# app/services/agent/tools_admin.py

from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
from uuid import UUID

import os
import json
import ast
import httpx
import re
import inspect

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.db import models as m
from app.core.logging import get_logger

# (중요) 요약/판정기는 "턴 리스트(JSON)"만으로 판정하도록 설계
# summarize_run_full(turns=List[Dict[str, Any]]) 시그니처를 권장
# 만약 기존 summarize_run_full이 (db, case_id, run_no)만 받는다면,
# 해당 파일도 turns 기반 시그니처로 업데이트하세요.
from app.services.admin_summary import summarize_run_full  # turns 기반 사용 권장

# ★ 추가: LLM 호출용
from app.services.llm_providers import agent_chat

# ★★ 추가: 동적 지침 생성기(2안)
from app.services.agent.guidance_generator import DynamicGuidanceGenerator

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────────────────────
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://127.0.0.1:5177")  # 운영 시 외부 MCP 주소로 설정

def _env_flag(names: List[str], default: bool) -> bool:
    """
    여러 env 키를 동시에 지원하기 위한 bool 파서.
    - true: 1, true, yes, y, on
    - false: 0, false, no, n, off
    """
    truthy = {"1", "true", "yes", "y", "on"}
    falsy  = {"0", "false", "no", "n", "off"}
    for k in names:
        v = os.getenv(k)
        if v is None:
            continue
        s = v.strip().lower()
        if s in truthy:
            return True
        if s in falsy:
            return False
    return default

# ✅ emotion tool ON/OFF 스위치(.env)
# - 어떤 키를 쓰든 동작하게 후보 다 지원
EMOTION_TOOL_ENABLED = _env_flag(
    ["TOOLS_EMOTION_ENABLED", "EMOTION_ENABLED", "USE_EMOTION_TOOL", "ENABLE_EMOTION", "VP_EMOTION_ENABLED"],
    default=True,
)

# ─────────────────────────────────────────────────────────
# 공통: {"data": {...}} 입력 통일
# ─────────────────────────────────────────────────────────
class SingleData(BaseModel):
    data: Any = Field(..., description="이 안에 실제 페이로드를 담는다")


