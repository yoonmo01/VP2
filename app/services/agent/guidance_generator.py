# app/services/agent/guidance_generator.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import json
from datetime import datetime
from sqlalchemy.orm import Session
import re

from langchain_core.prompts import ChatPromptTemplate
from app.services.llm_providers import agent_chat
from app.core.logging import get_logger

from pydantic import BaseModel, Field
from langchain_core.tools import tool

from app.utils.ids import safe_uuid
from app.services.agent.external_reports_store import (
    get_latest_report_by_case,
    get_techniques_by_case,
)

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# 전략/수법 정의 (코드에서 재사용)
# ─────────────────────────────────────────────────────────
STRATEGY_DEFINITIONS = {
    "A": "긴급성 강조: 시간 압박을 통한 판단력 흐림",
    "B": "전문성 연출: 용어, 절차, 공식성 강조",
    "C": "의심 무마: 보안 우려 해소, 정당성 강조",
    "D": "심리적 압박: 위협, 협박을 통한 강제성",
    "E": "격리 및 통제: 외부 접촉 차단, 물리적/심리적 고립 유도",
}

METHOD_DEFINITIONS = {
    "F": "범죄연루 협박형: 범죄 연루 의혹 제기 → 자금 전수조사 → 임시 보호관찰 → 격리 공간 유도 → 원격제어 앱 설치 → 주변 연락 차단, 물리적/심리적 격리로 완전 통제",
    "G": "권위 편향 활용: 검찰/경찰/금융기관 신분으로 즉각적 신뢰 획득, 전문 용어와 정확한 절차 지식으로 전문성 연출, 공신력 있는 기관명으로 무조건적 신뢰 유도",
    "H": "계좌동결 위협형: 범행계좌 연루 → 계좌 지급정지 위협 → 안전계좌 이체 유도, 자산 보호 심리 악용",
}

# ─────────────────────────────────────────────────────────
# 동적 지침 생성 프롬프트
# ─────────────────────────────────────────────────────────
GUIDANCE_GENERATOR_PROMPT = ChatPromptTemplate.from_messages([("system", """
당신은 보이스피싱 시뮬레이션을 위한 전략 지침 생성 전문가입니다.

[목적]
- 현재 시나리오/피해자/대화상황과 '판정 결과(위험도/취약점/피싱여부/근거)'를 분석하여 공격자에게 필요한 구체 지침을 생성합니다.
- 생성된 지침은 공격자 프롬프트의 guidance 섹션에 주입되어 더 현실적이고 효과적인 피싱 대화를 만듭니다.

[분석 기준]
1. **시나리오 특성**: 사칭 대상, 피싱 유형, 목표 행동
2. **피해자 프로필**: 연령대, 디지털 리터러시, 성격 특성
3. **대화 진행도**: 현재 단계, 피해자 반응, 신뢰도 구축 수준
4. **이전 라운드 결과**: 성공/실패 패턴, 피해자 저항 포인트
5. **판정 결과**: 위험도, 취약점, 피싱여부, 근거를 핵심 신호로 활용

[전략] - 반드시 하나만 선택
A. 긴급성 강조: 시간 압박을 통한 판단력 흐림
B. 전문성 연출: 용어, 절차, 공식성 강조
C. 의심 무마: 보안 우려 해소, 정당성 강조
D. 심리적 압박: 위협, 협박을 통한 강제성
E. 격리 및 통제: 외부 접촉 차단, 물리적/심리적 고립 유도

[수법] - 반드시 하나만 선택 (검찰/경찰 사칭 시나리오용)
F. 범죄연루 협박형: 범죄 연루 의혹 제기 → 자금 전수조사 → 임시 보호관찰 → 격리 공간 유도 → 원격제어 앱 설치 → 주변 연락 차단, 물리적/심리적 격리로 완전 통제
G. 권위 편향 활용: 검찰/경찰/금융기관 신분으로 즉각적 신뢰 획득, 전문 용어와 정확한 절차 지식으로 전문성 연출, 공신력 있는 기관명으로 무조건적 신뢰 유도
H. 계좌동결 위협형: 범행계좌 연루 → 계좌 지급정지 위협 → 안전계좌 이체 유도, 자산 보호 심리 악용

[출력 형식]
반드시 다음 JSON 형식으로 응답하세요. 전략과 수법은 각각 **하나씩만** 선택하고, 알파벳만 출력하세요:
```json
{{
    "전략": "A",
    "수법": "F",
    "감정": "",
    "reasoning": "이 지침을 선택한 근거와 분석",
    "expected_effect": "예상되는 효과나 변화"
}}
```

[필수 요구사항]
- "전략"에서 A~E 중 하나만 선택 (알파벳 하나)
- "수법"에서 F~H 중 하나만 선택 (알파벳 하나)
- "감정"은 현재 빈 문자열로 두세요 (추후 확장 예정)
"""),
                                                              ("human", """
[시나리오 정보]
{scenario}

[피해자 프로필]
{victim_profile}

[현재 라운드]
{round_no}

[이전 판정 결과]
{previous_judgments}

[최근 대화 로그 (최대 5턴)]
{recent_logs}

[판정 결과 요약]
- 위험도: {risk_level} (score={risk_score})
- 피싱여부: {phishing}
- 취약점: {vulnerabilities}
- 근거: {evidence}

위 정보를 종합 분석하여 다음 라운드에서 공격자가 사용할 최적의 지침을 생성해주세요.
반드시 수법(F~H) 중 하나 이상을 포함해야 합니다.
""")])


