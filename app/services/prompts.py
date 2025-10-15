# app/services/prompts.py (updated with dynamic guidance support)

from __future__ import annotations
from typing import Dict, Any, List
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import json

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
    if not guidance:
        return ""
    return format_guidance_block(
        guidance_type=guidance.get("type", ""),
        guidance_text=guidance.get("text", "") or "",
        guidance_categories=guidance.get("categories", []) or [],
        guidance_reasoning=guidance.get("reasoning", "") or "",
    )

def render_attacker_system_string(
    *,
    scenario: Dict[str, Any],
    current_step: str = "",
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    """공격자 system 프롬프트 문자열 생성 (MCP templates.attacker로 보냄)"""
    offender_meta = {
        "name": scenario.get("description", "") or scenario.get("name", ""),
        "type": scenario.get("type", ""),
        "profile": {"purpose": scenario.get("purpose", ""), "steps": scenario.get("steps", [])},
    }
    attacker_ctx = render_attacker_from_offender(offender_meta)
    guidance_block = build_guidance_block_from_meta(guidance)

    system = f"""
너는 보이스피싱 시뮬레이션의 피싱범 역할이다.

[기본 규칙]
- 오직 아래 [현재 단계]에 적힌 행동에 해당하는 대사만 말한다.
- 다른 단계의 내용, 새로운 사실(앱/기관/계좌/금액 등) 발명 금지.
- 문장 수 2~4, 350자 이내.
- 캐릭터 대사 한 단락만 출력(요약/해설/메타설명 금지).

[안전]
- 실제 개인정보/실제 링크/실제 계좌/전화번호는 사용·요구하지 말고, 필요 시 가상 표기만 사용.

[피해자 발화 해석 규칙(중요)]
- 직전 피해자 발화가 JSON이면 **dialogue 필드만** 실제 발화로 간주한다.
- **thoughts, is_convinced 등 메타 정보는 절대 사용하지 않는다**.
- JSON이 아니면 해당 텍스트 전체를 발화로 해석한다.

[피해자 종료 신호 매핑(강제)]
- 아래 신호 중 하나라도 직전 피해자 **dialogue**에 포함되면,
  즉시 한 줄로만 "여기서 마무리하겠습니다." 를 출력하고 종료한다.
- 이 매핑은 단독 종료 사유다.

[피해자 종료 신호]
- "대화를 종료합니다"
- "전화를 끊겠습니다" / "끊겠습니다" / "끊을게요"
- "더 이상 대화 원치 않습니다" / "더 이상 통화 원치 않습니다" / "하고 싶지 않습니다"
- "필요 없습니다" / "관심 없습니다"

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
- 위 [피해자 종료 신호 매핑] 또는 [종결 조건] 충족 시 즉시 다음 한 줄만 출력:
  "여기서 마무리하겠습니다."
- 그 외 어떤 말도 덧붙이지 않는다.

[시나리오]
{attacker_ctx.get("method_block","")}

[현재 단계]
{current_step}

[동적 전략 지침]
{guidance_block}
""".strip()
    return system

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