def _to_dict(obj: Any) -> Dict[str, Any]:
    """
    admin.* 툴에 들어오는 data를 dict로 정규화.
    """
    # Pydantic 모델 처리
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()

    # 이미 dict면 그대로 반환
    if isinstance(obj, dict):
        return obj

    # 문자열이 아니면 에러
    if not isinstance(obj, str):
        raise HTTPException(status_code=422, detail=f"data는 JSON 객체여야 합니다. got type: {type(obj).__name__}")

    s = (obj or "").strip()
    if not s:
        raise HTTPException(status_code=422, detail="data가 비어있습니다.")

    logger.info("[_to_dict] 입력 길이: %d자", len(s))

    # ─────────────────────────────────────────────────────────
    # 안전한 전처리: LangChain/툴 로그 prefix, 코드펜스 제거
    # ─────────────────────────────────────────────────────────
    def _strip_wrappers(text: str) -> str:
        t = text.strip()
        # 예: "Action Input: {...}"
        m = re.search(r"(?:Action Input:|action_input:)\s*([\{\[].*)$", t, flags=re.IGNORECASE | re.DOTALL)
        if m:
            t = m.group(1).strip()
        # 코드펜스 제거
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
            t = t.strip()
        return t

    # ─────────────────────────────────────────────────────────
    # (추가) JSON 조각이 끝까지 닫히지 않았을 때, 부족한 닫는 괄호를 자동으로 보정
    # ─────────────────────────────────────────────────────────
    def _balance_json_fragment(text: str) -> Optional[str]:
        """
        첫 '{' 또는 '['부터 끝까지를 가져온 뒤,
        문자열 영역은 무시하고 스택 기반으로 부족한 닫는 괄호를 자동으로 붙인다.
        - LLM이 tool input 끝 괄호를 하나 빼먹는 케이스를 복구하기 위함
        """
        t = _strip_wrappers(text)
        if not t:
            return None

        start = None
        for i, ch in enumerate(t):
            if ch in "{[":
                start = i
                break
        if start is None:
            return None

        s2 = t[start:]
        stack: List[str] = []
        in_str = False
        esc = False

        for ch in s2:
            if in_str:
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    stack.append("}")
                elif ch == "[":
                    stack.append("]")
                elif ch in ("}", "]"):
                    if stack and stack[-1] == ch:
                        stack.pop()

        if stack:
            s2 = s2 + "".join(reversed(stack))
        return s2

    # ─────────────────────────────────────────────────────────
    # 첫 번째로 "완결되는" JSON 조각만 추출 (추가 텍스트/로그 섞임 방지)
    # ─────────────────────────────────────────────────────────
    def _extract_first_json_fragment(text: str) -> Optional[str]:
        t = _strip_wrappers(text)
        if not t:
            return None

        start = None
        start_ch = None
        for i, ch in enumerate(t):
            if ch in "{[":
                start = i
                start_ch = ch
                break
        if start is None or start_ch is None:
            return None

        end_ch = "}" if start_ch == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(t)):
            ch = t[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == start_ch:
                    depth += 1
                elif ch == end_ch:
                    depth -= 1
                    if depth == 0:
                        return t[start : j + 1]
        return None

    # ─────────────────────────────────────────────────────────
    # JSON 문자열 내부에서만 invalid escape 제거 (예: "\}" -> "}")
    # ─────────────────────────────────────────────────────────
    _VALID_ESC = set('"\\/bfnrtu')
    def _fix_invalid_escapes_in_strings(text: str) -> str:
        out: List[str] = []
        in_str = False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == '"' and (i == 0 or text[i-1] != "\\"):
                in_str = not in_str
                out.append(ch)
                i += 1
                continue
            if in_str and ch == "\\" and i + 1 < len(text):
                nxt = text[i + 1]
                # 유효한 escape면 그대로 둠
                if nxt in _VALID_ESC:
                    out.append("\\")
                    out.append(nxt)
                    i += 2
                    continue
                # invalid escape면 백슬래시 제거하고 문자만 남김
                out.append(nxt)
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    # ─────────────────────────────────────────────────────────
    # JSON 문자열 내부의 실제 제어문자(\n,\r,\t)를 escape 처리
    # (바깥 텍스트는 건드리지 않음)
    # ─────────────────────────────────────────────────────────
    def _escape_control_chars_in_strings(text: str) -> str:
        out: List[str] = []
        in_str = False
        esc = False
        for ch in text:
            if in_str:
                if esc:
                    out.append(ch)
                    esc = False
                    continue
                if ch == "\\":
                    out.append(ch)
                    esc = True
                    continue
                if ch == '"':
                    out.append(ch)
                    in_str = False
                    continue
                # 문자열 내부 제어문자만 이스케이프
                if ch == "\n":
                    out.append("\\n"); continue
                if ch == "\r":
                    out.append("\\r"); continue
                if ch == "\t":
                    out.append("\\t"); continue
                out.append(ch)
                continue
            else:
                if ch == '"':
                    out.append(ch)
                    in_str = True
                    continue
                out.append(ch)
        return "".join(out)

    # ─────────────────────────────────────────────────────────
    # 파싱 루틴: "추출 → json.loads → (escape fixes) → 재시도"
    # ─────────────────────────────────────────────────────────
    def _parse_json_dict(candidate: str) -> Optional[Dict[str, Any]]:
        c = candidate.strip()
        if not c:
            return None
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
            # 배열이면 기존 호환을 위해 dict로 감싸기
            if isinstance(v, list):
                return {"data": v}
            return None
        except json.JSONDecodeError as e:
            # invalid escape / control char 케이스만 단계적으로 수정
            msg = (e.msg or "").lower()
            c2 = c
            changed = False
            if "invalid" in msg and "escape" in msg:
                c2 = _fix_invalid_escapes_in_strings(c2)
                changed = True
            if "invalid control character" in msg:
                c2 = _escape_control_chars_in_strings(c2)
                changed = True
            if changed and c2 != c:
                try:
                    v2 = json.loads(c2)
                    if isinstance(v2, dict):
                        logger.info("[_to_dict] escape/control 보정 후 파싱 성공")
                        return v2
                    if isinstance(v2, list):
                        return {"data": v2}
                except json.JSONDecodeError:
                    pass
            return None

    # 1) 원문에서 바로 시도
    s0 = _strip_wrappers(s)
    v = _parse_json_dict(s0)
    if v is not None:
        logger.info("[_to_dict] 1단계 성공 (전체 문자열)")
        return v

    # 2) 첫 JSON 조각만 추출해서 시도
    frag = _extract_first_json_fragment(s0)
    if frag:
        logger.info("[_to_dict] 2단계: JSON 조각 추출 (%d자)", len(frag))
        v = _parse_json_dict(frag)
        if v is not None:
            logger.info("[_to_dict] 2단계 성공 (조각 파싱)")
            return v

    # 2.5) (추가) 괄호 누락/미완결 JSON 복구 시도
    balanced = _balance_json_fragment(s0)
    # balance는 "끝 괄호"만 붙이므로, 뒤에 로그/문장이 섞여 있으면 Extra data가 날 수 있음.
    # => balanced 결과에서 다시 "첫 번째로 완결되는 JSON 조각"만 뽑아서 파싱한다.
    frag2 = None
    if balanced:
        frag2 = _extract_first_json_fragment(balanced) or balanced

    if frag2 and frag2 != frag:
        logger.info("[_to_dict] 2.5단계: JSON 보정+조각 추출 (%d자)", len(frag2))
        v = _parse_json_dict(frag2)
        if v is not None:
            logger.info("[_to_dict] 2.5단계 성공 (보정 조각 파싱)")
            return v

    # 3) 최후: python literal_eval (JSON 유사 dict일 때만)
    #    (단, 이건 안전을 위해 매우 제한적으로 사용)
    try:
        maybe = ast.literal_eval(s0)
        if isinstance(maybe, dict):
            logger.info("[_to_dict] 3단계 성공 (literal_eval)")
            return maybe
    except Exception:
        pass

    # 실패: 더 이상 "고쳐쓰기" 하지 말고 원인 파악 가능한 로그만 남기고 종료
    head = s0[:500]
    tail = s0[-500:] if len(s0) > 500 else s0
    logger.error("[_to_dict] 파싱 실패")
    logger.error("[_to_dict] 입력 앞 500자: %s", head)
    logger.error("[_to_dict] 입력 뒤 500자: %s", tail)

    # 에러 위치를 남기기 위해 json.loads를 한번 더 시도해 위치 로그
    try:
        ctx = (frag2 or frag or s0)
        json.loads(ctx)
    except json.JSONDecodeError as e:
        logger.error("[_to_dict] JSONDecodeError: %s (pos=%d, len=%d)", e.msg, e.pos, len(ctx))
        cs = max(0, e.pos - 120)
        ce = min(len(ctx), e.pos + 120)
        logger.error("[_to_dict] 에러 주변(±120): %s", ctx[cs:ce])

    raise HTTPException(status_code=422, detail="data는 JSON 객체여야 합니다. 파싱 실패.")


def _unwrap_data(obj: Any) -> Dict[str, Any]:
    """
    SingleData(data=...) 구조를 풀어서 실제 payload(dict)를 반환.
    - {"case_id": "...", "run_no": 1, ...}
    - {"data": {...}}
    - 'Action Input: {"data":{...}}'
    전부 허용.
    """
    d = _to_dict(obj)

    inner = d.get("data")
    if isinstance(inner, dict):
        return inner

    return d


def _normalize_kind(val: Any) -> str:
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("{"):
            try:
                parsed = json.loads(s)
            except Exception:
                try:
                    parsed = ast.literal_eval(s)
                except Exception:
                    raise HTTPException(status_code=422, detail="kind 형식 오류")
            k = parsed.get("kind") or parsed.get("type")
            if isinstance(k, str):
                return k
        return s
    raise HTTPException(status_code=422, detail="kind는 문자열이어야 합니다.")


# ─────────────────────────────────────────────────────────
# 입력 스키마
# ─────────────────────────────────────────────────────────
class _JudgeReadInput(BaseModel):
    case_id: UUID
    run_no: int = Field(1, ge=1)


class _JudgeMakeInput(BaseModel):
    case_id: UUID
    run_no: int = Field(1, ge=1)
    # 오케스트레이터가 바로 턴을 넘겨줄 수 있게 허용
    turns: Optional[List[Dict[str, Any]]] = None
    log: Optional[Dict[str, Any]] = None
    # ✅ 추가: 오케스트레이터가 계산한 HMM 결과를 같이 넘길 수 있게
    hmm: Optional[Dict[str, Any]] = None
    hmm_result: Optional[Dict[str, Any]] = None


class _GuidanceInput(BaseModel):
    kind: str = Field(..., pattern="^(P|A)$", description="지침 종류: 'P'(피해자) | 'A'(공격자)")


class _SavePreventionInput(BaseModel):
    case_id: UUID
    offender_id: int
    victim_id: int
    run_no: int = Field(1, ge=1)
    summary: str
    steps: List[str] = Field(default_factory=list)


# ★ 추가: 최종예방책 생성 입력
class _MakePreventionInput(BaseModel):
    case_id: UUID
    rounds: int = Field(..., ge=1)
    turns: List[Dict[str, Any]] = Field(default_factory=list)
    judgements: List[Dict[str, Any]] = Field(default_factory=list)
    guidances: List[Dict[str, Any]] = Field(default_factory=list)
    # 포맷은 고정적으로 personalized_prevention을 기대
    format: str = Field("personalized_prevention")


# ─────────────────────────────────────────────────────────
# 터미널 조건(라운드5 또는 critical) 판단 헬퍼
# ─────────────────────────────────────────────────────────
def _is_terminal_case(rounds: int, judgements: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    rounds 가 5 이상이거나, judgements 중 risk.level == 'critical' 이 하나라도 있으면 터미널로 간주.
    return: (is_terminal, reason)  # reason in {"round5", "critical", "not_terminal"}
    """
    logger.info(f"[_is_terminal_case] rounds={rounds}, judgements count={len(judgements or [])}")

    try:
        if rounds >= 5:
            return True, "round5"

        for idx, j in enumerate(judgements or []):
            logger.info(f"[_is_terminal_case] judgement[{idx}]: {j}")

            risk = j.get("risk")
            logger.info(f"[_is_terminal_case] risk={risk}")

            if risk:
                lvl = str(risk.get("level", "")).lower()
                logger.info(f"[_is_terminal_case] level={lvl}")

                if lvl == "critical":
                    logger.info(f"[_is_terminal_case] ✓ CRITICAL 발견!")
                    return True, "critical"
    except Exception as e:
        logger.error(f"[_is_terminal_case] Exception: {e}")

    return False, "not_terminal"


# ─────────────────────────────────────────────────────────
# MCP에서 대화 턴(JSON) 가져오기
# ─────────────────────────────────────────────────────────
def _fetch_turns_from_mcp(case_id: UUID, run_no: int) -> List[Dict[str, Any]]:
    """
    MCP가 제공하는 대화로그(JSON) 엔드포인트에서 특정 라운드의 전체 턴을 받아온다.
    기대 형식: [{"role": "attacker"|"victim"|"system", "text": "...", "meta": {...}}, ...]
    기본 엔드포인트 가정: GET {MCP_BASE_URL}/api/cases/{case_id}/turns?run={run_no}
    """
    url = f"{MCP_BASE_URL}/api/cases/{case_id}/turns"
    params = {"run": run_no}
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            r = client.get(url, params=params, headers={"Accept": "application/json"})
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            logger.error(f"[MCP] JSON 파싱 실패. status={r.status_code}, text_head={r.text[:300]!r}")
            raise
    except Exception as e:
        logger.error(f"[MCP] 대화 로그 조회 실패: {e}")
        raise HTTPException(status_code=502, detail=f"MCP 대화로그 조회 실패: {e}")

    turns: Any = None
    if isinstance(data, dict):
        if "turns" in data:
            turns = data["turns"]
        elif "result" in data and isinstance(data["result"], dict) and "turns" in data["result"]:
            turns = data["result"]["turns"]
        else:
            if all(isinstance(v, list) for v in data.values()):
                turns = next(iter(data.values()))
    elif isinstance(data, list):
        turns = data

    if not isinstance(turns, list):
        raise HTTPException(status_code=502, detail="MCP 응답에서 turns 배열을 찾을 수 없습니다.")
    return turns  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────
# 판정 결과 저장 / 조회 (DB는 결과 저장·조회에만 사용)
# ─────────────────────────────────────────────────────────
def _persist_verdict(
    db: Session,
    *,
    case_id: UUID,
    run_no: int,
    verdict: Dict[str, Any],
) -> bool:
    """
    verdict 예:
      {
        "phishing": False,
        "evidence": "...",
        "risk": {"score": 10, "level": "low", "rationale": "..."},
        "victim_vulnerabilities": [...],
        "continue": {"recommendation": "continue", "reason": "..."}
      }
    """
    success = False

    # 1) AdminCaseSummary가 있으면 라운드별로 저장/업서트
    try:
        if hasattr(m, "AdminCaseSummary"):
            Model = m.AdminCaseSummary
            row = (
                db.query(Model)
                .filter(Model.case_id == case_id, Model.run == run_no)
                .first()
            )
            if not row:
                row = Model(case_id=case_id, run=run_no)
                db.add(row)

            row.phishing = bool(verdict.get("phishing", False))

            if hasattr(Model, "evidence"):
                setattr(row, "evidence", str(verdict.get("evidence", ""))[:4000])

            risk = verdict.get("risk") or {}
            if hasattr(Model, "risk_score"):
                setattr(row, "risk_score", int(risk.get("score", 0) or 0))
            if hasattr(Model, "risk_level"):
                setattr(row, "risk_level", str(risk.get("level", "") or ""))
            if hasattr(Model, "risk_rationale"):
                setattr(row, "risk_rationale", str(risk.get("rationale", "") or "")[:2000])

            if hasattr(Model, "vulnerabilities"):
                setattr(row, "vulnerabilities", verdict.get("victim_vulnerabilities", []))
            if hasattr(Model, "verdict_json"):
                setattr(row, "verdict_json", verdict)

            success = True
    except Exception as e:
        logger.warning(f"[admin.make_judgement] AdminCaseSummary 저장/업데이트 실패: {e}")

    # 2) 항상 AdminCase에 최신 요약 + 히스토리 라인 누적
    try:
        case = db.get(m.AdminCase, case_id)
        if not case:
            try:
                case = m.AdminCase(
                    id=case_id,
                    scenario={},
                    phishing=False,
                    status="running",
                    defense_count=0,
                )
                db.add(case)
                db.flush()
            except Exception as e:
                logger.warning(f"[admin.make_judgement] AdminCase 생성 실패: {e}")
                if success:
                    try:
                        db.commit()
                    except Exception:
                        pass
                return success

        case.phishing = bool(getattr(case, "phishing", False) or verdict.get("phishing", False))

        risk = verdict.get("risk") or {}
        cont = verdict.get("continue") or {}

        if hasattr(case, "last_run_no"):
            case.last_run_no = run_no
        if hasattr(case, "last_risk_score"):
            case.last_risk_score = int(risk.get("score", 0) or 0)
        if hasattr(case, "last_risk_level"):
            case.last_risk_level = str(risk.get("level", "") or "")
        if hasattr(case, "last_risk_rationale"):
            case.last_risk_rationale = str(risk.get("rationale", "") or "")
        if hasattr(case, "last_vulnerabilities"):
            case.last_vulnerabilities = verdict.get("victim_vulnerabilities", [])
        if hasattr(case, "last_recommendation"):
            case.last_recommendation = str(cont.get("recommendation", "") or "")
        if hasattr(case, "last_recommendation_reason"):
            case.last_recommendation_reason = str(cont.get("reason", "") or "")

        prev = (case.evidence or "").strip()
        piece = json.dumps({"run": run_no, "verdict": verdict}, ensure_ascii=False)
        case.evidence = (prev + ("\n" if prev else "") + piece)[:8000]

        success = True
        db.commit()
        return success

    except Exception as e:
        logger.warning(f"[admin.make_judgement] AdminCase 저장 실패: {e}")
        try:
            db.commit()
        except Exception:
            pass
        return bool(success)


def _read_persisted_verdict(db: Session, *, case_id: UUID, run_no: int) -> Optional[Dict[str, Any]]:
    # 1) AdminCaseSummary 우선
    try:
        if hasattr(m, "AdminCaseSummary"):
            Model = m.AdminCaseSummary
            row = (
                db.query(Model)
                .filter(Model.case_id == case_id, Model.run == run_no)
                .first()
            )
            if row:
                ev = ""
                if hasattr(row, "evidence") and getattr(row, "evidence", None):
                    ev = row.evidence
                elif hasattr(row, "reason") and getattr(row, "reason", None):
                    ev = row.reason

                risk: Dict[str, Any] = {}
                if hasattr(row, "risk_score"):
                    risk["score"] = int(getattr(row, "risk_score", 0) or 0)
                if hasattr(row, "risk_level"):
                    risk["level"] = getattr(row, "risk_level", None) or ""
                if hasattr(row, "risk_rationale"):
                    risk["rationale"] = getattr(row, "risk_rationale", None) or ""

                vul: List[Any] = []
                if hasattr(row, "vulnerabilities") and getattr(row, "vulnerabilities", None):
                    vul = list(row.vulnerabilities or [])

                if hasattr(row, "verdict_json") and getattr(row, "verdict_json", None):
                    vj = dict(row.verdict_json or {})
                    vj.setdefault("evidence", ev)
                    vj.setdefault("risk", risk or {"score": 0, "level": "", "rationale": ""})
                    vj.setdefault("victim_vulnerabilities", vul)
                    vj.setdefault("phishing", bool(getattr(row, "phishing", False)))
                    vj.setdefault("continue", {"recommendation": "continue", "reason": ""})
                    return vj

                return {
                    "phishing": bool(getattr(row, "phishing", False)),
                    "evidence": ev,
                    "risk": risk or {"score": 0, "level": "", "rationale": ""},
                    "victim_vulnerabilities": vul,
                    "continue": {"recommendation": "continue", "reason": ""},
                }
    except Exception:
        pass

    # 2) Fallback: AdminCase.evidence에서 run별 JSON 찾기
    try:
        case = db.get(m.AdminCase, case_id)
        raw = (getattr(case, "evidence", "") or "")
        for line in raw.splitlines():
            try:
                obj = json.loads(line)
                if int(obj.get("run", -1)) == run_no and isinstance(obj.get("verdict"), dict):
                    return obj["verdict"]
            except Exception:
                continue
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────
# LLM 결과 파싱 보조
# ─────────────────────────────────────────────────────────
def _safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """
    코드펜스/설명 섞여도 '첫 번째로 완결되는 JSON(객체/배열)'만 추출해 파싱.
    Extra data(뒤에 설명 문장 붙음) 오류를 크게 줄인다.
    """
    text = (text or "").strip()

    def _strip_code_fence(s: str) -> str:
        s = s.strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
            s = re.sub(r"\s*```$", "", s)
        return s.strip()

    def _extract_first_json_fragment(s: str) -> Optional[str]:
        s = _strip_code_fence(s)
        if not s:
            return None

        start = None
        start_ch = None
        for idx, ch in enumerate(s):
            if ch in "{[":
                start = idx
                start_ch = ch
                break
        if start is None or start_ch is None:
            return None

        end_ch = "}" if start_ch == "{" else "]"
        depth = 0
        in_str = False
        esc = False

        for j in range(start, len(s)):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == start_ch:
                    depth += 1
                elif ch == end_ch:
                    depth -= 1
                    if depth == 0:
                        return s[start:j + 1]
        return None

    frag = _extract_first_json_fragment(text)
    if not frag:
        return None

    try:
        obj = json.loads(frag)
        if isinstance(obj, dict):
            return obj
        # 배열이면 dict로 감싸서 기존 호출부 안전
        return {"data": obj}
    except Exception:
        try:
            obj = ast.literal_eval(frag)
            if isinstance(obj, dict):
                return obj
            return {"data": obj}
        except Exception:
            return None


# ─────────────────────────────────────────────────────────
# 툴 팩토리
# ─────────────────────────────────────────────────────────
def make_admin_tools(db: Session, guideline_repo):
    # generator가 repo를 받는 버전/안받는 버전 둘 다 대비
    try:
        dynamic_generator = DynamicGuidanceGenerator(guideline_repo=guideline_repo)
    except TypeError:
        dynamic_generator = DynamicGuidanceGenerator()

    def _call_with_signature_filter(fn, **kwargs):
        """
        ✅ 함수 시그니처에 존재하는 키워드만 골라 호출 (TypeError 방지)
        - generator 메서드 파라미터가 바뀌어도 안전하게 동작
        """
        sig = inspect.signature(fn)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return fn(**filtered)

    def _normalize_previous_judgments(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        ✅ previous_judgements(오타) / previous_judgments(정상) 둘 다 허용
        """
        pj = payload.get("previous_judgments")
        if pj is None:
            pj = payload.get("previous_judgements")
        return pj if isinstance(pj, list) else []
    def _looks_labeled_turns(turns: List[Dict[str, Any]]) -> bool:
        """
        tools_emotion(label_emotions_on_turns) 결과 turns인지 최소 휴리스틱 검증.
        - victim 턴에 pred4/pred8/probs4/probs8/emotion/hmm 관련 키가 조금이라도 있으면 OK
        """
        if not isinstance(turns, list) or not turns:
            return False

        victim_seen = 0
        labeled_seen = 0

        for t in turns:
            if not isinstance(t, dict):
                continue
            role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()
            if role != "victim":
                continue
            victim_seen += 1

            # tools_emotion에서 붙을 법한 키들
            if any(k in t for k in ("pred4", "pred8", "probs4", "probs8", "emotion", "emotion4", "emotion8")):
                labeled_seen += 1
                continue
            meta = t.get("meta")
            if isinstance(meta, dict) and any(k in meta for k in ("hmm", "hmm_result", "emotion", "pred4", "pred8")):
                labeled_seen += 1

        # victim이 없으면(이상) False
        if victim_seen == 0:
            return False
        # victim 턴 중 최소 1개라도 라벨 흔적이 있으면 OK
        return labeled_seen > 0

    @tool(
        "admin.make_judgement",
        args_schema=SingleData,
        description="(case_id, run_no)의 전체 대화를 MCP JSON 또는 전달받은 turns로 판정한다. DB는 결과 저장에만 사용한다."
    )
    def make_judgement(data: Any) -> Dict[str, Any]:
        logger.info("[admin.make_judgement] raw data type=%s repr=%r", type(data), data)
        payload = _unwrap_data(data)
        try:
            ji = _JudgeMakeInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"JudgeMakeInput 검증 실패: {e}")

        turns: Optional[List[Dict[str, Any]]] = ji.turns

        if turns is None and ji.log and isinstance(ji.log, dict):
            maybe = ji.log.get("turns")
            if isinstance(maybe, list):
                turns = maybe
        # ✅ emotion OFF 모드면: turns 미전달도 허용 → MCP에서 raw turns 재조회
        # ✅ emotion ON 모드면: 기존처럼 라벨링된 turns 강제
        if turns is None:
            if EMOTION_TOOL_ENABLED:
                raise HTTPException(
                    status_code=422,
                    detail="turns가 없습니다. tools_emotion에서 라벨링된 turns를 받아 admin.make_judgement에 전달해야 합니다."
                )
            turns = _fetch_turns_from_mcp(ji.case_id, ji.run_no)
        # ✅ emotion ON일 때만 "라벨링 흔적" 검증
        if EMOTION_TOOL_ENABLED:
            if isinstance(turns, list) and not _looks_labeled_turns(turns):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "turns에 감정/라벨 정보가 보이지 않습니다. "
                        "MCP 원본 turns가 아니라 tools_emotion(label_victim_emotions) 결과 turns를 전달해야 합니다."
                    )
                )
        # ✅ HMM 결과 추출 (payload 우선, log에 있으면 fallback)
        hmm_payload: Optional[Dict[str, Any]] = None
        if isinstance(ji.hmm, dict):
            hmm_payload = ji.hmm
        elif isinstance(ji.hmm_result, dict):
            hmm_payload = ji.hmm_result
        elif ji.log and isinstance(ji.log, dict):
            maybe_hmm = ji.log.get("hmm") or ji.log.get("hmm_result")
            if isinstance(maybe_hmm, dict):
                hmm_payload = maybe_hmm

        # ✅ emotion OFF면 hmm 신호도 사용하지 않음(정합성 유지)
        if not EMOTION_TOOL_ENABLED:
            hmm_payload = None

        # summarize_run_full이 기대하는 최소 필드(role/text)로 정규화
        normalized_turns: List[Dict[str, Any]] = []
        for t in (turns or []):
            if not isinstance(t, dict):
                continue
            role = t.get("role") or t.get("speaker") or t.get("type")
            text = t.get("text") or t.get("content") or t.get("message")
            if role is None and isinstance(t.get("meta"), dict):
                role = t["meta"].get("role")
            if text is None and isinstance(t.get("meta"), dict):
                text = t["meta"].get("text")
            if role is None or text is None:
                # 그래도 원본 보존(디버깅)
                normalized_turns.append(t)
                continue
            normalized_turns.append({**t, "role": str(role), "text": str(text)})
        try:
            # ✅ summarize_run_full이 혹시 hmm 인자를 지원하면 전달(미래 대비)
            kwargs = {"turns": normalized_turns}
            try:
                sig = inspect.signature(summarize_run_full)
                if hmm_payload and "hmm" in sig.parameters:
                    kwargs["hmm"] = hmm_payload
            except Exception:
                pass
            verdict = summarize_run_full(**kwargs)
        except TypeError as te:
            logger.error("[admin.make_judgement] summarize_run_full가 turns 기반 시그니처를 지원해야 합니다.")
            raise HTTPException(
                status_code=500,
                detail="summarize_run_full이 'turns' 인자를 지원하도록 업데이트해 주세요."
            ) from te

        # ✅ verdict에도 hmm을 같이 실어두면 이후 generate_guidance/저장에서도 사용 가능
        if hmm_payload and isinstance(verdict, dict):
            verdict.setdefault("signals", {})
            if isinstance(verdict["signals"], dict):
                verdict["signals"].setdefault("hmm", hmm_payload)

        risk = verdict.get("risk") or {}
        score = int(risk.get("score", 0) or 0)
        score = 0 if score < 0 else (100 if score > 100 else score)
        risk["score"] = score

        level = str((risk.get("level") or "").lower())
        if level not in {"low", "medium", "high", "critical"}:
            level = (
                "critical" if score >= 75 else
                "high" if score >= 50 else
                "medium" if score >= 25 else
                "low"
            )
        risk["level"] = level
        verdict["risk"] = risk

        if level == "critical":
            verdict["continue"] = {
                "recommendation": "stop",
                "reason": "위험도가 critical로 판정되어 시뮬레이션을 종료합니다."
            }
        else:
            verdict["continue"] = {
                "recommendation": "continue",
                "reason": "위험도가 critical이 아니므로 다음 라운드를 진행합니다."
            }

        persisted = _persist_verdict(db, case_id=ji.case_id, run_no=ji.run_no, verdict=verdict)
        if not persisted:
            try:
                logger.warning("[admin.make_judgement] persisted=False → 1회 재시도")
                persisted = _persist_verdict(db, case_id=ji.case_id, run_no=ji.run_no, verdict=verdict)
            except Exception:
                pass

        # ★ 연속 피싱 실패 시 외부 API 호출 체크
        external_api_result = None
        try:
            from app.services.agent.external_api import check_and_trigger_external_api
            phishing_result = bool(verdict.get("phishing", False))

            external_api_result = check_and_trigger_external_api(
                case_id=str(ji.case_id),
                phishing=phishing_result,
                turns=normalized_turns,
                scenario={},  # 필요 시 payload에서 추출
                victim_profile={},
                guidance={},
                judgement=verdict,
                round_no=ji.run_no,
            )

            if external_api_result and external_api_result.get("triggered"):
                logger.info(
                    "[admin.make_judgement] 외부 API 호출됨: %s",
                    external_api_result.get("reason")
                )
        except Exception as e:
            logger.warning("[admin.make_judgement] 외부 API 체크 실패: %s", e)

        result = {
            "ok": True,
            "persisted": persisted,
            "case_id": str(ji.case_id),
            "run_no": ji.run_no,
            **verdict,
        }

        # 외부 API 결과가 있으면 포함
        if external_api_result:
            result["external_api"] = external_api_result

        return result

    @tool(
        "admin.judge",
        args_schema=SingleData,
        description="(case_id, run_no)의 **저장된 판정**을 조회한다. 저장된 결과가 없으면 '없음'을 알려준다."
    )
    def judge(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        try:
            ji = _JudgeReadInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"JudgeInput 검증 실패: {e}")

        saved = _read_persisted_verdict(db, case_id=ji.case_id, run_no=ji.run_no)
        if saved is not None:
            return {
                "ok": True,
                "phishing": bool(saved.get("phishing", False)),
                "reason": str(saved.get("evidence", "")),  # 기존 호환
                "run_no": ji.run_no,
                "evidence": saved.get("evidence", ""),
                "risk": saved.get("risk", {"score": 0, "level": "", "rationale": ""}),
                "victim_vulnerabilities": saved.get("victim_vulnerabilities", []),
                "continue": saved.get("continue", {"recommendation": "continue", "reason": ""}),
            }

        return {
            "ok": False,
            "case_id": str(ji.case_id),
            "run_no": ji.run_no,
            "message": "저장된 라운드 판정이 없습니다. admin.make_judgement를 먼저 호출하세요."
        }

    @tool(
        "admin.generate_guidance",
        args_schema=SingleData,
        description=(
            "판정결과(위험도/취약점/피싱여부/근거) + (선택) 시나리오/피해자/이전판정을 바탕으로 "
            "공격자용 맞춤 지침을 생성한다. 예: {'data': {'case_id':UUID,'run_no':int,"
            "'scenario':{...},'victim_profile':{...},'previous_judgements':[...]} }"
        )
    )
    def generate_guidance(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        case_id = payload.get("case_id")
        run_no = int(payload.get("run_no") or payload.get("round_no") or 1)

        try:
            case_uuid = UUID(str(case_id))
        except Exception:
            return {"ok": False, "error": "invalid_case_id", "message": "case_id must be UUID"}

        verdict = _read_persisted_verdict(db, case_id=case_uuid, run_no=run_no)
        if not verdict:
            return {"ok": False, "error": "no_saved_verdict", "message": "admin.make_judgement 이후 호출하세요."}

        scenario = payload.get("scenario") or {}
        victim_profile = payload.get("victim_profile") or {}
        previous_judgments = _normalize_previous_judgments(payload)

        try:
            # ✅ 여기서 터지던 핵심 원인 해결:
            # - guideline_repo: generate_guidance()가 안 받는 경우가 많음 → 시그니처 필터링으로 자동 제거
            # - previous_judgements 오타 → previous_judgments로 정규화
            #
            # 또한 generator 구현에 따라 run_no/round_no 명칭이 다를 수 있어 둘 다 넣고,
            # 시그니처에 있는 것만 전달한다.
            kwargs = dict(
                db=db,
                case_id=str(case_uuid),
                run_no=run_no,
                round_no=run_no,
                scenario=scenario,
                victim_profile=victim_profile,
                verdict=verdict,
                previous_judgments=previous_judgments,
                guideline_repo=guideline_repo,  # 있으면 전달, 없으면 자동 제거
            )

            result = _call_with_signature_filter(dynamic_generator.generate_guidance, **kwargs)
        except Exception as e:
            logger.exception("[admin.generate_guidance] 실패")
            return {"ok": False, "error": f"generator_failed: {e!s}"}

        return {
            "ok": True,
            "type": "A",
            "전략": result.get("전략", ""),
            "수법": result.get("수법", ""),
            "감정": result.get("감정", ""),
            "reasoning": result.get("reasoning", ""),
            "expected_effect": result.get("expected_effect", ""),
            "risk_level": (verdict.get("risk") or {}).get("level", ""),
            "targets": verdict.get("victim_vulnerabilities", []),
            "source": "dynamic_generator+verdict"
        }

    @tool(
        "admin.make_prevention",
        args_schema=SingleData,
        description=(
            "대화(turns)+판단(judgements)+지침(guidances)로 최종 예방책(personalized_prevention) JSON을 생성한다. "
            "Action Input 예: {'data': {'case_id':UUID,'rounds':int,'turns':[...],'judgements':[...],'guidances':[...],'format':'personalized_prevention'}}"
        )
    )
    def make_prevention(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        try:
            pi = _MakePreventionInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"MakePreventionInput 검증 실패: {e}")

        is_term, _reason = _is_terminal_case(pi.rounds, pi.judgements)
        if not is_term:
            return {
                "ok": False,
                "error": "not_terminal",
                "message": "prevention can be generated only at round 5+ or when risk is critical",
                "rounds": pi.rounds,
            }

        llm = agent_chat(temperature=0.2)

        schema_hint = {
            "personalized_prevention": {
                "summary": "string (2~3문장)",
                "analysis": {
                    "outcome": "success|fail",
                    "reasons": ["string", "string", "string"],
                    # verdict에서 critical도 올 수 있어 허용 범위 확장
                    "risk_level": "low|medium|high|critical"
                },
                "steps": ["명령형 한국어 단계 5~9개"],
                "tips": ["체크리스트형 팁 3~6개"]
            }
        }

        system = (
            "너는 보이스피싱 예방 전문가다. 입력된 대화/판단/지침을 바탕으로, "
            "아래 스키마에 맞춘 JSON만 출력하라. 한국어로 간결하고 실용적으로 작성하라. "
            "코드블럭/주석/설명 금지. 오직 JSON 한 개만 반환."
        )
        user = {
            "case_id": str(pi.case_id),
            "rounds": pi.rounds,
            "guidances": pi.guidances,
            "judgements": pi.judgements,
            "turns": pi.turns,
            "format": pi.format,
            "schema": schema_hint
        }

        messages = [
            ("system", system),
            ("human",
             "다음 입력을 바탕으로 'personalized_prevention' 키 하나만 있는 JSON을 출력하라.\n"
             + json.dumps(user, ensure_ascii=False))
        ]

        try:
            res = llm.invoke(messages)
            text = getattr(res, "content", str(res))
            parsed = _safe_json_parse(text) or {}
            if "personalized_prevention" not in parsed:
                return {
                    "ok": False,
                    "error": "missing_key_personalized_prevention",
                    "raw": text[:1200]
                }
            return {
                "ok": True,
                "case_id": str(pi.case_id),
                "personalized_prevention": parsed["personalized_prevention"]
            }
        except Exception as e:
            return {"ok": False, "error": f"llm_error: {e!s}"}

    @tool(
        "admin.save_prevention",
        args_schema=SingleData,
        description="개인화된 예방책을 DB에 저장한다. {'data': {'case_id':UUID,'offender_id':int,'victim_id':int,'run_no':int,'summary':str,'steps':[str,...]}}"
    )
    def save_prevention(data: Any) -> str:
        payload = _unwrap_data(data)
        try:
            spi = _SavePreventionInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"SavePreventionInput 검증 실패: {e}")

        try:
            q = (
                db.query(m.PersonalizedPrevention)
                .filter(
                    m.PersonalizedPrevention.case_id == spi.case_id,
                    m.PersonalizedPrevention.is_active == True  # noqa: E712
                )
            )
            if hasattr(m.PersonalizedPrevention, "created_at"):
                q = q.order_by(m.PersonalizedPrevention.created_at.desc())
            else:
                q = q.order_by(m.PersonalizedPrevention.id.desc())
            existing = q.first()
            if existing:
                return str(existing.id)
        except Exception:
            pass

        obj = m.PersonalizedPrevention(
            case_id=spi.case_id,
            offender_id=spi.offender_id,
            victim_id=spi.victim_id,
            run=spi.run_no,
            content={"summary": spi.summary, "steps": spi.steps},
            note="agent-generated",
            is_active=True,
        )
        db.add(obj)
        db.commit()
        return str(obj.id)

    return [make_judgement, judge, generate_guidance, make_prevention, save_prevention]
