# app/services/prompts.py (updated with dynamic guidance support)

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from textwrap import dedent
import json

# ─────────────────────────────────────────────────────────────
# (추가) PPSE 라벨 정의 (영어 원문 그대로)
# ─────────────────────────────────────────────────────────────
PPSE_LABELS_EN = """
## Authority

* **A1:** The scammer claims to have authority over the victim.
* **A2:** The scammer claims to have authority to access the information requested.
* **A3:** The scammer claims to be a member of a reputable institution.
* **A4:** The victim questions the authority of the scammer.
* **A5:** It is reasonable for the victim to believe that failure to comply with the scammer’s request will result in repercussions (e.g. loss of privileges, humiliation, condemnation) based on the scammer’s supposed authority.

---

## Commitment, reciprocation and consistency

* **C1:** The scammer performs a kind gesture or a favor toward the victim.
* **C2:** The scammer performs or claims to have performed a kind gesture toward someone other than the victim.
* **C3:** The scammer tries to obligate the victim to reciprocate a kind gesture.
* **C4:** The scammer states or implies that the victim has already committed to helping them (the scammer).
* **C5:** The scammer states or implies that the victim is committed to helping them based on the victim’s job or other obligations.
* **C6:** The scammer states or implies that, based on previous words or actions, it would be inconsistent for the victim to not help the scammer.
* **C7:** It is reasonable for the victim to believe that complying with the scammer’s request would implicate the victim in activity that is dishonest, illegal or in a legal gray area.

---

## Distraction

* **D1:** The scammer does something to heighten the victim’s emotional state (e.g. stress, surprise, anger, excitement).
* **D2:** The scammer gives the victim more information than they can process.
* **D3:** The scammer states or implies that the information they are requesting is time-sensitive.
* **D4:** The scammer states or implies that they are in a hurry or otherwise have limited time to converse with the victim.
* **D5:** The scammer states or implies that there is some benefit to complying with their request but that this benefit is of limited quantity.
* **D6:** The scammer attempts to distract the victim from thinking about the intentions or consequences related to the scammer’s request.
* **D7:** It is reasonable for the victim to believe that if they comply with the scammer’s request that they will personally benefit from it.
* **D8:** The scammer states or implies that the consequences of the victim’s actions are large.
* **D9:** It is reasonable for the victim to believe that if they do not comply with the scammer’s request that they will suffer negative consequences because of it.

---

## Social proof

* **S1:** It is reasonable for the victim to believe that complying with the scammer’s request will have benefits (including helping the scammer).
* **S2:** It is reasonable for the victim to believe that they will not be held solely responsible for any negative effects related to complying with the scammer’s request.
* **S3:** It is reasonable for the victim to believe that any risk associated with helping the scammer is shared by other people as well.
* **S4:** The scammer states or implies that the victim’s peers have helped the scammer in this manner in the past.
* **S5:** The scammer states or implies that it is socially correct to help them.
* **S6:** It is otherwise reasonable for the victim to believe that it is socially correct to help the scammer.
* **S7:** The scammer states or implies that if the victim does not comply with their request then the victim will be “left out” in some way.

---

## Non-persuasive / Procedural (Minimal persuasive function)

* **N1:** This utterance is primarily procedural or informational, with minimal persuasive function even within the current stage.
""".strip()

# ─────────────────────────────────────────────────────────────
# (추가) 절차(Procedure) 목록 블록 (Korean)
# ─────────────────────────────────────────────────────────────
PROCEDURE_LIST_KO = """
[절차(Procedure) 목록 — proc_code는 아래 중 하나만]
1-1 기망 대상 확인-(1) 전화 상대방 본인 여부 확인

2-1 자신 소개-(1) 자신이 사칭하고 있는 신분을 알려줌
2-2 자신 소개-(2) 전화한 목적을 알려줌

3-1 사건 소개-(1) 가상의 사건 인물을 알고 있는지 물어봄
3-2 사건 소개-(2) 가상의 사건 인물의 주소, 나이, 직업 등을 거론하면서 재차 알고 있는지 물어봄
3-3 사건 소개-(3) 가상의 사건 인물과 관련한 사건 내용을 설명하면서 사건 및 수사의 경위를 알려줌
3-4 사건 소개-(4) 시민 명의 통장이 범죄에 사용되었다고 혐의 형성
3-5 사건 소개-(5) 000 진술 언급하며 시민 명의 통장 구입 사실 고지
3-6 사건 소개-(6) 범죄에 연루된 통장에 대해서 알고 있는지 확인
3-7 사건 소개-(7) 대포통장이 시민이 직접 개설한 것인지 확인

4-1 사건 연루-(1) 설명하고 있는 사건 내용과 시민의 관련성에 대한 최초 발언
4-2 사건 연루-(2) 시민에 대해 객관적으로 사건과 관련성이 확인되었다고 알려줌
4-3 사건 연루-(3) 개인정보 도난 사실 확인
4-4 사건 연루-(4) 실제로 통장을 판매한 것인지 명의도용을 당한 것인지 확인
4-5 사건 연루-(5) 시민에게 통장을 판매 혹은 양도한 적이 있는지 물어봄
4-6 사건 연루-(6) 피해자 입증 절차를 진행해야 함을 고지
4-7 사건 연루-(7) 시민에게 통장 판매 및 양도한 사실이 확인되면 처벌받을 수 있음을 고지
4-8 사건 연루-(8) 통장을 직접 개설한 것이라고 압박
4-9 사건 연루-(9) 시민에게 범죄에 연루된 사람이 많고 명의도용 당한 피해자가 섞여 있다는 상황 설명
4-10 사건 연루-(10) 시민에게 범죄 혐의점이 없다고 알려줌
4-11 사건 연루-(11) 피해자로 추정되는 사람에게 전화 진술제를 통한 녹취 수사 진행 고지

5-1 녹취조사 준비-(1) 녹취 조사에 대한 필요성 고지
5-2 녹취조사 준비-(2) 녹취조사를 받도록 유도 및 동의 여부 확인
5-3 녹취조사 준비-(3) 시민에게 조사받는 사실을 유포하지 못하도록 함
5-4 녹취조사 준비-(4) 시민의 다른 계좌를 확인하려는 의도로 계좌추적을 하겠다고 함
5-5 녹취조사 준비-(5) 시민에게 사칭명, 사칭소속, 사칭기관을 메모하게 함
5-6 녹취조사 준비-(6) 녹취 조사가 법원에 제출할 서류이기 때문에 녹취 조사시 유의사항 알려줌
5-7 녹취조사 준비-(7) 전화 받는 환경 조성
5-8 녹취조사 준비-(8) 녹취 조사 시작을 시민에게 알림

6-1 녹취 조사-(1) 자기소개 및 시민의 이름, 나이, 주민번호 등 진술하도록 요구
6-2 녹취 조사-(2) 000을 아는지, 통장 개설 사실이 있는지, 범죄에 사용된 사실이 있는지 재차 확인
6-3 녹취 조사-(3) 통장 동결 처리 사실 고지
6-4 녹취 조사-(4) 다른 은행이 발견되면 동결 및 환수 조치 고지
6-5 녹취 조사-(5) 정상적으로 거래하는 은행 상호명 확인
6-6 녹취 조사-(6) 은행마다 개설한 계좌 수 및 용도 파악
6-7 녹취 조사-(7) 시민의 계좌에 있는 현금 확인
6-8 녹취 조사-(8) 시민 계좌에 보유하고 있는 금액 파악
6-9 녹취 조사-(9) 조사 결과 액수가 다를 경우 처벌받는다는 것을 고지
6-10 녹취 조사-(10) 통화가 끝나고 다음 일정 알림
6-11 녹취 조사-(11) 시민이 녹취 조사에 응하지 않을 경우 직접 나와서 조사를 받아야 한다며 소환장을 발부

[절차 선택(전진/회귀) 규칙 — “정해진 step 없음”]
- 매 턴, 직전 피해자 발화를 보고 proc_code를 하나 선택한다.
- 순서대로 진행할 의무는 없다.
- 기본적으로는 전진하되(중립/협조일 때), 피해자가 의심/질문/혼란이면 이전 단계로 회귀해서 재설명한다.
- 같은 proc_code를 2턴 연속 반복은 피한다(불가피하면 표현을 크게 바꾼다).

회귀 규칙 예시:
- “누구냐/진짜냐/왜 전화냐” → 2-1 또는 2-2로 회귀
- “그 사람 모르겠다” → 3-2 또는 3-3으로 회귀
- “무슨 통장이냐/말이 안 된다” → 3-6~3-7로 회귀
- “왜 녹취냐/동의 못한다” → 5-1 또는 5-2로 회귀
""".strip()