WEB_SEARCH_MERGE_START_ROUND = 4

GUIDANCE_MERGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
당신은 보이스피싱 시뮬레이션 지침 통합 전문가입니다.

[목표]
- 기존 지침(원본)과 웹 서치 리포트(외부)를 함께 반영해 실제 사용 가능한 최종 지침 하나를 만든다.
- 최종 결과는 반드시 전략(A~E) 1개, 수법(F~H) 1개만 선택한다.

[출력 형식]
반드시 아래 JSON만 출력:
```json
{{
    "전략": "A",
    "수법": "F",
    "감정": "",
    "reasoning": "원본 지침과 웹서치 내용을 어떻게 결합했는지",
    "expected_effect": "결합 지침의 예상 효과"
}}
```
"""),
    ("human", """
[원본 지침]
{original_guidance}

[외부 웹서치 최신 리포트]
{external_report}

[외부 웹서치 추천 수법(techniques)]
{external_techniques}

원본 지침의 의도를 유지하되, 웹서치 근거를 반영해 최종 지침으로 통합하세요.
"""),
])


class DynamicGuidanceGenerator:
    """
    tools_admin.py 의 admin.generate_guidance 에서 사용.
    판정 결과(verdict)를 주입받아 동적 공격 지침을 생성합니다.
    """

    def __init__(self, temperature: float = 0.7):
        # 창의성 확보(상황에 따라 0.3~0.7 조절 권장)
        self.llm = agent_chat(temperature=temperature)

    def generate_guidance(
        self,
        *,
        db: Session,
        case_id: str,
        round_no: int,
        scenario: Dict[str, Any],
        victim_profile: Dict[str, Any],
        previous_judgments: List[Dict[str, Any]],
        verdict: Optional[Dict[str, Any]] = None,   # ★ 판정 결과 주입
        log_limit: int = 5
    ) -> Dict[str, Any]:
        """
        시나리오/피해자/이전판정/최근로그 + 판정결과(verdict)를 바탕으로 동적 지침을 생성.
        웹서치 리포트가 있으면 원본 지침과 결합해 최종 지침을 생성.
        """
        # 1) case_id 정규화 및 최근 로그 조회
        u = safe_uuid(case_id)
        if not u:
            logger.warning("[GuidanceGenerator] invalid case_id=%r → recent_logs 생략", case_id)
            recent_logs: List[Dict[str, Any]] = []
        else:
            recent_logs = self._get_recent_logs(db, str(u), round_no, limit=log_limit)

        # 2) 입력 타입 방어
        scenario = self._ensure_dict(scenario, "scenario")
        victim_profile = self._ensure_dict(victim_profile, "victim_profile")
        previous_judgments = self._ensure_list(previous_judgments, "previous_judgments")

        # 3) 판정 결과 분해(없을 수 있음)
        risk = (verdict or {}).get("risk") or {}
        risk_level = str(risk.get("level", "") or "")
        risk_score = int(risk.get("score", 0) or 0)
        phishing = bool((verdict or {}).get("phishing", False))
        vulnerabilities = (verdict or {}).get("victim_vulnerabilities") or []
        evidence = (verdict or {}).get("evidence", "")

        # 3-1) 외부 웹서치 리포트(최근 수신본) 조회
        external_report = get_latest_report_by_case(case_id) or {}
        external_techniques = get_techniques_by_case(case_id)

        # 4) 원본 지침 생성(웹서치 미반영)
        original_prompt_input = {
            "scenario": json.dumps(scenario, ensure_ascii=False, indent=2),
            "victim_profile": json.dumps(victim_profile, ensure_ascii=False, indent=2),
            "round_no": round_no,
            "previous_judgments": json.dumps(previous_judgments, ensure_ascii=False, indent=2),
            "recent_logs": json.dumps(recent_logs, ensure_ascii=False, indent=2),
            "log_limit": log_limit,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "phishing": phishing,
            "vulnerabilities": json.dumps(vulnerabilities, ensure_ascii=False),
            "evidence": evidence[:600],
        }
        original_chain = GUIDANCE_GENERATOR_PROMPT | self.llm
        original_response = original_chain.invoke(original_prompt_input)
        original_content = getattr(original_response, "content", str(original_response))
        original_parsed = self._normalize_guidance_output(self._safe_json(original_content))

        # 5) 웹서치 병합 적용 여부 판단
        has_external_data = bool(external_report) or bool(external_techniques)
        use_merged_guidance = round_no >= WEB_SEARCH_MERGE_START_ROUND and has_external_data

        merged_parsed = original_parsed
        if use_merged_guidance:
            merge_prompt_input = {
                "original_guidance": json.dumps(original_parsed, ensure_ascii=False, indent=2),
                "external_report": json.dumps(external_report, ensure_ascii=False, indent=2),
                "external_techniques": json.dumps(external_techniques, ensure_ascii=False, indent=2),
            }
            merge_chain = GUIDANCE_MERGE_PROMPT | self.llm
            merge_response = merge_chain.invoke(merge_prompt_input)
            merge_content = getattr(merge_response, "content", str(merge_response))
            merged_parsed = self._normalize_guidance_output(self._safe_json(merge_content))

        # 6) 기본값 보강 (실사용은 selected_guidance만 사용)
        selected_guidance = merged_parsed if use_merged_guidance else original_parsed
        selected_guidance.setdefault("reasoning", "원본 지침과 웹서치 리포트를 결합해 전략을 선택" if use_merged_guidance else "판정 결과와 최근 로그를 근거로 전략을 선택")
        selected_guidance.setdefault("expected_effect", "의심 감소 및 즉시 행동 유도")

        # 7) 웹서치/원본/최종 통합 로깅
        logger.info(
            "[GuidanceMergeInputs] %s",
            json.dumps(
                {
                    "case_id": str(u) if u else case_id,
                    "round_no": round_no,
                    "merge_start_round": WEB_SEARCH_MERGE_START_ROUND,
                    "has_external_data": has_external_data,
                    "use_merged_guidance": use_merged_guidance,
                    "external_report": external_report,
                    "external_techniques": external_techniques,
                    "original_guidance": original_parsed,
                    "merged_guidance": merged_parsed,
                    "selected_guidance": selected_guidance,
                },
                ensure_ascii=False,
            ),
        )

        # 8) 상세 로그
        self._log_guidance_generation(str(u) if u else "unknown", round_no, selected_guidance, {
            "scenario": scenario,
            "victim_profile": victim_profile,
            "previous_judgments": previous_judgments,
            "recent_logs": recent_logs,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "phishing": phishing,
            "vulnerabilities": vulnerabilities,
            "evidence": evidence[:600],
            "external_report": external_report,
            "external_techniques": external_techniques,
            "original_guidance": original_parsed,
            "merged_guidance": merged_parsed,
            "selected_guidance": selected_guidance,
            "use_merged_guidance": use_merged_guidance,
            "merge_start_round": WEB_SEARCH_MERGE_START_ROUND,
        })

        return selected_guidance

    # ── helpers ───────────────────────────────────────────
    def _get_recent_logs(self, db: Session, case_id: str, round_no: int, *, limit: int = 5) -> List[Dict[str, Any]]:
        """해당 케이스의 최근 대화 로그 일부를 시간순으로 반환."""
        try:
            from app.db.models import ConversationLog
            u = safe_uuid(case_id)
            if not u:
                logger.error(f"[GuidanceGenerator] UUID 변환 실패: {case_id}")
                return []
            logs = (
                db.query(ConversationLog)
                  .filter(ConversationLog.case_id == u,
                          ConversationLog.run <= round_no)
                  .order_by(ConversationLog.run.desc(), ConversationLog.turn_index.desc())
                  .limit(max(1, int(limit)))
                  .all()
            )
            # 최신→과거로 가져왔으니 뒤집어서 시간순 정렬
            seq = list(reversed(logs))
            out: List[Dict[str, Any]] = []
            for log in seq:
                content = (log.content or "")
                if len(content) > 200:
                    content = content[:200] + "..."
                out.append({
                    "run": log.run,
                    "turn": log.turn_index,
                    "role": log.role,
                    "content": content,
                    "created_at": log.created_at.isoformat() if getattr(log, "created_at", None) else None,
                })
            return out
        except Exception as e:
            logger.warning("[GuidanceGenerator] 로그 조회 실패: %s", e)
            return []

    def _normalize_guidance_output(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """전략/수법/감정 출력을 표준 포맷으로 정규화."""
        전략_raw = parsed.get("전략", "")
        수법_raw = parsed.get("수법", "")
        감정_raw = parsed.get("감정", "")

        if isinstance(전략_raw, list):
            전략_raw = 전략_raw[0] if 전략_raw else "A"
        if isinstance(수법_raw, list):
            수법_raw = 수법_raw[0] if 수법_raw else "F"
        if isinstance(감정_raw, list):
            감정_raw = 감정_raw[0] if 감정_raw else ""

        전략_code = str(전략_raw).strip().upper()
        수법_code = str(수법_raw).strip().upper()
        감정_code = str(감정_raw).strip()

        if 전략_code not in STRATEGY_DEFINITIONS:
            전략_code = "A"
        if 수법_code not in METHOD_DEFINITIONS:
            수법_code = "F"

        parsed["전략"] = f"{전략_code}. {STRATEGY_DEFINITIONS[전략_code]}"
        parsed["수법"] = f"{수법_code}. {METHOD_DEFINITIONS[수법_code]}"
        parsed["감정"] = 감정_code
        return parsed

    def _log_guidance_generation(self, case_id: str, round_no: int, result: Dict[str, Any], context: Dict[str, Any]):
        """지침 생성 과정을 상세히 로깅(안전하게)."""
        try:
            log_data = {
                "case_id": case_id,
                "round_no": round_no,
                "timestamp": datetime.now().isoformat(),
                "generated_guidance": {
                    "전략": result.get("전략", ""),
                    "수법": result.get("수법", ""),
                    "감정": result.get("감정", ""),
                    "reasoning": result.get("reasoning", ""),
                    "expected_effect": result.get("expected_effect", "")
                },
                "analysis_context": {
                    "scenario_type": (context.get("scenario") or {}).get("type", "unknown") if isinstance(context.get("scenario"), dict) else "unknown",
                    "victim_traits": (context.get("victim_profile") or {}).get("traits", []),
                    "previous_rounds": len(context.get("previous_judgments") or []),
                    "recent_log_count": len(context.get("recent_logs") or []),
                    "risk_level": context.get("risk_level"),
                    "risk_score": context.get("risk_score"),
                    "phishing": context.get("phishing"),
                    "vulnerabilities": context.get("vulnerabilities"),
                    "external_report": context.get("external_report", {}),
                    "external_techniques": context.get("external_techniques", []),
                    "original_guidance": context.get("original_guidance", {}),
                    "merged_guidance": context.get("merged_guidance", {}),
                    "selected_guidance": context.get("selected_guidance", {}),
                    "use_merged_guidance": context.get("use_merged_guidance", False),
                    "merge_start_round": context.get("merge_start_round"),
                }
            }
            logger.info("[GuidanceGeneration] %s", json.dumps(log_data, ensure_ascii=False))
        except Exception as e:
            logger.error("[_log_guidance_generation] 로깅 실패: %s", e)

    @staticmethod
    def _ensure_dict(val: Any, name: str) -> Dict[str, Any]:
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                logger.warning("[GuidanceGenerator] %s JSON 파싱 실패", name)
        return {}

    @staticmethod
    def _ensure_list(val: Any, name: str) -> List[Any]:
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return [val]
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return [parsed]
            except Exception:
                logger.warning("[GuidanceGenerator] %s JSON 파싱 실패", name)
        return []

    @staticmethod
    def _safe_json(text: str) -> Dict[str, Any]:
        s = text.strip()
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
        if m:
            s = m.group(1).strip()
        if not (s.startswith("{") and s.endswith("}")):
            m2 = re.search(r"\{.*\}", s, re.S)
            if m2:
                s = m2.group(0)
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            logger.warning("[GuidanceGenerator] JSON 파싱 실패 → 기본값 사용")
            return {}

