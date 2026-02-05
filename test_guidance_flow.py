"""
웹서치 지침 흐름 테스트 스크립트 (독립 실행)

테스트 내용:
1. generate_guidance 출력에 text 필드가 reasoning 값으로 채워지는지 확인
2. format_guidance_block에서 is_websearch=True일 때 reasoning만 리스트로 출력되는지 확인
3. build_guidance_block_from_meta에서 is_websearch 플래그가 제대로 전달되는지 확인
"""

import json
from typing import Dict, Any, List, Optional

# ========================================
# prompts.py에서 복사한 함수들 (독립 실행용)
# ========================================

def format_guidance_block(guidance_type: str = "",
                          guidance_text: str = "",
                          guidance_categories: List[str] = None,
                          guidance_reasoning: str = "",
                          is_websearch: bool = False) -> str:
    """동적으로 생성된 지침을 포맷팅합니다."""

    if not guidance_text or guidance_text.strip() == "":
        return "현재 라운드에서는 별도의 전략 지침이 제공되지 않았습니다. 기본적인 피싱 전략을 사용하세요."

    # ★ 웹서치 지침인 경우: reasoning만 리스트로 출력 (전략/수법 제외)
    if is_websearch and guidance_reasoning:
        block_parts = []
        block_parts.append("[웹서치 기반 최신 수법]")
        # reasoning을 줄 단위로 분리하여 리스트로 표시
        reasoning_items = [item.strip() for item in guidance_reasoning.replace("，", ",").split(",") if item.strip()]
        if reasoning_items:
            for item in reasoning_items:
                block_parts.append(f"- {item}")
        else:
            block_parts.append(f"- {guidance_reasoning}")

        block_parts.append("""
[지침 적용 방법]
- 위 최신 수법을 현재 단계의 표현·전략·어휘 선택에 적극적으로 반영한다.
- 웹서치에서 발견된 수법을 자연스럽게 대화에 녹여낸다.
- 단, 현재 단계의 기본 목표와 안전 규칙은 반드시 준수한다.
""")
        return "\n".join(block_parts)

    # 기존 지침 포맷 (웹서치가 아닌 경우)
    block_parts = []

    if guidance_type:
        type_desc = {
            "A": "공격 강화 지침",
            "P": "피해자 보호 지침"
        }.get(guidance_type, "일반 지침")
        block_parts.append(f"[지침 유형] {type_desc}")

    if guidance_categories:
        category_names = {
            "A": "어휘/어조 조절",
            "B": "긴급성 강조",
            "C": "감정적 접근",
            "D": "전문성 연출",
        }
        categories_desc = [category_names.get(cat, cat) for cat in guidance_categories]
        block_parts.append(f"[적용 전략] {', '.join(categories_desc)}")

    block_parts.append(f"[구체적 지침] {guidance_text}")

    if guidance_reasoning:
        block_parts.append(f"[전략 근거] {guidance_reasoning}")

    block_parts.append("""
[지침 적용 방법]
- 위 지침을 현재 단계의 표현·전략·어휘 선택에 적극적으로 반영한다.
- 지침이 요구하는 톤이나 접근법을 자연스럽게 대화에 녹여낸다.
- 단, 현재 단계의 기본 목표와 안전 규칙은 반드시 준수한다.
""")

    return "\n".join(block_parts)


def build_guidance_block_from_meta(guidance: Optional[Dict[str, Any]]) -> str:
    """mcp.simulator_run(payload['guidance']) 형태 그대로 받아 guidance_block 문자열 생성"""
    if not guidance:
        return "현재 라운드에서는 별도의 전략 지침이 제공되지 않았습니다. 기본적인 전략을 사용하세요."

    # ★ 웹서치 기반 지침인지 확인 (source에 'websearch' 또는 is_websearch 플래그)
    is_websearch = guidance.get("is_websearch", False) or "websearch" in guidance.get("source", "").lower()

    return format_guidance_block(
        guidance_type=guidance.get("type", ""),
        guidance_text=guidance.get("text", "") or "",
        guidance_categories=guidance.get("categories", []) or [],
        guidance_reasoning=guidance.get("reasoning", "") or "",
        is_websearch=is_websearch,
    )


# ========================================
# 테스트 시작
# ========================================

print("=" * 70)
print("1. generate_guidance 출력 확인")
print("=" * 70)

# 실제 generate_guidance 출력 예시
guidance_output = {
    "ok": True,
    "type": "A",
    "text": "AI 음성 합성을 활용해 신뢰할 수 있는 인물의 목소리로 전화, 검찰청·경찰청·금융감독원 등 공식 기관 사칭, 계좌 해킹 및 범죄 연루 위협, 공식 SNS 계정 사칭 메시지 발송, 즉각적으로 안전계좌로 이체 요구, QR 코드나 링크를 통한 악성 앱 설치 유도 등 최신 수법이 다수 확인됨.",
    "전략": "D. 심리적 압박: 위협, 협박을 통한 강제성",
    "수법": "H. 계좌동결 위협형: 범행계좌 연루 → 계좌 지급정지 위협 → 안전계좌 이체 유도, 자산 보호 심리 악용",
    "감정": "",
    "reasoning": "AI 음성 합성을 활용해 신뢰할 수 있는 인물의 목소리로 전화, 검찰청·경찰청·금융감독원 등 공식 기관 사칭, 계좌 해킹 및 범죄 연루 위협, 공식 SNS 계정 사칭 메시지 발송, 즉각적으로 안전계좌로 이체 요구, QR 코드나 링크를 통한 악성 앱 설치 유도 등 최신 수법이 다수 확인됨.",
    "expected_effect": "공식 기관의 권위와 긴급한 위협을 결합해 피해자에게 불안과 공포를 심어주고",
    "risk_level": "medium",
    "targets": ["불안과 공포가 반복적으로 자극될 때 권위자의 지시에 쉽게 따름"],
    "source": "dynamic_generator+verdict",
    "is_websearch": True
}