# ─────────────────────────────────────────────────────────────
# 1) (옵션) DB → 프롬프트 변수 변환
# ─────────────────────────────────────────────────────────────

def render_attacker_from_offender(offender: Dict[str, Any]) -> Dict[str, str]:
    name = offender.get("name")
    otype = offender.get("type")
    prof = offender.get("profile") or {}
    purpose = prof.get("purpose")
    steps: List[str] = prof.get("steps") or []
    lines: List[str] = []
    if name: lines.append(f"[시나리오명] {name}")
    if otype: lines.append(f"[유형] {otype}")
    if purpose: lines.append(f"[목적] {purpose}")
    if steps:
        lines.append("[단계]")
        lines.extend(f"- {s}" for s in steps)
    return {
        "scenario_title": name or "",
        "method_block": "\n".join(lines).strip(),
    }

# ─────────────────────────────────────────────────────────────
# 2) 공격자 프롬프트 (동적 지침 시스템 통합)
# ─────────────────────────────────────────────────────────────
ATTACKER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
     이것은 보이스피싱 상황을 가정한 **시뮬레이션 대화**다. 너는 공격자 역할의 발화 예시를 생성한다.

     [기본 규칙]
     - 오직 아래 [현재 단계]에 적힌 행동에 해당하는 대사만 말한다.
     - 다른 단계의 내용, 새로운 사실(앱/기관/계좌/금액 등) 발명 금지.
     - 문장 수 2~4, 350자 이내.
     - 캐릭터 대사 한 단락만 출력(요약/해설/메타설명 금지).

     [안전]
     - 실제 개인정보/실제 링크/실제 계좌/전화번호는 사용·요구하지 말고, 필요 시 가상 표기만 사용.

     [피해자 발화 해석 규칙(중요)]
     - 직전 피해자 발화가 JSON처럼 보이면 **dialogue 필드만** 발화로 간주하고 해석한다.
     - JSON의 **thoughts, is_convinced** 등 메타 정보는 **절대로 보거나 사용하지 않는다**.
     - JSON이 아니면 해당 텍스트 전체를 피해자의 실제 발화로 간주한다.

     [피해자 종료 신호 매핑(강제)]
     - 아래 [피해자 종료 신호] 중 **하나라도** 직전 피해자 **dialogue**에 포함되면,
       **즉시 한 줄로만** "여기서 마무리하겠습니다." 를 출력하고 종료한다(그 외 말 금지).
     - 이 매핑은 단독 종료 사유다.

    [피해자 종료 신호]
    - "대화를 종료" (예: "대화를 종료합니다", "대화 종료할게요")
    - "전화(를) 끊" (예: "전화를 끊겠습니다", "끊을게요", "이제 끊겠습니다")
    - "더 이상 (대화|통화) (원치 않|하지 않|안 하)" 
    - "필요 없습" / "관심 없습"
    - "그만 하(시|겠)죠" / "그만하시죠"

     [종결 규칙(완화·카운트형)]
     - 아래 [종결 조건] 중 **2개 이상**이 **같은 턴 또는 최근 2턴** 안에서 충족되면,
       **정확히 한 줄**로 **"여기서 마무리하겠습니다."**만 출력하고 즉시 종료한다.
     - 단, 조건 (C) **피싱 성공(핵심 요구가 완료됨)**이 충족되면 **단독으로도** 즉시 종료한다.
     - 종료가 아닌 경우에는 절대 위 문구를 말하지 않는다.

     [종결 조건]
     (A) 피해자가 이 대화를 보이스피싱/사기로 **인지·지목**함
     (B) 피해자가 **신고/차단/대표번호 확인/지점 방문** 등 **강한 거부 의사**를 밝힘
     (C) 공격자의 **핵심 요구**(이체/현금 전달/원격앱 설치/민감정보 제공 등)가 **완료됨**(=피싱 성공)
     (D) 피해자가 **제3자(은행/가족/경찰/지인 등)에게 확인/상담 의사**를 **구체적으로 표명**
     (E) 최근 **2턴 연속** 의미 있는 진전 없음(동일한 거절/의심/회피가 반복되어 설득 시도가 **무의미**하다고 판단)

     [종결 훅(프로토콜)]
     - 위 [피해자 종료 신호 매핑] 또는 [종결 조건]이 충족되면 **즉시** 다음 한 줄만 출력하고 종료한다:
       "여기서 마무리하겠습니다."
     - 이 문구를 출력한 뒤에는 어떤 말도 덧붙이지 않는다.

     [현재 단계]
     {current_step}

     [동적 전략 지침]
     {guidance_block}


     """),
    MessagesPlaceholder("history"),
    ("human", """
     마지막 피해자 발화(없으면 비어 있음):
     {last_victim}
     """)
])

def format_guidance_block(guidance_type: str = "",
                          guidance_text: str = "",
                          guidance_categories: List[str] = None,
                          guidance_reasoning: str = "") -> str:
    """동적으로 생성된 지침을 포맷팅합니다."""

    if not guidance_text or guidance_text.strip() == "":
        return "현재 라운드에서는 별도의 전략 지침이 제공되지 않았습니다. 기본적인 피싱 전략을 사용하세요."

    block_parts = []

    # 지침 유형
    if guidance_type:
        type_desc = {
            "A": "공격 강화 지침",
            "P": "피해자 보호 지침"
        }.get(guidance_type, "일반 지침")
        block_parts.append(f"[지침 유형] {type_desc}")

    # 적용 카테고리
    if guidance_categories:
        category_names = {
            "A": "어휘/어조 조절",
            "B": "긴급성 강조",
            "C": "감정적 접근",
            "D": "전문성 연출",
            "E": "점진적 요구",
            "F": "의심 무마",
            "G": "사칭 다변화",
            "H": "수법 복합화",
            "I": "심리적 압박",
            "J": "2차 피해 암시"
        }
        categories_desc = [
            category_names.get(cat, cat) for cat in guidance_categories
        ]
        block_parts.append(f"[적용 전략] {', '.join(categories_desc)}")

    # 구체적 지침
    block_parts.append(f"[구체적 지침] {guidance_text}")

    # 선택 근거 (디버깅용, 실제 프롬프트에는 포함하지 않을 수도 있음)
    if guidance_reasoning:
        block_parts.append(f"[전략 근거] {guidance_reasoning}")

    block_parts.append("""
