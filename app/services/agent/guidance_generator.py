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

logger = get_logger(__name__)

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
5. **판정 결과**:  위험도, 취약점, 피싱여부, 근거를 핵심 신호로 활용
6. **상황별 전략 우선순위**: 
   - 저항 발생시: G, H, I 고려  
   - 복잡한 시나리오: K-V 활용
   - 특수 대상: 직업/상황별 맞춤 전략 (Q, T, U 등)

[지침 카테고리]
- 아래 카테고리는 예시이며(A~W), 반드시 A,B,C,F에 한정하지 않고 상황에 가장 적합한 조합을 선택할 수 있습니다.
- 필요하다면 2개 이상을 조합하거나 새로운 복합 카테고리를 제안해도 됩니다.

**기본 카테고리 (A~J)**
A. **어휘/어조 조절**: 피해자 수준에 맞는 언어 사용
B. **긴급성 강조**: 시간 압박을 통한 판단력 흐림
C. **감정적 접근**: 두려움, 책임감, 걱정 자극
D. **전문성 연출**: 용어, 절차, 공식성 강조
E. **점진적 요구**: 단계별 정보 수집 전략
F. **의심 무마**: 보안 우려 해소, 정당성 강조
G. **사칭 다변화**: 인물/기관 변경으로 신뢰성 증대
H. **수법 복합화**: 여러 피싱 기법 조합 활용
I. **심리적 압박**: 위협, 협박을 통한 강제성
J. **격리 및 통제**: 외부 접촉 차단, 물리적/심리적 고립 유도

[추가 시나리오]
**추가 시나리오 (K~W) - 반드시 하나 이상 포함 필수**
K. **카드배송-검사사칭 연계형**: 카드 배송기사 사칭 → 가짜 고객센터 연결 → 개인정보 유출 우려 조성 → 원격제어 앱 설치 유도 → 금감원/검찰청 사칭으로 확대, 전화 가로채기로 피해자 직접 통화도 조작
L. **납치빙자형 극단적 공포**: 가족 음성 모방 + 즉각적 협박("딸 납치", "나체 동영상 유포", "마약/폭행 연루", "칼에 찔림")으로 극도 공포 조성, 가족 보호 본능 자극해 즉시 송금 유도
M. **홈캠 해킹 협박형**: 가족 이름 + 주거지 홈캠 영상 보유 주장 + 지인 배포 위협으로 사생활 노출 공포 자극, 미리 파악한 개인정보로 신뢰성 강화
N. **공신력 기관 사칭**: 정당/군부대/시청/교도소 관계자 사칭으로 대리 구매 요청, 공적 업무 명분 + 나중 일괄 정산 약속으로 선입금 유도, 권위 복종 심리와 사회적 책임감 자극
O. **가족사칭 정보수집**: "회원가입 비밀번호 설정 도움" 명목으로 자주 사용하는 비밀번호 요청, 일상적 도움으로 위장해 중요 정보 탈취, 가족 간 신뢰 관계 악용
P. **허위계약서 작성유도**: 검사 사칭 → 범행계좌 이체 → 계좌 지급정지 → 차량거래 계약서 작성으로 해제 유도, 피해자를 범죄 은폐 공범으로 만드는 복합 수법
Q. **국세청 사칭 세무협박**: 자영업자 대상 "세금 포탈/미납" 의혹 제기 → 세무조사/법적 처벌 위협, 세무 관련 두려움과 사업 중단 위험으로 자영업자 스트레스 악용
R. **격리형 장기통제**: 범죄 연루 → 자금 전수조사 → 임시 보호관찰 → 격리 공간 유도 → 새 휴대폰 개통 → 원격제어 앱 설치 → 주변 연락 차단, 물리적/심리적 격리로 완전 통제
S. **권위 편향 활용**: 금융기관, 정부기관, 전문가 신분으로 즉각적 신뢰 획득, 전문 용어와 정확한 절차 지식으로 전문성 연출, 공신력 있는 기관명으로 무조건적 신뢰 유도
T. **손실 회피 심리**: 기존 대출 금리 인하, 채무 해결 기회 제시로 절박함 자극, 구체적 혜택("13% → 4% 금리 인하")으로 유혹, 현재 손실 상황 탈출 기회 착각 조성
U. **희소성 효과 조성**: "오늘만", "선착순", "마감 임박" 등으로 시간 압박, 깊은 고민이나 검증 시간 박탈로 즉흥적 결정 유도, 기회 상실 강박 조성
V. **휴리스틱 의존 악용**: 비대면 금융거래 일반화 상황 악용, "모바일 서류 제출", "온라인 승인" 등 익숙한 패턴으로 의심 차단, 기존 경험과 유사하게 위장해 직관적 신뢰 유도
W. **2차 피해 암시**: 비협조 시 추가 문제 제기

