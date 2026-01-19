# app/services/enhanced_scenario_builder.py (신규)

from __future__ import annotations
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.agent.guidance_generator import DynamicGuidanceGenerator
from app.core.logging import get_logger

logger = get_logger(__name__)


class ScenarioEnhancer:
    """시나리오 개선을 위한 지침 생성 시스템"""

    def __init__(self):
        self.guidance_generator = DynamicGuidanceGenerator()

    def enhance_scenario_with_guidance(
            self,
            db: Session,
            base_scenario: Dict[str, Any],
            victim_profile: Dict[str, Any],
            enhancement_type: str = "scenario_optimization") -> Dict[str, Any]:
        """
        기본 시나리오를 지침 생성 시스템으로 개선합니다.

        Args:
            base_scenario: 기본 시나리오 {"description", "purpose", "steps"}
            victim_profile: 피해자 프로필
            enhancement_type: 개선 유형

        Returns:
            개선된 시나리오
        """
        try:
            logger.info("[ScenarioEnhancer] 시나리오 개선 시작")

            # 지침 생성 (초기 시나리오용 특별 모드)
            enhancement_guidance = self._generate_scenario_guidance(
                db=db,
                scenario=base_scenario,
                victim_profile=victim_profile,
                enhancement_type=enhancement_type)

            # 시나리오 개선 적용
            enhanced_scenario = self._apply_guidance_to_scenario(
                base_scenario=base_scenario,
                guidance=enhancement_guidance,
                victim_profile=victim_profile)

            logger.info("[ScenarioEnhancer] 시나리오 개선 완료")
            return enhanced_scenario

        except Exception as e:
            logger.error(f"[ScenarioEnhancer] 시나리오 개선 실패: {e}")
            # 실패 시 원본 시나리오 반환
            return base_scenario

    def _generate_scenario_guidance(self, db: Session, scenario: Dict[str,
                                                                      Any],
                                    victim_profile: Dict[str, Any],
                                    enhancement_type: str) -> Dict[str, Any]:
        """시나리오 개선을 위한 특별 지침 생성"""

        # 초기 시나리오 개선용 가상 판정 데이터
        mock_previous_judgments = [{
            "round":
            0,
            "phishing":
            False,
            "reason":
            "초기 시나리오 분석 - 개선 필요",
            "analysis_type":
            enhancement_type,
            "victim_vulnerability_assessment":
            self._assess_victim_vulnerability(victim_profile)
        }]

        try:
            guidance_result = self.guidance_generator.generate_guidance(
                db=db,
                case_id="scenario_enhancement",  # 특별 케이스 ID
                round_no=1,
                scenario=scenario,
                victim_profile=victim_profile,
                previous_judgments=mock_previous_judgments)
            return guidance_result
        except Exception as e:
            logger.error(f"[ScenarioEnhancer] 지침 생성 실패: {e}")
            return self._get_fallback_guidance(victim_profile)

    def _assess_victim_vulnerability(
            self, victim_profile: Dict[str, Any]) -> Dict[str, str]:
        """피해자 취약성 평가"""
        knowledge = victim_profile.get("knowledge", {})
        traits = victim_profile.get("traits", {})
        meta = victim_profile.get("meta", {})

        vulnerability_score = 0
        vulnerabilities = []

        # 지식 수준 평가
        if knowledge.get("financial_literacy") in ["낮음", "매우 낮음"]:
            vulnerability_score += 2
            vulnerabilities.append("금융 리터러시 부족")

        if knowledge.get("digital_literacy") in ["낮음", "매우 낮음"]:
            vulnerability_score += 2
            vulnerabilities.append("디지털 리터러시 부족")

        # 성격 특성 평가
        if traits.get("trust") in ["높음", "매우 높음"]:
            vulnerability_score += 1
            vulnerabilities.append("높은 신뢰성")

        if traits.get("suspicion") in ["낮음", "매우 낮음"]:
            vulnerability_score += 2
            vulnerabilities.append("낮은 의심성")

        # 연령대 평가
        age = meta.get("age", 0)
        if isinstance(age, int) and age >= 60:
            vulnerability_score += 1
            vulnerabilities.append("고령층")

        return {
            "score":
            str(vulnerability_score),
            "level":
            "높음" if vulnerability_score >= 5 else
            "중간" if vulnerability_score >= 3 else "낮음",
            "factors":
            vulnerabilities
        }

    def _apply_guidance_to_scenario(
            self, base_scenario: Dict[str, Any], guidance: Dict[str, Any],
            victim_profile: Dict[str, Any]) -> Dict[str, Any]:
        """지침을 바탕으로 시나리오 개선"""

        enhanced_scenario = base_scenario.copy()
        guidance_text = guidance.get("guidance_text", "")
        categories = guidance.get("selected_categories", [])

        # Steps 개선
        enhanced_steps = self._enhance_steps(original_steps=base_scenario.get(
            "steps", []),
                                             guidance_text=guidance_text,
                                             categories=categories,
                                             victim_profile=victim_profile)

        enhanced_scenario["steps"] = enhanced_steps

        # Description 개선 (필요시)
        if "긴급성" in guidance_text or "B" in categories:
            original_desc = enhanced_scenario.get("description", "")
            if "긴급" not in original_desc:
                enhanced_scenario[
                    "description"] = f"{original_desc} (긴급 상황 강조)"

        # 메타데이터 추가
        enhanced_scenario["enhancement_info"] = {
            "applied_guidance": guidance_text,
            "categories": categories,
            "enhancement_timestamp": "initial_scenario_build"
        }

        return enhanced_scenario

    def _enhance_steps(self, original_steps: List[str], guidance_text: str,
                       categories: List[str],
                       victim_profile: Dict[str, Any]) -> List[str]:
        """Steps를 지침에 따라 개선"""

        if not original_steps:
            return self._generate_default_steps(guidance_text, categories)

        enhanced_steps = []

        for step in original_steps:
            enhanced_step = step

            # 카테고리별 개선
            if "B" in categories:  # 긴급성 강조
                if "긴급" not in enhanced_step:
                    enhanced_step = f"긴급하게 {enhanced_step.lower()}"

            if "C" in categories:  # 감정적 접근
                emotional_keywords = ["걱정", "불안", "위험"]
                if not any(keyword in enhanced_step
                           for keyword in emotional_keywords):
                    enhanced_step = f"{enhanced_step} (피해자의 불안감 자극)"

            if "D" in categories:  # 전문성 연출
                if "수사기관" in step or "경찰" in step:
                    enhanced_step = enhanced_step.replace(
                        "정보를", "공식 절차에 따른 정보를")

            enhanced_steps.append(enhanced_step)

        # 피해자 특성에 따른 추가 단계
        vulnerability = self._assess_victim_vulnerability(victim_profile)
        if vulnerability["level"] == "높음":
            enhanced_steps.append("피해자의 높은 신뢰성을 활용하여 추가 정보 획득")

        return enhanced_steps

    def _generate_default_steps(self, guidance_text: str,
                                categories: List[str]) -> List[str]:
        """기본 Steps가 없을 때 지침 기반 생성"""
        default_steps = ["신뢰 관계 구축", "개인정보 수집", "금융정보 획득"]

        if "B" in categories:  # 긴급성
            default_steps[0] = "긴급 상황 설정으로 즉시 신뢰 획득"

        if "C" in categories:  # 감정적 접근
            default_steps.insert(1, "피해자의 불안감과 책임감 자극")

        return default_steps

    def _get_fallback_guidance(
            self, victim_profile: Dict[str, Any]) -> Dict[str, Any]:
        """지침 생성 실패 시 기본 지침"""
        vulnerability = self._assess_victim_vulnerability(victim_profile)

        if vulnerability["level"] == "높음":
            return {
                "guidance_text":
                "피해자의 높은 취약성을 고려하여 점진적이고 신뢰 기반의 접근 방식을 사용하세요.",
                "selected_categories": ["A", "C", "E"],
                "reasoning": "피해자 취약성 분석 기반 기본 전략",
                "expected_effect": "높은 성공률 예상"
            }
        else:
            return {
                "guidance_text": "표준 피싱 전략을 사용하되 전문성을 강조하세요.",
                "selected_categories": ["D", "F"],
                "reasoning": "표준 접근법",
                "expected_effect": "일반적인 효과 예상"
            }