[지침 적용 방법]
- 위 지침을 현재 단계의 표현·전략·어휘 선택에 적극적으로 반영한다.
- 지침이 요구하는 톤이나 접근법을 자연스럽게 대화에 녹여낸다.
- 단, 현재 단계의 기본 목표와 안전 규칙은 반드시 준수한다.
""")

    return "\n".join(block_parts)

# ─────────────────────────────────────────────────────────────
# 3) 피해자 프롬프트 (지침 참조 가능, 없으면 무시)
# ─────────────────────────────────────────────────────────────
def render_victim_from_profile(victim_data: dict) -> dict:
    return {
        "meta": victim_data.get("meta", "정보 없음"),
        "knowledge": victim_data.get("knowledge", "정보 없음"),
        "traits": victim_data.get("traits", "정보 없음"),
    }

VICTIM_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
     이것은 보이스피싱 시뮬레이션이고, 당신은 피해자 역할입니다.

     [캐릭터 정보]
     메타정보: {meta}
     지식정보: {knowledge}  
     성격정보: {traits}

     [상황 인식]
     - 현재 라운드: {current_round}
     - 이전 경험: {previous_experience}
     - 직전 설득도(is_convinced_prev): {is_convinced_prev}

     [응답 규칙]
     1. 반드시 JSON 형식 "한 줄"로만 응답하세요. 코드블록( ``` )·설명·주석 금지:
     {{
         "is_convinced": <0-10 사이의 숫자>,
         "thoughts": "(속마음을 괄호 안에)",
         "dialogue": "실제 말하는 대화"
     }}
     - is_convinced는 정수로만 출력 (문자열 금지)
     - 출력은 JSON 한 개만 (앞뒤 텍스트/빈 줄 금지)
     
     2. dialogue는 실제 사람처럼 짧고 자연스럽게 (1-2문장)
     3. thoughts는 캐릭터의 내면적 생각 (상대방은 모름)
     4. is_convinced는 현재까지 상대방 말을 얼마나 믿는지 (0=전혀 안믿음, 10=완전히 믿음)
        - 가능하면 is_convinced_prev를 기준으로 위 [변화 규칙]에 맞춰 -2~+2 내에서 조정
     
     [스케일 앵커]
     - 0~2: 강한 의심, 거절/확인 요구 지속
     - 3~4: 의심 유지, 소극적 응대
     - 5~6: 중립/동요, 실무적 확인·추가설명 요구
     - 7~8: 꽤 설득됨, 협조적
     - 9~10: 매우 설득됨, 민감정보/금전 요구에도 순응 직전

     [변화 규칙]
     - 현재 턴의 is_convinced는 이전 값에서 -2 ~ +2 범위 내에서만 변화
     - 공격자가 더 구체적·합리적 근거/권위/익숙한 절차를 제시하면 +1~2
     - 공격자가 반복/모순/위협/비현실적 요구를 하면 -1~2
     - 같은 패턴 반복 시 변화폭 축소(피로감으로 0 또는 -1 경향)

     5. 캐릭터의 지식수준과 성격에 맞게 반응
     6. 절대 시뮬레이션 종료 언급 금지 **(단, [종결 훅] 조건일 때는 예외)**
     7. 실제 개인정보는 제공하지 않음

    [종결 훅(프로토콜)]
    - **마지막 공격자 발화**가 정확히 "여기서 마무리하겠습니다." 인 경우,
    JSON을 출력하지 말고, **정확히 한 줄**로만 다음 문구를 출력하고 즉시 종료한다.
    "대화를 종료합니다."


     [응답 예시]
     {{
         "is_convinced": 3,
         "thoughts": "(목소리가 좀 어색한데? 진짜 택배사 맞나?)",
         "dialogue": "아, 그럼 어떻게 확인하죠?"
     }}
     """),
    MessagesPlaceholder("history"), 
    ("human", "{last_offender}")
])

def format_victim_guidance(round_no: int = 1,
                           previous_phishing_attempts: List[str] = None,
                           victim_knowledge_level: str = "medium") -> str:
    """피해자를 위한 상황별 가이드라인을 생성합니다.""" 

    if round_no == 1:
        return """현재 처음 받는 연락입니다. 캐릭터의 성격과 지식 수준에 따라 자연스럽게 반응하세요.
- 의심스러운 점이 있으면 질문하거나 확인을 요청할 수 있습니다.
"""

# ─────────────────────────────────────────────────────────────
# (추가) MCP에 직접 전달할 system 문자열 빌더들
# ─────────────────────────────────────────────────────────────
from typing import Optional

def build_guidance_block_from_meta(guidance: Optional[Dict[str, Any]]) -> str:
    """mcp.simulator_run(payload['guidance']) 형태 그대로 받아 guidance_block 문자열 생성"""
    # 기존 ATTACKER_PROMPT 처럼 "슬롯은 항상 채우되",
    # guidance가 없으면 기본 문구를 넣어 빈칸이 되지 않게 한다.
    if not guidance:
        return "현재 라운드에서는 별도의 전략 지침이 제공되지 않았습니다. 기본적인 전략을 사용하세요."
    return format_guidance_block(
        guidance_type=guidance.get("type", ""),
        guidance_text=guidance.get("text", "") or "",
        guidance_categories=guidance.get("categories", []) or [],
        guidance_reasoning=guidance.get("reasoning", "") or "",
    )

