# app/routers/offenders.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.utils.deps import get_db
from app.db import models as m
from app.schemas.offender import OffenderCreateIn, OffenderOut
from typing import List, Any, Dict
import json
import logging
import re

# LLM provider (널리 쓰는 llm_providers.py 사용)
import app.services.llm_providers as llm_providers
# langchain message helper
from langchain_core.messages import SystemMessage, HumanMessage

router = APIRouter(tags=["offenders"])
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# 프롬프트: 범행 '단계(step)'(행동/절차) 중심으로 4~7개 생성을 강제
# ─────────────────────────────────────────────────────────
LLM_PROMPT_TEMPLATE = """
당신은 교육/연구용 모의훈련 설계자입니다.
아래 정보를 바탕으로 **범행 단계(행동/절차)** 를 **4~7개** 생성하세요.
각 단계는 '행동·절차'를 간결하게 설명하는 한 문장(짧게)이어야 합니다.
예시: "보이스피싱 조직 콜센터 상담원이 수사관을 사칭하여 피해자에게 전화" 처럼,
발화(대사) 형태가 아닌 '무슨 일이 일어나는가' 수준의 단계여야 합니다.

- Offender Type: {offender_type}
- Purpose: {purpose}

요구사항:
1) 출력형식은 반드시 엄격한 JSON 하나: {{ "steps": ["단계1", "단계2", ...] }}
2) 단계 수는 4~7개 사이여야 함(LLM이 상황 판단해 개수 결정)
3) 각 step은 6~20 단어 내외의 간결한 행동/절차 문장
4) 개인정보/민감행위(계좌번호/주민등록번호/원격제어/비번/OTP 등) 구체 요구 문구 포함 금지
5) 출력에 설명, 코드블럭, 마크다운, 추가 텍스트를 섞지 말고 JSON만 내보내세요.
""".strip()

SENSITIVE_PATTERNS = [
    r"계좌번호", r"주민등록번호", r"원격제어", r"비밀번호", r"OTP", r"카드번호", r"인증번호"
]

def _contains_sensitive(s: str) -> bool:
    for p in SENSITIVE_PATTERNS:
        if re.search(p, s, flags=re.IGNORECASE):
            return True
    return False

def _extract_json_substring(maybe_text: str) -> str | None:
    """
    LLM 응답에 ```json ... ``` 같은 코드블럭이나 설명이 있어도
    가장 바깥의 JSON 객체(최초 '{'부터 마지막 '}'까지)를 추출해 반환.
    실패하면 None.
    """
    if not maybe_text:
        return None
    # Remove markdown code fences first (they may contain JSON)
    text = maybe_text.strip()
    # If fence blocks exist, join their contents to increase chance of correct JSON
    fences = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fences:
        candidate = "\n".join(fences)
        # try to find JSON in candidate
        m = re.search(r"(\{[\s\S]*\})", candidate)
        if m:
            return m.group(1)
    # fallback: find first '{' and last '}' in whole text
    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        return m.group(1)
    return None

def _parse_steps_from_text_to_list(text: str, max_steps: int = 7) -> List[str]:
    """
    안전 파싱:
    1) JSON 부분 추출 -> json.loads -> steps 배열 얻기
    2) 실패 시 줄/콤마 분리로 문장 후보 뽑기
    3) 결과 정제(공백제거), 4~7개 보정(잘라내기/보강)
    """
    MIN_STEPS, MAX_STEPS = 4, max_steps
    steps: List[str] = []

    json_sub = _extract_json_substring(text)
    if json_sub:
        try:
            j = json.loads(json_sub)
            if isinstance(j, dict) and isinstance(j.get("steps"), list):
                for s in j["steps"]:
                    if isinstance(s, str) and s.strip():
                        steps.append(s.strip())
        except Exception:
            # continue to fallbacks
            pass

    # fallback 1: try direct json.loads of whole text
    if not steps:
        try:
            j = json.loads(text)
            if isinstance(j, dict) and isinstance(j.get("steps"), list):
                for s in j["steps"]:
                    if isinstance(s, str) and s.strip():
                        steps.append(s.strip())
        except Exception:
            pass

    # fallback 2: lines that look like steps
    if not steps:
        # split by newlines and by comma, prioritize lines
        lines = [ln.strip(" \"' \t,-") for ln in text.splitlines() if ln.strip()]
        # filter out lines that are too long explanatory sentences (>120 chars)
        for ln in lines:
            if 5 <= len(ln) <= 200:
                steps.append(ln)
        if not steps:
            # try comma-separated chunks
            parts = re.split(r"[,\n]+", text)
            for p in parts:
                p = p.strip(" \"' \t-")
                if 5 <= len(p) <= 200:
                    steps.append(p)

    # final sanitization: remove any lines that clearly look like dialogue (quotes, '공격자:' 포함)
    sanitized = []
    for s in steps:
        s2 = re.sub(r"^(\"|'|`)+", "", s).strip()
        s2 = re.sub(r"^(공격자:|피해자:)\s*", "", s2)  # strip role prefixes
        if s2 and not s2.lower().startswith("note:") and len(s2) > 3:
            sanitized.append(s2)
    steps = sanitized

    # remove duplicates while preserving order
    seen = set()
    uniq = []
    for s in steps:
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    steps = uniq

    # length adjustments
    if len(steps) > MAX_STEPS:
        steps = steps[:MAX_STEPS]

    if len(steps) < MIN_STEPS:
        # fillers (행동/절차 중심으로 자연스럽게 보강)
        fillers = [
            "조직원이 피해자에게 검수/수사관을 사칭하여 초기 연락을 시도한다.",
            "피해자를 안심시키기 위해 공문서·기관명을 도용하여 신뢰를 형성한다.",
            "추가 확인 또는 조치 명목으로 피해자에게 절차적 요구를 전달한다.",
            "금전 전달을 위해 현금수거책 또는 송금 방식을 지시한다.",
            "사후 정리(증거 은닉/연락 차단)를 위해 후속 지침을 전달한다.",
        ]
        i = 0
        while len(steps) < MIN_STEPS and i < len(fillers):
            steps.append(fillers[i])
            i += 1
        # if still short, duplicate last with suffix
        while len(steps) < MIN_STEPS:
            steps.append((steps[-1] if steps else f"(목적 미정) 절차적 접촉을 시도한다.") + " (보강)")

    return steps[:MAX_STEPS]