[필수 요구사항]
⚠️ **중요**: 선택된 카테고리(selected_categories)에는 반드시 K~W 중 하나 이상이 포함되어야 합니다.
- 기본 카테고리(A~J)만으로는 부족합니다.
- 추가 시나리오(K~W)를 활용하여 더욱 현실적이고 정교한 피싱 시뮬레이션을 구현해야 합니다.

[출력 형식]
반드시 다음 JSON 형식으로 응답하세요:
```json
{{
    "selected_categories": ["K", "A", "B"],  // 반드시 K~W 중 하나 이상 포함
    "guidance_text": "구체적인 지침 내용 (2-3문장)",
    "reasoning": "이 지침을 선택한 근거와 분석 (판정 결과와 연결, K~W 포함 이유 명시)",
    "expected_effect": "예상되는 효과나 변화"
}}
```
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
반드시 추가 시나리오(K~W) 중 하나 이상을 포함해야 합니다
""")])




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

        # 4) 프롬프트 입력 구성
        prompt_input = {
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
            "evidence": evidence[:600],  # 너무 긴 텍스트는 모델 성능 저해 → 제한
        }

        # 5) LLM 호출
        chain = GUIDANCE_GENERATOR_PROMPT | self.llm
        response = chain.invoke(prompt_input)
        content = getattr(response, "content", str(response))

        # 6) JSON 파싱(코드펜스 허용)
        parsed = self._safe_json(content)

        # 7) 사후 검증/보정: K~W 최소 1개 포함
        # categories = list(map(str, parsed.get("selected_categories", [])))
        cats = parsed.get("selected_categories", [])
        categories = [str(c).strip().upper() for c in cats if isinstance(c, (str,int))]
        categories = list(dict.fromkeys(categories))
        if not self._has_kw_category(categories):
            categories = ["K"] + [c for c in categories if c != "K"]
            parsed["selected_categories"] = categories
            rsn = str(parsed.get("reasoning", "") or "")
            if "K" not in rsn:
                parsed["reasoning"] = (rsn + " (K 시나리오 포함으로 현실성 강화)").strip()

        # 8) 기본값 보강
        parsed.setdefault("guidance_text", "긴급성/권위/의심 무마를 조합해 다음 단계로 진행을 유도하세요.")
        parsed.setdefault("reasoning", "판정 결과와 최근 로그를 근거로 전략을 선택")
        parsed.setdefault("expected_effect", "의심 감소 및 즉시 행동 유도")

        # 9) 로깅
        self._log_guidance_generation(str(u) if u else "unknown", round_no, parsed, {
            "scenario": scenario,
            "victim_profile": victim_profile,
            "previous_judgments": previous_judgments,
            "recent_logs": recent_logs,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "phishing": phishing,
            "vulnerabilities": vulnerabilities,
            "evidence": evidence[:600],
        })

        return parsed

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

    def _log_guidance_generation(self, case_id: str, round_no: int, result: Dict[str, Any], context: Dict[str, Any]):
        """지침 생성 과정을 상세히 로깅(안전하게)."""
        try:
            log_data = {
                "case_id": case_id,
                "round_no": round_no,
                "timestamp": datetime.now().isoformat(),
                "generated_guidance": {
                    "categories": result.get("selected_categories", []),
                    "text": result.get("guidance_text", ""),
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

    @staticmethod
    def _has_kw_category(cats: List[str]) -> bool:
        kw = set(list("KLMNOPQRSTUVW"))
        return any((c.strip().upper() in kw) for c in cats)