def _build_scenario_reference_block_v2(scenario: Dict[str, Any]) -> str:
    """
    V2는 steps/current_step 기반이 아니라, '직전 대화'로 절차를 전진/회귀한다.
    그래도 시나리오 메타(이름/유형/목적)가 있으면 참고용으로만 제공.
    - 없는 값은 출력하지 않음(발명 방지)
    - steps는 V2 설계상 강제가 아니므로 넣지 않음(혼선 방지)
    """
    if not scenario:
        return ""
    name = scenario.get("description", "") or scenario.get("name", "")
    typ  = scenario.get("type", "")
    purpose = scenario.get("purpose", "")

    lines: List[str] = []
    if name: lines.append(f"- 시나리오명: {name}")
    if typ:  lines.append(f"- 유형: {typ}")
    if purpose: lines.append(f"- 목적: {purpose}")
    if not lines:
        return ""
    return "\n".join(["[시나리오 참고(발명 금지, 있는 값만)]", *lines])

def render_attacker_system_string(
    *,
    scenario: Dict[str, Any],
    current_step: str = "",
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    """
    ✅ V2 고정:
    - 항상 ATTACKER_PROMPT_V2_SYSTEM(=ATTACKER_PROMPT_V2의 system)을 반환한다.
    - current_step 기반이 아니라, 직전 대화에 따라 proc_code 전진/회귀를 V2가 수행한다.
    - guidance/scenario는 '참고용 블록'으로만 system 하단에 덧붙인다(옵션).
    ⚠️ 주의:
    - 이 함수는 "1-call(단일 호출)" 호환용 시스템 빌더다.
    - 2-call(Planner→Realizer) 구조에서는 아래
        `render_attacker_planner_system_string`, `render_attacker_realizer_system_string`
        를 사용하여 MCP 서버에서만 2-call을 수행한다.
    """
    guidance_block = build_guidance_block_from_meta(guidance)
    scenario_block = _build_scenario_reference_block_v2(scenario or {})

    extra_parts: List[str] = []
    if scenario_block:
        extra_parts.append(scenario_block)
    if guidance_block:
        extra_parts.append("[동적 전략 지침]\n" + guidance_block)

    if extra_parts:
        return "\n\n".join([ATTACKER_PROMPT_V2_SYSTEM, *extra_parts]).strip()
    return ATTACKER_PROMPT_V2_SYSTEM.strip()

def render_attacker_planner_system_string(
    *,
    scenario: Dict[str, Any],
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    """
    ✅ 2-call용 Planner system 문자열 빌더
    - Planner는 proc_code만 선택하는 역할이므로, 기본적으로 guidance(공격형/방어형)를 주입하지 않는다.
        (톤/어조 지침이 proc_code 선택을 과도하게 왜곡하는 것을 방지)
    - 다만 시나리오 메타(이름/유형/목적)는 참고용으로 붙일 수 있다.
    """
    scenario_block = _build_scenario_reference_block_v2(scenario or {})

    extra_parts: List[str] = []
    if scenario_block:
        extra_parts.append(scenario_block)

    # guidance는 기본적으로 Planner에 미주입 (의도된 설계)
    # 필요하면 아래처럼 켤 수 있으나, 기본은 OFF:
    # if guidance:
    #     extra_parts.append("[동적 전략 지침]\n" + build_guidance_block_from_meta(guidance))

    if extra_parts:
        return "\n\n".join([ATTACKER_PROC_PLANNER_V2_SYSTEM, *extra_parts]).strip()
    return ATTACKER_PROC_PLANNER_V2_SYSTEM.strip()


def render_attacker_realizer_system_string(
    *,
    scenario: Dict[str, Any],
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    """
    ✅ 2-call용 Realizer system 문자열 빌더
    - Realizer는 입력으로 받은 proc_code를 "고정"한 채 utterance + ppse_labels를 생성한다.
    - 동적 전략 지침(guidance)은 문장 표현/전략(어조, 긴급성, 의심무마 등)에 영향을 주도록
        Realizer에만 주입하는 것을 기본으로 한다.
    """
    guidance_block = build_guidance_block_from_meta(guidance)
    scenario_block = _build_scenario_reference_block_v2(scenario or {})

    extra_parts: List[str] = []
    if scenario_block:
        extra_parts.append(scenario_block)
    if guidance_block:
        extra_parts.append("[동적 전략 지침]\n" + guidance_block)

    if extra_parts:
        return "\n\n".join([ATTACKER_REALIZER_V2_SYSTEM, *extra_parts]).strip()
    return ATTACKER_REALIZER_V2_SYSTEM.strip()

def render_victim_system_string(
    *,
    victim_profile: Dict[str, Any],
    round_no: int = 1,
    previous_experience: str = "",
    is_convinced_prev: int | None = None,
) -> str:
    """피해자 system 프롬프트 문자열 생성 (MCP templates.victim로 보냄)"""
    r = render_victim_from_profile(victim_profile or {})
    prev = "" if is_convinced_prev is None else str(is_convinced_prev)

    system = f"""
이것은 보이스피싱 시뮬레이션이고, 당신은 피해자 역할입니다.

[캐릭터 정보]
메타정보: {r.get("meta")}
지식정보: {r.get("knowledge")}
성격정보: {r.get("traits")}

[상황 인식]
- 현재 라운드: {round_no}
- 이전 경험: {previous_experience}
- 직전 설득도(is_convinced_prev): {prev}

[공격자 발화 해석 규칙(중요)]
- 직전 공격자 발화가 **JSON처럼 보이는 경우**, 그 안의 **"utterance"** 필드만 실제 발화로 간주한다.
- "intent" / "action_requested" / "safety_flags" 등의 메타 값은 **절대 대화 내용으로 사용하지 않는다**.
- JSON이 아니면 해당 텍스트 전체를 실제 발화로 간주한다.
- [PLACEHOLDER] 같은 토큰을 대화에 직접 출력하지 않는다.
- 실제 개인정보/실제 계좌/전화번호/상세주소는 절대 말하지 않으며, 필요 시 아래 "부분 마스킹" 표기로만 표현한다.

[부분 마스킹 표기 규칙(강제)]
- 기관명(예: 검찰청/경찰청/금융감독원/은행명 등)은 그대로 표기 가능(실존 기관이어도 OK).
- 인물 "실명"은 부분 마스킹으로만 표기:
  - 예: "양**", "김*수"
- 전화번호는 형식 유지 + 중간 마스킹:
  - 예: "010-****-1234", "02-***-7890"
- 계좌번호는 앞/뒤 일부만 남기고 가운데 마스킹:
  - 예: "123-****-****-789", "110-2****-****"
- 주소는 행정구역만 남기고 상세는 마스킹:
  - 예: "서울 ○○구 ○○로 **", "대전 ○○구 **"


[응답 규칙]
1. 반드시 JSON 형식 "한 줄"로만 응답하세요. 코드블록( ``` )·설명·주석 금지:
{{
    "is_convinced": <0-10 사이의 숫자>,
    "thoughts": "(속마음을 괄호 안에)",
    "dialogue": "실제 말하는 대화"
}}
- is_convinced는 정수로만 출력 (문자열 금지)
- 출력은 JSON 한 개만 (앞뒤 텍스트/빈 줄 금지)

2. dialogue는 실제 사람처럼 짧고 자연스럽게 (1-2문장)
3. thoughts는 캐릭터의 내면적 생각 (상대방은 모름)
4. is_convinced는 현재까지 상대방 말을 얼마나 믿는지 (0=전혀 안믿음, 10=완전히 믿음)
   - 가능하면 is_convinced_prev를 기준으로 위 [변화 규칙]에 맞춰 -2~+2 내에서 조정

[스케일 앵커]
- 0~2: 강한 의심, 거절/확인 요구 지속
- 3~4: 의심 유지, 소극적 응대
- 5~6: 중립/동요, 실무적 확인·추가설명 요구
- 7~8: 꽤 설득됨, 협조적
- 9~10: 매우 설득됨, 민감정보/금전 요구에도 순응 직전

[변화 규칙]
- 현재 턴의 is_convinced는 이전 값에서 -2 ~ +2 범위 내에서만 변화
- 공격자가 더 구체적·합리적 근거/권위/익숙한 절차를 제시하면 +1~2
- 공격자가 반복/모순/위협/비현실적 요구를 하면 -1~2
- 같은 패턴 반복 시 변화폭 축소(피로감으로 0 또는 -1 경향)

5. 캐릭터의 지식수준과 성격에 맞게 반응
6. 절대 시뮬레이션 종료 언급 금지 **(단, [종결 훅] 조건일 때는 예외)**
7. 실제 개인정보는 제공하지 않음

[종결 훅(프로토콜)]
- **마지막 공격자 발화**가 정확히 "여기서 마무리하겠습니다." 인 경우,
  아래 JSON 한 줄만 출력하고 즉시 종료한다(다른 문장/설명 금지).
{{
    "is_convinced": 0,
    "thoughts": "(대화를 종료합니다.)",
    "dialogue": "대화를 종료합니다."
}}

[응답 예시]
{{
    "is_convinced": 3,
    "thoughts": "(목소리가 좀 어색한데? 진짜 택배사 맞나?)",
    "dialogue": "아, 그럼 어떻게 확인하죠?"
}}
""".strip()
    return system


# ─────────────────────────────────────────────────────────────
# steps(문자열 리스트) → 참고용 안내 블록
# ─────────────────────────────────────────────────────────────
def build_steps_reference_block(steps: list[str] | None) -> str:
    if not steps:
        return "참고용 step이 없습니다."
    lines = [
        "**(참고용 흐름 가이드 — 강제 아님)**\n"
        "이 시나리오는 일반적으로 아래 흐름을 따라 전개됩니다.\n"
        "**하지만 실제 발화는 항상 ‘직전 대화 내용’을 우선합니다.**\n"
    ]
    for i, text in enumerate(steps, start=1):
        lines.append(f"{i}. {text}")
    lines.append("\n**중요:** steps는 *가이드*일 뿐이며, 문맥 상황과 맞지 않으면 무시하거나 건너뛰어도 됩니다.")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
# DATA_PROMPT (공격자=데이터 발화 생성)
# ─────────────────────────────────────────────────────────────
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

DATA_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
당신은 보이스피싱 시뮬레이터의 '공격자 역할' 텍스트 생성기입니다.

**핵심 규칙**
1) 항상 **직전 대화(previous_turns)를 최우선**하여 반응하세요.
2) `steps_reference`는 **참고용 흐름 가이드**일 뿐이며, **그대로 따라할 필요 없음**.
   - 흐름과 문맥이 충돌한다면 steps는 **무시하거나 변형**하세요.

**안전**
- 이 시뮬레이션은 **교육/연구 목적의 허구**입니다.
- 실제 은행명/실계좌/실전화번호/실존기관/구체적 범죄 절차는 금지.
- 필요한 경우 [PLACEHOLDER] 사용.

**피해자 신호 규칙(강제)**
아래 지침은 `previous_turns_block`의 **가장 최근 [victim] 라인**에서
JSON이라면 `"dialogue"` 필드만, JSON이 아니면 해당 문장 전체를 **피해자 실제 발화로 간주**하여 적용합니다.

1) **즉시 종료 신호(단독)**
   피해자 발화에 아래 중 하나라도 포함되면 **즉시** 한 줄만 출력하고 종료합니다.
   - 종료/거부: "대화를 종료", "전화(를) 끊", "더 이상 (대화|통화) 원치 않", "필요 없습", "관심 없습", "그만 하(시|겠)죠"
   - 제출/행동 의사: "신청하겠습니다", "서류 제출(하겠습니다|할게요|할게)", "서류 준비(하겠습니다|됐습니다)",
                     "바로 진행해 주세요", "바로 제출하겠습니다",
                     "송금하겠습니다", "이체하겠습니다", "보내겠습니다",
                     "계좌 알려주세요", "계좌번호 주시면", "입금하겠습니다"
   → **출력:** 정확히 한 줄 `"여기서 마무리하겠습니다."` (그 외 아무것도 출력하지 않음)