async def _generate_steps_4to7_clean(offender_type: str, purpose: str) -> List[str]:
    """
    agent_chat을 사용해 JSON으로 받으려 시도하고, 다양한 포맷도 견딤.
    """
    llm = llm_providers.agent_chat(temperature=0.2)
    prompt = LLM_PROMPT_TEMPLATE.format(offender_type=offender_type, purpose=purpose)
    msgs = [
        SystemMessage(content="너는 윤리적 제약을 준수하는 모의훈련 설계자다. 반드시 JSON 형식만 출력."),
        HumanMessage(content=prompt),
    ]
    try:
        # LangChain ChatOpenAI 인스턴스의 async 호출 인터페이스 사용
        resp = await llm.ainvoke(msgs)
        # resp may be LangChain message object or plain string
        text = getattr(resp, "content", None) or str(resp)
    except Exception as e:
        logger.exception("LLM 호출 실패: %s", e)
        raise HTTPException(status_code=502, detail="LLM 호출 실패")

    # parse to steps robustly
    steps = _parse_steps_from_text_to_list(text, max_steps=7)

    # sensitivity check
    for s in steps:
        if _contains_sensitive(s):
            raise HTTPException(status_code=400, detail="민감정보(계좌/주민번호 등) 유도가 포함되어 생성 중단되었습니다.")

    # ensure final count 4~7
    if len(steps) < 4:
        # fill handled in parser; re-run to be safe
        steps = _parse_steps_from_text_to_list(text, max_steps=7)
    if len(steps) < 4:
        # last-resort fillers
        fillers = [
            "조직원이 피해자에게 검수/수사관을 사칭하여 초기 연락을 시도한다.",
            "가짜 기관·사이트로 유인하여 개인정보 입력을 유도한다.",
            "수사·조사 명목으로 금전 이동 또는 대출 절차를 요구한다.",
            "현금수거책이 피해자를 방문하여 현금을 수령한다.",
        ]
        i = 0
        while len(steps) < 4 and i < len(fillers):
            steps.append(fillers[i])
            i += 1

    return steps[:7]

# ─────────────────────────────────────────────────────────
# 기존 엔드포인트들 (원본 그대로 — 건드리지 않음)
# ─────────────────────────────────────────────────────────

@router.post("/make/offenders/", response_model=OffenderOut)
def create_offender(payload: OffenderCreateIn, db: Session = Depends(get_db)):
    obj = m.PhishingOffender(
        name=payload.name,
        type=payload.type,
        profile=payload.profile.model_dump(),  # JSONB에 그대로 저장
        source=(payload.source.model_dump() if payload.source else None),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@router.get("/offenders/", response_model=List[OffenderOut])
def get_offenders(db: Session = Depends(get_db)):
    return db.query(m.PhishingOffender).all()

@router.get("/offenders/{offender_id}", response_model=OffenderOut)
def get_offender(offender_id: int, db: Session = Depends(get_db)):
    return db.get(m.PhishingOffender, offender_id)

@router.get("/offenders/by-type/{type_name}", response_model=List[OffenderOut])
def get_offenders_by_type(type_name: str, db: Session = Depends(get_db)):
    return (
        db.query(m.PhishingOffender)
        .filter(m.PhishingOffender.type == type_name)
        .order_by(m.PhishingOffender.id)
        .all()
    )

# ─────────────────────────────────────────────────────────
# 신규: type+pupose만으로 LLM이 4~7개 '범행 단계'를 생성 → JSON으로 DB 저장
# ─────────────────────────────────────────────────────────

@router.post("/make/offenders/auto", response_model=OffenderOut)
async def create_offender_auto(payload: OffenderCreateIn, db: Session = Depends(get_db)):
    """
    사용자는 type + profile.purpose만 입력.
    서버가 LLM으로 4~7개의 '행동/절차 단계'를 생성해서 profile.steps에 JSON으로 저장.
    """
    if not payload.profile or not getattr(payload.profile, "purpose", None):
        raise HTTPException(status_code=400, detail="profile.purpose가 필요합니다.")

    steps = await _generate_steps_4to7_clean(
        offender_type=payload.type,
        purpose=payload.profile.purpose,
    )

    profile_dict: Dict[str, Any] = {
        "purpose": payload.profile.purpose,
        "steps": steps,
    }
    source_dict: Dict[str, Any] = payload.source.model_dump() if payload.source else {}
    if not source_dict:
        source_dict = {"title": "custom", "page": "custom", "url": "custom"}

    obj = m.PhishingOffender(
        name=payload.name,
        type=payload.type,
        profile=profile_dict,
        source=(source_dict if source_dict else None),
        is_active=True,
    )
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    except Exception as e:
        db.rollback()
        logger.exception("DB 저장 실패: %s", e)
        raise HTTPException(status_code=500, detail="DB 저장 실패")

    return obj
