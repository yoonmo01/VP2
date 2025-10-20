from __future__ import annotations

from sqlalchemy.orm import Session
from uuid import UUID
from app.db import models as m
from app.services.llm_providers import admin_chat  # ADMIN_MODEL 사용
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json, re
import statistics  # ✅ 추가: 평균 계산용

# =========================
# LLM 프롬프트 (전체 대화: 공격자+피해자)
# =========================
PROMPT_FULL_DIALOG = """
당신은 연구용 보이스피싱 분석가입니다.
아래 **전체 대화 로그(공격자+피해자)** 를 읽고, 피해 발생 여부와 위험도, 취약성, 다음 라운드 진행 권고를 **JSON으로만** 출력하세요.

[중요 전제]
- 대화가 아직 종료되지 않았을 수 있음. **현재까지의 로그만** 근거로 판정하고, 미래 상황은 가정하지 말 것.
- '공격자' 발화는 맥락 제공용이며, **판정은 결국 피해자의 실제 실행/확약/전달 발화가 핵심 증거**가 되어야 함.
- 아래 [판정 기준]과 [위험도 가이드]를 준수.

[판정 기준] (하나라도 충족 시 phishing=true)
A) **금전 이동 완료/직접 시도**
   - “송금/이체/입금/출금/인출/ATM/보관함(락커) 넣음/현금 전달/안전계좌” 등 **실제 금전 이동** 완료 또는 즉시 실행 단계
   - 신규·대환·카드론 등 **대출 실행** 후 금액을 범인 측에 전달
B) **민감 금융·인증 정보 제공**
   - 주민등록번호, 계좌번호, **통장 비밀번호**, 보안카드 번호, **OTP/인증번호**, 카드 CVC/유효기간, 공동/공동인증서 비밀번호 등 제공
C) **디지털 접근 허용(피싱 경유)**
   - **QR코드 접속**, **의심 링크 클릭**, **악성앱 설치/실행**, **원격제어 앱(AnyDesk/TeamViewer 등) 설치·승인**
D) **사칭에 따른 실행**
   - 가족·지인·수사기관·금융기관 사칭에 속아 **송금/인출/계좌·비밀번호 제공/앱 설치**가 발생
E) **지속적 고신뢰 + 명시적 실행 의사(실행 직전 단계)**   # ← 누적/지속 반영
   - 다음 중 **하나 이상** 충족 **AND** 피해자 발화에 “신청하겠다/설치하겠다/보내겠다/이체하겠다/승인하겠다” 등 **구체적 실행 의사**가 명시되면,
     **phishing=true로 판단**하라. (단, 금전/민감정보/앱/원격제어가 **미발생**이면 risk는 **high** 범위에 제한)
     (1) 최근 3턴의 설득도 평균 **last3_avg ≥ 8**
     (2) **연속 2턴 이상** 설득도 **≥ 9**
     (3) 전체 대화에서 설득도 **≥ 9**가 **3회 이상** 발생
   - **단일 스파이크(한 번만 10점)** 은 실행 의사/행동이 동반되지 않으면 phishing 판단의 직접 근거로 보지 말 것

[phishing=false 판단] (모두 충족 시에만)
1. 위 A~D 이벤트가 **전혀 발생하지 않음**
2. 현재까지 **피해자 발화 기준**으로 금전 이동·민감정보 제공·앱/링크 실행이 **발생하지 않음**
3. 피해자가 대표번호 재확인/지점 방문/신고/거절/통화 종료 등으로 **명확히 방어**하고 이후 실행이 없음

[위험도 가이드] (risk.score ∈ [0,100], risk.level ∈ {{low, medium, high, critical}})
- critical(75~100): 금전 이동 완료/직접 시도, OTP·비번 등 핵심정보 제공, 원격제어 허용 등 **피해 실현/임박**
- high(50~74): 링크 클릭/QR·앱 설치 등 실행 전 단계가 복수 확인, 다수 설득 징후, 금전 이전 직전
- medium(25~49): 일부 흔들림(의심 링크 열람 시도 등)이나 설득 진행 중, 아직 핵심 실행 없음
- low(0~24): 일관된 방어/검증, 의심 시그널 탐지, 실행 징후 없음

[신뢰도(is_convinced) 참고 가이드]
- is_convinced: 0=전혀 안 믿음 ~ 10=매우 설득됨.
- **스파이크 vs 지속**: 단발성 최고점(예: 10)이 한 번만 나타나면 과대평가하지 말고, **최근 평균/연속 고점/고신뢰 빈도** 등 **지속성**을 우선 고려.
- 피해 발생 여부와 위험도 판정 시, **설득도 추이(최대/평균/최근 평균/연속 고점/고신뢰 빈도)**와 **피해자 발화의 실행 의사 표현**을 함께 종합할 것.

[취약성(victim_vulnerabilities) 예시]
- “권위/긴급 호소에 취약”, “검증 없이 링크/QR 응답”, “금융 지식 부족”, “원격제어/앱 설치 거부 약함”, “개인정보 요구에 관대” 등
- 최대 3~6개, 간결한 문장형

[다음 라운드 진행 권고(continue)]
- {{\"recommendation\":\"continue\"|\"stop\",\"reason\":\"...\"}}
- 예: 위험도 높음/판정 true → \"stop\" 또는 \"continue\" (교육/추가 검증 목적에 따라), 판단 근거를 명확히 서술
- 본 시스템은 훈련 시뮬레이션이므로, 피드백/보호 조치를 위해 **합리적 권고**를 제시

[출력 형식] (아주 엄격)
- 오직 JSON 객체 1개만 출력(코드블록/설명/주석 금지)
- 최상위 키(정확히 5개): \"phishing\", \"evidence\", \"risk\", \"victim_vulnerabilities\", \"continue\"
- \"phishing\": true | false
- \"evidence\": 한 단락(2~4문장) 요약 + **핵심 발화 2~6개**를 turn_index와 역할을 함께 인용
  - 인용 예: turn 7 [피해자] \\\"700만원 송금했어요\\\", turn 10 [피해자] \\\"락커 24번에 넣었습니다\\\"
  - 큰따옴표는 반드시 \\\" 로 이스케이프할 것
- \"risk\": {{\"score\": 정수 0~100, \"level\": \"low\"|\"medium\"|\"high\"|\"critical\", \"rationale\": \"한 단락\"}}
- \"victim_vulnerabilities\": [문자열, ...] (3~6개)
- \"continue\": {{\"recommendation\":\"continue\"|\"stop\",\"reason\":\"한 단락\"}}
- **문자열 내부에서 \" 는 반드시 \\\" 로 이스케이프.** (어렵다면 『 』 사용 가능)

[참고 시나리오]
{scenario}

[대화 로그]
{dialog}

[신뢰도 통계 요약]
{conviction}
""".strip()