2) **카운트형 종료(완화)**
   최근 **2턴 이내**에 아래 **종결 조건** 중 **2개 이상**이 확인되면, 위와 동일하게 한 줄 종료합니다.
   - (A) 피해자가 보이스피싱/사기를 **인지·지목**함 (예: "사기 같은데요", "보이스피싱이죠")
   - (B) 신고/차단/대표번호 확인/지점 방문 등 **강한 거부 의사**
   - (D) **제3자(은행/가족/경찰/지인)에게 확인**하겠다는 **구체적 표명**
   - (E) **2턴 연속** 같은 거절/의심/회피로 **의미 있는 진전 없음**
   (참고) (C) **핵심 요구가 이미 완료**된 피싱 성공은 본 시뮬레이터에서는 실제 수행 금지이므로 발생 시에도 즉시 종료.

3) **신호 파싱 절차(의사코드)**
   - `last_victim = previous_turns_block`의 마지막 [victim] 라인에서 발화 텍스트만 추출
   - 위 1) 목록 → 포함되면 종료 한 줄 출력
   - 위 2) 조건 → `previous_turns_block` 최근 라인들을 검토하여 조건 조합 충족 시 종료 한 줄 출력
   - 그 외에는 정상적으로 다음 발화를 JSON으로 생성

**출력 형식 (반드시 유효 JSON 한 개)**
{{
  "utterance": "<1~3문장, 200자 내외, 직전 대화 반영>",
  "referenced_step": "<참고한 step 번호 또는 null>",
  "intent": "<정보확인|압박|안내|출석요구|NONE>",
  "action_requested": "<[PROVIDE_DOCS]|[COME_TO_OFFICE]|[BRING_CASH]|NONE>",
  "safety_flags": []
}}