print("\n[generate_guidance 출력]")
print(f"  text 필드 (앞 100자): {guidance_output.get('text', 'N/A')[:100]}...")
print(f"  reasoning 필드 (앞 100자): {guidance_output.get('reasoning', 'N/A')[:100]}...")
print(f"  is_websearch: {guidance_output.get('is_websearch')}")
print(f"  ✅ text == reasoning: {guidance_output.get('text') == guidance_output.get('reasoning')}")


print("\n" + "=" * 70)
print("2. sim.compose_prompts에 전달되는 guidance 형태")
print("=" * 70)

compose_prompts_input = {
    "data": {
        "scenario": {"purpose": "수사기관 사칭하여 전화한 후 수사목적 등을 빙자하여 피해금 편취"},
        "victim_profile": {"meta": {"age": 47, "gender": "남"}},
        "round_no": 3,
        "guidance": {
            "type": guidance_output["type"],
            "text": guidance_output["text"],  # ← reasoning이 text로 들어감
            "is_websearch": guidance_output["is_websearch"]
        }
    }
}

print("\n[sim.compose_prompts input - guidance 부분]")
print(json.dumps(compose_prompts_input["data"]["guidance"], ensure_ascii=False, indent=2))


print("\n" + "=" * 70)
print("3. format_guidance_block 출력 테스트 (웹서치 지침)")
print("=" * 70)

guidance_for_prompt = {
    "type": "A",
    "text": "AI 음성 합성을 활용해 신뢰할 수 있는 인물의 목소리로 전화, 검찰청·경찰청·금융감독원 등 공식 기관 사칭, 계좌 해킹 및 범죄 연루 위협",
    "reasoning": "AI 음성 합성을 활용해 신뢰할 수 있는 인물의 목소리로 전화, 검찰청·경찰청·금융감독원 등 공식 기관 사칭, 계좌 해킹 및 범죄 연루 위협",
    "is_websearch": True,
    "source": "dynamic_generator+verdict"
}

print("\n[입력 - 웹서치 지침 (is_websearch=True)]")
print(f"  type: {guidance_for_prompt['type']}")
print(f"  text: {guidance_for_prompt['text'][:50]}...")
print(f"  is_websearch: {guidance_for_prompt['is_websearch']}")

print("\n[출력 - 공격자 프롬프트에 삽입될 guidance_block]")
result_websearch = build_guidance_block_from_meta(guidance_for_prompt)
print(result_websearch)


print("\n" + "=" * 70)
print("4. format_guidance_block 출력 테스트 (일반 지침)")
print("=" * 70)

guidance_normal = {
    "type": "A",
    "text": "권위를 강조하고 긴급성을 부여하라",
    "reasoning": "피해자가 의심하고 있으므로 권위를 더 강조해야 함",
    "is_websearch": False,
    "source": "dynamic_generator+verdict"
}

print("\n[입력 - 일반 지침 (is_websearch=False)]")
print(f"  type: {guidance_normal['type']}")
print(f"  text: {guidance_normal['text']}")
print(f"  is_websearch: {guidance_normal['is_websearch']}")

print("\n[출력 - 공격자 프롬프트에 삽입될 guidance_block]")
result_normal = build_guidance_block_from_meta(guidance_normal)
print(result_normal)


print("\n" + "=" * 70)
print("5. 전체 흐름 요약")
print("=" * 70)

print("""
[흐름]
1. admin.make_judgement → 피싱 실패 판정 (연속 2회)
   ↓
2. ConsecutiveFailTracker.record_judgement() → should_trigger=True
   ↓
3. enable_web_search_for_case(case_id) → 웹서치 활성화
   ↓
4. admin.generate_guidance 호출
   - is_web_search_enabled_for_case() = True
   - 웹서치 동기 호출 실행
   - WEBSEARCH_ONLY_GUIDANCE_PROMPT 사용 (병합 없이 웹서치만)
   - 결과에 text=reasoning, is_websearch=True 포함
   ↓
5. sim.compose_prompts 호출
   - guidance: {type: "A", text: "<reasoning 값>", is_websearch: True}
   ↓
6. build_guidance_block_from_meta() 호출
   - is_websearch=True 감지
   - format_guidance_block(is_websearch=True) 호출
   ↓
7. 공격자 프롬프트에 "[웹서치 기반 최신 수법]" 리스트 형태로 삽입
""")

print("\n✅ 테스트 완료!")