# =========================
# 포맷터 (턴 리스트 → 문자열)
# =========================
def _format_dialog_from_turns(turns: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for i, t in enumerate(turns, start=1):
        role = t.get("role", "")
        role_ko = "공격자" if role in ("offender", "attacker") else "피해자"
        text = t.get("text") or t.get("content") or ""
        lines.append(f"{i} [{role_ko}] {text}")
    return "\n".join(lines)

def _format_dialog_full_run(db: Session, case_id: UUID, run_no: int) -> str:
    rows = (
        db.query(m.ConversationLog)
        .filter(
            m.ConversationLog.case_id == case_id,
            m.ConversationLog.run == run_no,
        )
        .order_by(m.ConversationLog.turn_index.asc())
        .all()
    )
    if not rows:
        return ""
    out: List[str] = []
    for r in rows:
        role_ko = "공격자" if r.role == "offender" else "피해자"
        out.append(f"{r.turn_index} [{role_ko}] {r.content or ''}")
    return "\n".join(out)

def _scenario_string(db: Session, case_id: UUID) -> str:
    case = db.get(m.AdminCase, case_id)
    if not case:
        return ""
    scen = getattr(case, "scenario", None)
    if isinstance(scen, (dict, list)):
        return json.dumps(scen, ensure_ascii=False)
    return str(scen or "")

# ====== (신규) 신뢰도 요약 유틸 ======
def _extract_is_convinced_from_text(text: str) -> Optional[int]:
    """
    피해자 텍스트에서 is_convinced (정수 0-10) 추출.
    JSON 우선 파싱 → 실패 시 정규식 백업.
    """
    if not text:
        return None
    s = text.strip()
    # JSON 파싱 시도
    try:
        if s.startswith("{"):
            obj = json.loads(_normalize_quotes(_strip_code_fences(s)))
            v = obj.get("is_convinced")
            if isinstance(v, (int, float)):
                return max(0, min(10, int(v)))
    except Exception:
        pass
    # 정규식 백업
    m = re.search(r'"?is_convinced"?\s*[:=]\s*(\d{1,2})', s)
    if m:
        try:
            return max(0, min(10, int(m.group(1))))
        except Exception:
            return None
    return None

def _conviction_summary_text_from_turns(turns: List[Dict[str, Any]]) -> str:
    """
    피해자 턴의 is_convinced를 누적/지속 지표까지 계산해 프롬프트에 제공.
    - last3_avg: 최근 3턴 평균
    - high_count(>=9): 9점 이상 빈도
    - max_consec_high(>=9): 9점 이상 연속 최장 길이
    - rising_trend: 최근 3턴 단조 증가 & 마지막이 8 이상
    - intent_count: 실행 의사 키워드 등장 횟수(피해자 dialogue 기준)
    - intent_hits_turns: 키워드가 등장한 피해자 턴 인덱스(1부터, 최대 5개 표시)
    """
    vals: List[int] = []
    last: Optional[int] = None

    # 실행 의사(신청/설치/이체/송금/보내/승인 등) 키워드
    intent_keywords = [
        # 신청
        "신청", "신청하겠", "신청할게", "신청할께", "신청합니다", "신청드립", "신청 진행",
        # 설치
        "설치", "설치하겠", "설치할게", "설치합니다",
        # 송금/이체/전송
        "이체", "송금", "보내겠", "보내드리겠", "보냅니다", "보낼게", "전송하겠", "전송합니다",
        # 승인/동의
        "승인하겠", "승인합니다", "동의하겠", "동의합니다",
        # 계좌/번호 제공 의사
        "계좌 알려", "계좌번호 알려", "번호 알려", "계좌 보내", "계좌 드리",
    ]

    # 피해자 dialogue 텍스트 추출용(피해자 JSON이면 "dialogue"만)
    def _extract_dialogue_text(text: str) -> str:
        if not text:
            return ""
        s = text.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(_normalize_quotes(_strip_code_fences(s)))
                dlg = obj.get("dialogue")
                if isinstance(dlg, str):
                    return dlg
            except Exception:
                pass
        return s  # JSON 아니면 전체를 그대로

    intent_hits: List[int] = []
    for idx, t in enumerate(turns, start=1):
        role = t.get("role")
        if role not in ("victim", "피해자"):
            continue

        raw = (t.get("text") or t.get("content") or "").strip()
        # is_convinced
        v = _extract_is_convinced_from_text(raw)
        if v is not None:
            vals.append(v)
            last = v

        # 실행 의사 키워드 탐지(피해자 실제 대화문으로)
        dlg = _extract_dialogue_text(raw)
        if dlg:
            if any(k in dlg for k in intent_keywords):
                intent_hits.append(idx)

    if not vals:
        # 그래도 intent 신호가 있으면 그 정보만 노출
        if intent_hits:
            return f"설득도 정보 없음, intent_count={len(intent_hits)}, intent_hits_turns={intent_hits[:5]}"
        return "설득도 정보 없음"

    avg = statistics.mean(vals)
    last3_avg = statistics.mean(vals[-3:]) if len(vals) >= 3 else avg

    high_count = sum(1 for x in vals if x >= 9)
    # 9점 이상 연속 최장
    max_consec_high = 0
    cur = 0
    for x in vals:
        if x >= 9:
            cur += 1
            max_consec_high = max(max_consec_high, cur)
        else:
            cur = 0

    rising_trend = False
    if len(vals) >= 3:
        a, b, c = vals[-3], vals[-2], vals[-1]
        rising_trend = (a <= b <= c) and (c >= 8)

    intent_count = len(intent_hits)

    return (
        f"count={len(vals)}, max={max(vals)}, avg={avg:.2f}, last={last}, "
        f"last3_avg={last3_avg:.2f}, high_count(>=9)={high_count}, "
        f"max_consec_high(>=9)={max_consec_high}, rising_trend={str(rising_trend)}, "
        f"intent_count={intent_count}, intent_hits_turns={intent_hits[:5]}, raw={vals}"
    )

# ====== JSON 파싱 유틸 (생략 없이 기존 코드 유지) ======
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _normalize_quotes(s: str) -> str:
    return (
        s.replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2018", "'").replace("\u2019", "'")
    )

def _escape_braces(s: str) -> str:
    """str.format 사용 전, 대화/시나리오 내부의 { } 를 이스케이프해 KeyError 방지"""
    return (s or "").replace("{", "{{").replace("}", "}}")

def _extract_json_with_balancing(s: str) -> str:
    start = s.find("{")
    if start == -1:
        return s.strip()
    stack = []
    in_str = False
    esc = False
    end = None
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in ("}", "]"):
                if stack and stack[-1] == ch:
                    stack.pop()
                    if not stack:
                        end = i
                        break
    if end is not None:
        return s[start:end + 1]
    balanced = s[start:]
    while stack:
        balanced += stack.pop()
    return balanced

def _escape_inner_quotes_for_value_of(key: str, text: str) -> str:
    pat = re.compile(rf'("{re.escape(key)}"\s*:\s*")(?P<val>.*)(")\s*(?=[,}}])', re.S)
    def _fix(m: re.Match) -> str:
        val = m.group("val")
        val_fixed = re.sub(r'(?<!\\)"', r'\\"', val)
        return m.group(1) + val_fixed + m.group(3)
    return pat.sub(_fix, text)

def _json_loads_lenient_full(s: str) -> Dict[str, Any]:
    s0 = _normalize_quotes(_strip_code_fences(s))
    raw = _extract_json_with_balancing(s0)

    def _sanitize(d: Dict[str, Any]) -> Dict[str, Any]:
        phishing = bool(d.get("phishing", False))
        evidence = str(d.get("evidence", ""))

        risk = d.get("risk") or {}
        score = int(risk.get("score", 0))
        if score < 0: score = 0
        if score > 100: score = 100
        level = str(risk.get("level") or "")
        if level not in {"low", "medium", "high", "critical"}:
            level = (
                "critical" if score >= 75 else
                "high"     if score >= 50 else
                "medium"   if score >= 25 else
                "low"
            )
        rationale = str(risk.get("rationale", ""))

        vul = d.get("victim_vulnerabilities") or []
        if not isinstance(vul, list):
            vul = [str(vul)]
        vul = [str(x) for x in vul][:6]

        cont = d.get("continue") or {}
        rec = cont.get("recommendation") or ("stop" if level == "critical" else "continue")
        reason = str(cont.get("reason", "")) or (
            "위험도가 critical로 판정되어 시나리오를 종료합니다."
            if rec == "stop" else
            "위험도가 critical이 아니므로 수법 고도화/추가 라운드 진행을 권고합니다."
        )

        return {
            "phishing": phishing,
            "evidence": evidence,
            "risk": {"score": score, "level": level, "rationale": rationale},
            "victim_vulnerabilities": vul,
            "continue": {"recommendation": rec, "reason": reason},
        }

    try:
        return _sanitize(json.loads(raw))
    except Exception:
        pass

    fixed_min = re.sub(r'(:\s*)0+(\d+)(\s*[,\}])', r': \2\3', raw)
    fixed_min = re.sub(r",(\s*[}\]])", r"\1", fixed_min)
    try:
        return _sanitize(json.loads(fixed_min))
    except Exception:
        pass

    fixed_esc = _escape_inner_quotes_for_value_of("evidence", fixed_min)
    return _sanitize(json.loads(fixed_esc))

# =========================
# 메인: 라운드별 전체대화 판정
# =========================
def summarize_run_full(
    db: Optional[Session] = None,
    case_id: Optional[UUID] = None,
    run_no: Optional[int] = None,
    turns: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    - turns 인자가 있으면 그것을 그대로 사용
    - 없으면 (db, case_id, run_no) 기반으로 DB에서 불러오기
    """
    if turns is not None:
        dialog = _format_dialog_from_turns(turns)
        scenario_str = ""  # MCP JSON으로 넘어오는 경우 시나리오 문자열은 생략 가능
        conviction_text = _conviction_summary_text_from_turns(turns)  # ✅ 추가
    else:
        if db is None or case_id is None or run_no is None:
            raise ValueError("summarize_run_full: turns 또는 (db, case_id, run_no) 중 하나는 제공해야 합니다.")
        dialog = _format_dialog_full_run(db, case_id, run_no)
        scenario_str = _scenario_string(db, case_id)
        # DB rows를 turns 형태로 단순 변환하여 신뢰도 추출
        rows = (
            db.query(m.ConversationLog)
            .filter(
                m.ConversationLog.case_id == case_id,
                m.ConversationLog.run == run_no,
            )
            .order_by(m.ConversationLog.turn_index.asc())
            .all()
        )
        tmp_turns = [{"role": r.role, "text": r.content} for r in rows]
        conviction_text = _conviction_summary_text_from_turns(tmp_turns)  # ✅ 추가

    if not dialog.strip():
        return {
            "phishing": False,
            "evidence": "대화가 없어 피해 여부를 판정할 수 없습니다.",
            "risk": {"score": 0, "level": "low", "rationale": "대화 없음"},
            "victim_vulnerabilities": [],
            "continue": {"recommendation": "continue", "reason": "분석할 대화가 없어 추가 수집 필요"},
        }

    llm = admin_chat()
    # ✅ conviction을 프롬프트에 주입
    prompt = PROMPT_FULL_DIALOG.format(
        scenario=_escape_braces(scenario_str),
        dialog=_escape_braces(dialog),
        conviction=_escape_braces(conviction_text),
    )
    resp = llm.invoke(prompt).content
    return _json_loads_lenient_full(resp)

# =========================
# 레거시 케이스 단위 판정
# =========================
def summarize_case(db: Session, case_id: UUID):
    case = db.get(m.AdminCase, case_id)
    if case is None:
        raise ValueError(f"AdminCase {case_id} not found")

    rows = (
        db.query(m.ConversationLog)
        .filter(m.ConversationLog.case_id == case_id)
        .order_by(m.ConversationLog.run.asc(), m.ConversationLog.turn_index.asc())
        .all()
    )
    if not rows:
        case.phishing = False
        case.evidence = "대화가 없어 피해 여부를 판정할 수 없음."
        case.status = "completed"
        case.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(case)
        return {"phishing": False, "evidence": case.evidence}

    lines: List[str] = []
    turns_like: List[Dict[str, Any]] = []  # ✅ 신뢰도 요약용
    for r in rows:
        role_ko = "공격자" if r.role == "offender" else "피해자"
        lines.append(f"run {r.run} :: {r.turn_index} [{role_ko}] {r.content or ''}")
        turns_like.append({"role": r.role, "text": r.content})
    dialog = "\n".join(lines)
    scenario_str = _scenario_string(db, case_id)
    conviction_text = _conviction_summary_text_from_turns(turns_like)  # ✅ 추가

    llm = admin_chat()
    prompt = PROMPT_FULL_DIALOG.format(
        scenario=_escape_braces(scenario_str),
        dialog=_escape_braces(dialog),
        conviction=_escape_braces(conviction_text),
    )
    resp = llm.invoke(prompt).content
    parsed = _json_loads_lenient_full(resp)

    case.phishing = bool(parsed.get("phishing", False))
    case.evidence = str(parsed.get("evidence", ""))
    case.status = "completed"
    case.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)

    return {"phishing": case.phishing, "evidence": case.evidence}