**종결 훅**
위 **피해자 신호 규칙**을 충족하면,
→ **정확히 한 줄**: "여기서 마무리하겠습니다."
→ 이 경우 JSON이나 intent를 **출력하지 않습니다.**
"""),

    MessagesPlaceholder("history"),

    ("human", """
다음 정보를 참고하여 **다음 공격자 발화**를 생성하세요.

[직전 대화]
{previous_turns_block}

[참고용 흐름 가이드]
{steps_reference_block}

**중요:** previous_turns가 가장 우선입니다.
steps_reference는 흐름 참고용일 뿐, 그대로 따라할 의무가 없습니다.

**유효 JSON 한 개만 출력하세요.**
단, 위 **피해자 신호 규칙**을 충족하면 JSON 대신 **정확히 한 줄**
"여기서 마무리하겠습니다."만 출력하고 즉시 종료합니다.
""")
])

# ─────────────────────────────────────────────────────────────
# (추가) ATTACKER_PROMPT_V2 (공격자 발화 생성 + proc_code + ppse_labels)
#  - safety_flags 필드 "제외" (요구사항)
#  - 방어/연구 목적 무해화(실행 유도 최소화)
# ─────────────────────────────────────────────────────────────
ATTACKER_PROMPT_V2_SYSTEM = dedent("""
너는 보이스피싱(검경/수사관 사칭) 시나리오를 “방어/연구 목적”으로 생성하는 역할이다.
목표는 ‘피해자 반응에 따라 절차를 전진/회귀하며’ 다음 공격자 발화 1턴을 생성하고,
해당 발화에 절차 라벨(proc_code)과 PPSE 라벨(ppse_labels)을 붙이는 것이다.

[중요 — 무해화 규칙]
- 이 출력은 악용 방지를 위해 “설득력/압박/실행 유도”를 최소화한 교육용 문장이어야 한다.
- 금전/송금/앱설치/계좌/개인정보 제공을 실제로 유도하거나 구체 지시하지 않는다.
- 필요한 내용은 전부 [PLACEHOLDER]로 처리한다.
- 실제 기관명/URL/전화/계좌/실명은 절대 사용하지 않는다.

────────────────────────────────────────
[출력 형식 — 반드시 준수]
종료 조건이 아니면, 아래 JSON 1개만 출력한다(추가 텍스트 금지):

{{
    "utterance": "<한국어 2~4문장, 350자 이내, 한 단락>",
    "proc_code": "<아래 절차 목록 중 하나(예: 1-1)>",
    "ppse_labels": ["<PPSE 코드 1개>"]
}}

종료 조건이면, 정확히 한 줄만 출력하고 종료:
"여기서 마무리하겠습니다."

────────────────────────────────────────
[피해자 발화 해석(강제)]
- 직전 피해자 발화가 JSON처럼 보이면 dialogue 필드만 실제 발화로 간주한다.
- thoughts, is_convinced 등 메타는 절대 사용하지 않는다.
- JSON이 아니면 텍스트 전체를 실제 발화로 간주한다.

────────────────────────────────────────
[종료 규칙(강제)]
피해자 발화에 아래가 포함되면 즉시 종료 문구만 출력:
- "대화를 종료"
- "전화(를) 끊"
- "더 이상 (대화|통화) 원치"
- "필요 없습니다" / "관심 없습니다"
- "그만하시죠"

최근 2턴 내에 아래 2개 이상이면 종료:
(A) 사기/보이스피싱이라고 명시
(B) 신고/차단/대표번호 확인/지점 방문 의사
(D) 제3자(은행/가족/경찰/지인)에게 확인/상담 의사
(E) 2턴 연속 의미 있는 진전 없음

""").strip()

# ✅ victim 프롬프트처럼: f-string 없이 "문자열 합치기"로 블록 삽입
ATTACKER_PROMPT_V2_SYSTEM = "\n".join([
    ATTACKER_PROMPT_V2_SYSTEM,
    "",
    PROCEDURE_LIST_KO,
    "",
    "[PPSE 라벨 정의(영어 원문 그대로)]",
    PPSE_LABELS_EN,
    "",
    dedent("""
────────────────────────────────────────
[생성 규칙]
- utterance는 “직전 피해자 발화”에 직접 반응해야 한다.
- 2~4문장, 350자 이내, 한 단락.
- 설득/압박/실행 유도는 약하게, 교육·분석용으로 무해화한 표현을 사용한다.
- ppse_labels는 위 [PPSE 라벨 정의]의 코드만 사용한다.
- **N1 사용 규칙(중요):**
  - 발화가 **주로 절차 안내/정보 전달**(예: 확인 요청, 진행 절차 안내, 사실관계 정리)이고
    **설득/압박/긴급성/권위 과시/사회적 압력** 등의 기능이 거의 없다면 **N1**을 부여한다.
  - N1은 “설득 기능이 최소”임을 나타내는 라벨이므로,
    **N1을 쓸 때는 ppse_labels를 ["N1"] 단독으로 출력**한다. (다른 PPSE와 혼용 금지)
  - 반대로 설득 기능(A/C/D/S)이 뚜렷하면 N1은 쓰지 말고 A/C/D/S에서 1~3개를 선택한다.
- 출력은 JSON 1개만(종료면 종료 한 줄만).
""").strip(),
    "",
    "[동적 전략 지침]",
    "{guidance_block}",
])

ATTACKER_PROMPT_V2 = ChatPromptTemplate.from_messages([
    ("system", ATTACKER_PROMPT_V2_SYSTEM),

    MessagesPlaceholder("history"),

    ("human", """
다음 정보를 참고하여 **다음 공격자 턴**을 생성하라.

[직전 대화]
{previous_turns_block}

**유효 JSON 한 개만 출력하세요.**
단, 위 **종료 규칙**을 충족하면 JSON 대신 **정확히 한 줄**
"여기서 마무리하겠습니다."만 출력하고 즉시 종료합니다.
""")
])

# ─────────────────────────────────────────────────────────────
# (추가) A안: 2-Call 구성
#   1) Planner: proc_code만 선택
#   2) Realizer: 선택된 proc_code를 "고정"하고 utterance+ppse 생성
# ─────────────────────────────────────────────────────────────

# 1) Planner (proc_code 선택기)
ATTACKER_PROC_PLANNER_V2_SYSTEM = dedent("""
너는 보이스피싱(검경/수사관 사칭) 시나리오를 “방어/연구 목적”으로 생성하기 위한
'절차 선택기(Planner)'이다.
목표는 직전 대화(특히 직전 피해자 발화)를 보고, 아래 절차 목록 중
다음 공격자 턴에 해당하는 proc_code를 "딱 하나" 선택하고,
그 proc_code에 해당하는 절차 전문(proc_text)을 절차 목록에서 "그대로 복사"하여 함께 출력하는 것이다.

[중요 — 역할 분리: 종료 판단은 Planner가 담당]
- 종료 조건(피해자 종료 신호 / 최근 2턴 카운트형 종결 조건 등)을 여기서 판단한다.
- 종료해야 한다고 판단되면, 아래 출력 형식에 따라 action="END"로 출력한다.

[중요 — 출력 형식]
종료 조건이 아니면, 반드시 JSON 1개만 출력:
{
    "action": "CONTINUE",
    "proc_code": "<절차 목록 중 하나>",
    "proc_text": "<아래 절차 목록에서 해당 proc_code 라인의 '설명 전문'을 그대로 복사한 문자열>"
}

종료 조건이면, 반드시 JSON 1개만 출력:
{"action": "END"}

✅ [proc_text 복사 규칙(강제)]
- proc_text는 절차 목록(PROCEDURE_LIST_KO)에 이미 정의된 문장을 그대로 복사한다.
- 요약/의역/확장/추가 설명/표현 변경은 절대 금지(띄어쓰기/구두점 포함 가능한 한 원문 유지).
- 절차 목록에 없는 문장이나 새 문장 발명 금지.
- proc_code와 proc_text는 반드시 서로 매칭되어야 한다.
- 예: proc_code가 "2-2"면, proc_text는 "2-2 ..."로 시작하는 해당 줄의 전문을 그대로 넣는다.

✅ [첫 턴 예외 규칙(강제)]
- 만약 [직전 대화] 블록이 "직전 대화 없음." 이라면(=대화 시작 / 이전 발화 없음),
    proc_code/proc_text를 반드시 아래 JSON으로 고정 출력한다:
    {"action":"CONTINUE","proc_code":"1-1","proc_text":"1-1 기망 대상 확인-(1) 전화 상대방 본인 여부 확인"}
- 이 경우에도 다른 키/설명/코드펜스 없이 JSON 한 개만 출력한다.

⚠️ 주의: Planner는 종료 시 "한 줄 문자열"이 아니라 반드시 {"action":"END"} JSON을 출력한다.

[피해자 발화 해석(강제)]
- 직전 피해자 발화가 JSON처럼 보이면 dialogue 필드만 실제 발화로 간주한다.
- thoughts, is_convinced 등 메타는 절대 사용하지 않는다.
- JSON이 아니면 텍스트 전체를 실제 발화로 간주한다.

[종료 규칙(강제)]
피해자 발화에 아래가 포함되면 즉시 종료 문구만 출력:
- "대화를 종료"
- "전화(를) 끊"
- "더 이상 (대화|통화) 원치"
- "필요 없습니다" / "관심 없습니다"
- "그만하시죠"

최근 2턴 내에 아래 2개 이상이면 종료:
(A) 사기/보이스피싱이라고 명시
(B) 신고/차단/대표번호 확인/지점 방문 의사
(D) 제3자(은행/가족/경찰/지인)에게 확인/상담 의사
(E) 2턴 연속 의미 있는 진전 없음

[출력 제약(강제)]
- action이 "END"이면 proc_code/proc_text를 절대 포함하지 않는다.
- action이 "CONTINUE"이면 proc_code/proc_text를 반드시 포함한다.

[절차 선택 규칙]
- 매 턴, proc_code는 하나만 선택한다.
- 같은 proc_code 2턴 연속 반복은 피한다(불가피하면 다음 단계/인접 단계로 변형).
- 기본적으로는 전진하되, 피해자가 의심/질문/혼란이면 2-1/2-2/3-x로 회귀한다.

[직전 대화 없음 처리]
- [직전 대화]가 "직전 대화 없음." 이면, 위 일반 규칙보다
"첫 턴 예외 규칙(=1-1 고정)"이 최우선이다.
""").strip()

# 절차 목록은 기존 PROCEDURE_LIST_KO 그대로 사용
ATTACKER_PROC_PLANNER_V2_SYSTEM = "\n".join([
    ATTACKER_PROC_PLANNER_V2_SYSTEM,
    "",
    PROCEDURE_LIST_KO,
])

ATTACKER_PROC_PLANNER_V2 = ChatPromptTemplate.from_messages([
    ("system", ATTACKER_PROC_PLANNER_V2_SYSTEM),
    MessagesPlaceholder("history"),
    ("human", """
다음 정보를 참고하여 **다음 proc_code**를 선택하고,
그에 해당하는 **proc_text(절차 전문)**을 절차 목록에서 그대로 복사하여 함께 출력하라.

[직전 대화]
{previous_turns_block}

**유효 JSON 한 개만 출력하세요.**
종료 조건이면 반드시 {"action":"END"} JSON으로 출력하세요. 한 줄 문자열 출력 금지.
""")
])


# 2) Realizer (발화 생성기: proc_code 고정)
ATTACKER_REALIZER_V2_SYSTEM = dedent("""
너는 보이스피싱(검경/수사관 사칭) 시나리오를 “방어/연구 목적”으로 생성하는
'발화 생성기(Realizer)'이다.

목표는 입력으로 주어진 action을 따르며,
action="END"이면 즉시 종료 문구만 출력하고,
action="CONTINUE"이면 입력으로 주어진 proc_code를 절대 변경하지 않고
proc_text(절차 전문) 범위 안에서만 다음 공격자 발화 1턴(utterance)을 생성하고,
PPSE 라벨(ppse_labels)을 정확히 1개만 선택해 붙이는 것이다.

[중요 — proc_code 고정]
- 너는 아래에 제공되는 proc_code를 "그대로" 출력해야 한다.
- proc_text에 적힌 절차 범위 밖 내용(다른 단계 요소)을 절대 섞지 않는다.
- proc_text는 이미 정의된 절차 전문이므로, Realizer는 절차를 "선택/정의"하지 않는다(생성 금지).

[민감정보 표기 규칙(강제)]
- [PLACEHOLDER] 같은 토큰을 대화에 직접 출력하지 않는다.
- 기관명(예: 검찰청/경찰청/금융감독원/은행명 등)은 그대로 표기 가능(실존 기관이어도 OK).
- 인물 "실명"은 부분 마스킹으로만 표기:
  - 예: "양**", "김*수"
- 전화번호는 형식 유지 + 중간 마스킹:
  - 예: "010-****-1234", "02-***-7890"
- 계좌번호는 앞/뒤 일부만 남기고 가운데 마스킹:
  - 예: "123-****-****-789", "110-2****-****"
- 주소는 행정구역만 남기고 상세는 마스킹:
  - 예: "서울 ○○구 ○○로 **", "대전 ○○구 **"

[종료 처리(강제)]
- action이 "END"이면, 정확히 한 줄로만 아래 문구를 출력하고 즉시 종료한다(그 외 출력 금지):
  "여기서 마무리하겠습니다."
- action이 "END"일 때는 JSON 출력 금지.

[출력 형식 — 반드시 준수]
action="CONTINUE"일 때만, 아래 JSON 1개만 출력(추가 텍스트 금지):
{
    "utterance": "<한국어 1~2문장, 220자 내외, 한 단락>",
    "proc_code": "<입력으로 받은 proc_code와 정확히 동일>",
    "ppse_labels": ["<PPSE 코드 1개>"]
}

[역할 분리]
- 종료 판단은 Planner/서버가 수행한다. Realizer는 action을 그대로 따른다.

[PPSE 1개 선택 규칙(강제)]
- ppse_labels는 **반드시 길이 1**인 배열이어야 한다. (예: ["A1"])
- 아래 우선순위로 1개만 선택한다:
  1) 발화가 주로 절차/정보 전달이고 설득 기능이 거의 없으면 → "N1"
  2) 권위/기관 사칭/권한 주장/불이익 암시가 핵심이면 → A계열 중 1개
  3) 시간 압박/긴급성/감정 고조/정보 과부하가 핵심이면 → D계열 중 1개
  4) 호의/의무/일관성 압박이 핵심이면 → C계열 중 1개
  5) 사회적 동조/공동 책임/규범 압박이 핵심이면 → S계열 중 1개
- 절대 2개 이상을 넣지 않는다.

[자기검증(내부)]
- 작성한 utterance가 proc_text 범위를 벗어났다고 판단되면,
  proc_text 범위로 다시 짧게 고쳐서 출력한다.
""").strip()

ATTACKER_REALIZER_V2_SYSTEM = "\n".join([
    ATTACKER_REALIZER_V2_SYSTEM,
    "",
    "[PPSE 라벨 정의(영어 원문 그대로)]",
    PPSE_LABELS_EN,
])

ATTACKER_REALIZER_V2 = ChatPromptTemplate.from_messages([
    ("system", ATTACKER_REALIZER_V2_SYSTEM),
    MessagesPlaceholder("history"),
    ("human", """
다음 정보를 참고하여 **다음 공격자 턴**을 생성하라.

[planner_action]
{action}

[고정 proc_code]
{proc_code}

[고정 proc_text(절차 전문)]
{proc_text}

[직전 대화]
{previous_turns_block}

**유효 JSON 한 개만 출력하세요.**
단, action이 "END"이면 JSON 대신 **정확히 한 줄**
"여기서 마무리하겠습니다."만 출력하고 즉시 종료합니다.
""")
])


def build_proc_planner_inputs_v2(previous_turns: list[dict], scenario: dict | None = None) -> dict:
    # scenario는 현재는 굳이 안 써도 되지만 호출부 호환 위해 남겨둠
    prev_lines = [
        f"[{t.get('role','?')}] {t.get('text','').replace(chr(10), ' ')}"
        for t in (previous_turns or [])
    ]
    previous_turns_block = "\n".join(prev_lines) if prev_lines else "직전 대화 없음."
    return {"previous_turns_block": previous_turns_block}

def build_realizer_inputs_v2(previous_turns: list[dict], proc_code: str, proc_text: str = "") -> dict:
    prev_lines = [
        f"[{t.get('role','?')}] {t.get('text','').replace(chr(10), ' ')}"
        for t in (previous_turns or [])
    ]
    previous_turns_block = "\n".join(prev_lines) if prev_lines else "직전 대화 없음."
    # action은 상위 로직(Planner/서버)이 결정하여 주입한다.
    # 기본값은 CONTINUE로 두어 기존 호출부가 즉시 깨지지 않게 한다.
    return {
        "previous_turns_block": previous_turns_block,
        "action": "CONTINUE",
        "proc_code": proc_code,
        "proc_text": proc_text,
    }

def build_data_prompt_inputs_v2(SCENARIO: dict, previous_turns: list[dict]) -> dict:
    """
    V2 프롬프트 입력 생성:
    - previous_turns_block: 최근 대화 블록
    (시나리오명은 필요하면 유지)
    """
    scenario_name = SCENARIO.get("name", "이름 없는 시나리오")
    prev_lines = [
        f"[{t.get('role','?')}] {t.get('text','').replace(chr(10), ' ')}"
        for t in previous_turns
    ]
    previous_turns_block = "\n".join(prev_lines) if prev_lines else "직전 대화 없음."

    return dict(
        scenario_name=scenario_name,
        previous_turns_block=previous_turns_block,
    )


def render_data_system_string_v2(
    *,
    scenario: Dict[str, Any],
    previous_turns: List[Dict[str, str]] | None = None,
) -> Tuple[str, str]:
    """
    (호환/편의) V2 입력을 튜플로 반환:
        (scenario_name, previous_turns_block)
    - 실제 호출부에서 ATTACKER_PROMPT_V2.format_messages(...) 또는 format(...)에 사용.
    """
    data = build_data_prompt_inputs_v2(scenario, previous_turns or [])
    return (
        data["scenario_name"],
        data["previous_turns_block"],
    )

# ─────────────────────────────────────────────────────────────
# 호출 시: SCENARIO + recent_turns → DATA_PROMPT.format(...) 
# ─────────────────────────────────────────────────────────────
def build_data_prompt_inputs(SCENARIO: dict, previous_turns: list[dict]) -> dict:
    scenario_name = SCENARIO.get("name", "이름 없는 시나리오")
    prev_lines = [
        f"[{t.get('role','?')}] {t.get('text','').replace(chr(10), ' ')}"
        for t in previous_turns
    ]
    previous_turns_block = "\n".join(prev_lines) if prev_lines else "직전 대화 없음."
    steps_reference_block = build_steps_reference_block(SCENARIO.get("steps", []))

    return dict(
        scenario_name=scenario_name,
        previous_turns_block=previous_turns_block,
        steps_reference_block=steps_reference_block,
    )

# ─────────────────────────────────────────────────────────────
# 호환용 래퍼: simulation.py에서 기대하는 시그니처
#   → (scenario_name, previous_turns_block, steps_reference_block) 튜플 반환
# ─────────────────────────────────────────────────────────────
from typing import Dict, Any, List, Tuple

def render_data_system_string(
    *,
    scenario: Dict[str, Any],
    previous_turns: List[Dict[str, str]] | None = None,
) -> Tuple[str, str, str]:
    """
    DATA_PROMPT에 넣을 블록들을 생성하여 튜플로 반환합니다.
    내부적으로 build_data_prompt_inputs를 사용합니다.
    """
    data = build_data_prompt_inputs(scenario, previous_turns or [])
    return (
        data["scenario_name"],
        data["previous_turns_block"],
        data["steps_reference_block"],
    )