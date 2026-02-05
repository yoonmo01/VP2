# app/services/agent/external_api.py
"""
외부 시스템과의 API 연결 모듈
- 생성된 대화를 외부 시스템에 전송
- 웹 서치 기반 새로운 수법 리포트 수신
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import os
import json
import httpx
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────
# VP-Web-Search 시스템 URL (기본 포트 8001)
EXTERNAL_API_BASE_URL = os.getenv("EXTERNAL_API_BASE_URL", "http://127.0.0.1:8001")
EXTERNAL_API_KEY = os.getenv("EXTERNAL_API_KEY", "")
EXTERNAL_API_TIMEOUT = float(os.getenv("EXTERNAL_API_TIMEOUT", "120"))  # 웹 서치는 시간이 걸림

# ON/OFF 설정
EXTERNAL_API_ENABLED = os.getenv("EXTERNAL_API_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

# 연속 피싱 실패 임계값 (이 값 이상 연속 실패 시 외부 API 호출)
CONSECUTIVE_FAIL_THRESHOLD = int(os.getenv("EXTERNAL_API_FAIL_THRESHOLD", "3"))

# 판정 후 즉시 외부 전송 (테스트용: 1회 이상 판정 시 바로 전송)
# EXTERNAL_API_SEND_ON_JUDGEMENT=1 이면 판정 1회 이상 시 바로 외부 시스템에 전송
SEND_ON_JUDGEMENT_ENABLED = os.getenv("EXTERNAL_API_SEND_ON_JUDGEMENT", "0").strip().lower() in ("1", "true", "yes", "on")

# 판정 횟수 임계값 (기본 1: 1회 이상 판정 시 전송)
JUDGEMENT_SEND_THRESHOLD = int(os.getenv("EXTERNAL_API_JUDGEMENT_THRESHOLD", "1"))


def is_external_api_enabled() -> bool:
    """외부 API 호출 활성화 여부"""
    return EXTERNAL_API_ENABLED


def is_send_on_judgement_enabled() -> bool:
    """판정 시 즉시 외부 전송 활성화 여부"""
    return SEND_ON_JUDGEMENT_ENABLED


def set_external_api_enabled(enabled: bool) -> None:
    """외부 API 호출 활성화/비활성화 (런타임 변경)"""
    global EXTERNAL_API_ENABLED
    EXTERNAL_API_ENABLED = enabled
    logger.info("[ExternalAPI] 활성화 상태 변경: %s", "ON" if enabled else "OFF")


def set_send_on_judgement_enabled(enabled: bool) -> None:
    """판정 시 즉시 외부 전송 활성화/비활성화 (런타임 변경)"""
    global SEND_ON_JUDGEMENT_ENABLED
    SEND_ON_JUDGEMENT_ENABLED = enabled
    logger.info("[ExternalAPI] 판정 시 즉시 전송: %s", "ON" if enabled else "OFF")


class ExternalAPIError(Exception):
    """외부 API 호출 실패"""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


# ─────────────────────────────────────────────────────────
# 연속 피싱 실패 추적기
# ─────────────────────────────────────────────────────────
class ConsecutiveFailTracker:
    """
    케이스별 연속 피싱 실패 횟수 추적
    - 피싱 성공(phishing=True) → 카운터 리셋
    - 피싱 실패(phishing=False) → 카운터 증가
    - 임계값 도달 시 외부 API 호출 트리거
    """

    def __init__(self, threshold: int = CONSECUTIVE_FAIL_THRESHOLD):
        self.threshold = threshold
        self._fail_counts: Dict[str, int] = {}  # case_id -> consecutive fail count
        self._triggered: Dict[str, bool] = {}   # case_id -> 이미 트리거됨 여부

    def record_judgement(self, case_id: str, phishing: bool) -> bool:
        """
        판정 결과 기록 및 외부 API 호출 필요 여부 반환

        Args:
            case_id: 케이스 ID
            phishing: 피싱 성공 여부 (True=피싱 성공, False=피싱 실패/방어 성공)

        Returns:
            bool: 외부 API 호출이 필요하면 True
        """
        case_id = str(case_id)

        if phishing:
            # 피싱 성공 → 카운터 리셋
            self._fail_counts[case_id] = 0
            self._triggered[case_id] = False
            logger.debug("[FailTracker] case=%s 피싱 성공, 카운터 리셋", case_id)
            return False

        # 피싱 실패 → 카운터 증가
        current = self._fail_counts.get(case_id, 0) + 1
        self._fail_counts[case_id] = current

        logger.info(
            "[FailTracker] case=%s 연속 피싱 실패: %d/%d",
            case_id, current, self.threshold
        )

        # 임계값 도달 체크
        if current >= self.threshold:
            # 이미 트리거된 경우 중복 호출 방지
            if self._triggered.get(case_id, False):
                logger.debug("[FailTracker] case=%s 이미 트리거됨, 스킵", case_id)
                return False

            self._triggered[case_id] = True
            logger.info(
                "[FailTracker] case=%s 연속 %d회 실패 → 외부 API 호출 트리거!",
                case_id, current
            )
            return True

        return False

    def get_fail_count(self, case_id: str) -> int:
        """현재 연속 실패 횟수 조회"""
        return self._fail_counts.get(str(case_id), 0)

    def reset(self, case_id: str) -> None:
        """케이스 카운터 리셋"""
        case_id = str(case_id)
        self._fail_counts.pop(case_id, None)
        self._triggered.pop(case_id, None)

    def reset_all(self) -> None:
        """전체 카운터 리셋"""
        self._fail_counts.clear()
        self._triggered.clear()


# 싱글톤 인스턴스
_fail_tracker: Optional[ConsecutiveFailTracker] = None


def get_fail_tracker() -> ConsecutiveFailTracker:
    """싱글톤 실패 추적기 반환"""
    global _fail_tracker
    if _fail_tracker is None:
        _fail_tracker = ConsecutiveFailTracker()
    return _fail_tracker


# ─────────────────────────────────────────────────────────
# 요청/응답 데이터 모델
# ─────────────────────────────────────────────────────────
@dataclass
class ConversationPayload:
    """외부 시스템에 전송할 대화 데이터"""
    case_id: str
    round_no: int
    turns: List[Dict[str, Any]]
    scenario: Dict[str, Any]
    victim_profile: Dict[str, Any]
    guidance: Dict[str, Any]  # 전략/수법/감정
    judgement: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "round_no": self.round_no,
            "turns": self.turns,
            "scenario": self.scenario,
            "victim_profile": self.victim_profile,
            "guidance": self.guidance,
            "judgement": self.judgement,
            "timestamp": self.timestamp,
        }


@dataclass
class MethodReport:
    """외부 시스템에서 받는 새로운 수법 리포트"""
    report_id: str
    new_methods: List[Dict[str, Any]]  # 새로운 수법 목록
    sources: List[str]  # 웹 서치 소스 URL
    summary: str  # 요약
    recommendations: List[str]  # 권장 사항
    created_at: str
    raw_response: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MethodReport":
        return cls(
            report_id=data.get("report_id", ""),
            new_methods=data.get("new_methods", []),
            sources=data.get("sources", []),
            summary=data.get("summary", ""),
            recommendations=data.get("recommendations", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            raw_response=data,
        )


# ─────────────────────────────────────────────────────────
# API 클라이언트
# ─────────────────────────────────────────────────────────
class ExternalAPIClient:
    """외부 시스템 API 클라이언트"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or EXTERNAL_API_BASE_URL).rstrip("/")
        self.api_key = api_key or EXTERNAL_API_KEY
        self.timeout = timeout or EXTERNAL_API_TIMEOUT

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _handle_response(self, response: httpx.Response, context: str) -> Dict[str, Any]:
        """응답 처리 및 에러 핸들링"""
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "[ExternalAPI] %s 실패: status=%d, response=%s",
                context, e.response.status_code, e.response.text[:500]
            )
            raise ExternalAPIError(
                f"{context} 실패: HTTP {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.text,
            )
        except json.JSONDecodeError as e:
            logger.error("[ExternalAPI] %s JSON 파싱 실패: %s", context, e)
            raise ExternalAPIError(f"{context} JSON 파싱 실패")
        except Exception as e:
            logger.error("[ExternalAPI] %s 예외: %s", context, e)
            raise ExternalAPIError(f"{context} 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # 대화 전송 API
    # ─────────────────────────────────────────────────────────
    def send_conversation(self, payload: ConversationPayload) -> Dict[str, Any]:
        """
        생성된 대화를 외부 시스템에 전송

        Returns:
            {
                "ok": True,
                "received_id": "...",
                "message": "..."
            }
        """
        url = f"{self.base_url}/api/v1/conversations"

        logger.info(
            "[ExternalAPI] 대화 전송: case_id=%s, round=%d, turns=%d",
            payload.case_id, payload.round_no, len(payload.turns)
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json=payload.to_dict(),
                    headers=self._get_headers(),
                )

            result = self._handle_response(response, "대화 전송")
            logger.info("[ExternalAPI] 대화 전송 성공: %s", result.get("received_id", ""))
            return {"ok": True, **result}

        except ExternalAPIError:
            raise
        except Exception as e:
            logger.error("[ExternalAPI] 대화 전송 예외: %s", e)
            raise ExternalAPIError(f"대화 전송 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # 새로운 수법 리포트 요청 API
    # ─────────────────────────────────────────────────────────
    def request_method_report(
        self,
        case_id: str,
        scenario_type: str,
        keywords: Optional[List[str]] = None,
        conversation_summary: Optional[str] = None,
    ) -> MethodReport:
        """
        웹 서치 기반 새로운 수법 리포트 요청

        Args:
            case_id: 케이스 ID
            scenario_type: 시나리오 유형 (예: "검찰사칭", "대출사기" 등)
            keywords: 추가 검색 키워드
            conversation_summary: 대화 요약 (컨텍스트 제공용)

        Returns:
            MethodReport: 새로운 수법 리포트
        """
        url = f"{self.base_url}/api/v1/methods/report"

        request_body = {
            "case_id": case_id,
            "scenario_type": scenario_type,
            "keywords": keywords or [],
            "conversation_summary": conversation_summary or "",
            "request_time": datetime.now().isoformat(),
        }

        logger.info(
            "[ExternalAPI] 수법 리포트 요청: case_id=%s, scenario=%s",
            case_id, scenario_type
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json=request_body,
                    headers=self._get_headers(),
                )

            result = self._handle_response(response, "수법 리포트 요청")
            report = MethodReport.from_dict(result)

            logger.info(
                "[ExternalAPI] 수법 리포트 수신: report_id=%s, methods=%d",
                report.report_id, len(report.new_methods)
            )
            return report

        except ExternalAPIError:
            raise
        except Exception as e:
            logger.error("[ExternalAPI] 수법 리포트 요청 예외: %s", e)
            raise ExternalAPIError(f"수법 리포트 요청 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # 대화 전송 + 리포트 수신 통합 API
    # ─────────────────────────────────────────────────────────
    def send_and_get_report(
        self,
        payload: ConversationPayload,
        scenario_type: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        대화 전송 후 새로운 수법 리포트 수신 (통합 호출)

        Returns:
            {
                "ok": True,
                "send_result": {...},
                "report": MethodReport
            }
        """
        # 1) 대화 전송
        send_result = self.send_conversation(payload)

        # 2) 시나리오 타입 추출
        if not scenario_type:
            scenario_type = payload.scenario.get("type") or payload.scenario.get("scenario_type") or "검찰사칭"

        # 3) 대화 요약 생성
        conversation_summary = self._summarize_conversation(payload.turns)

        # 4) 리포트 요청
        report = self.request_method_report(
            case_id=payload.case_id,
            scenario_type=scenario_type,
            keywords=keywords,
            conversation_summary=conversation_summary,
        )

        return {
            "ok": True,
            "send_result": send_result,
            "report": report,
        }

    def _summarize_conversation(self, turns: List[Dict[str, Any]], max_length: int = 500) -> str:
        """대화 요약 생성"""
        parts = []
        for t in turns[-10:]:  # 최근 10턴만
            role = t.get("role", "unknown")
            text = t.get("text") or t.get("content") or t.get("dialogue") or ""
            if isinstance(text, dict):
                text = text.get("dialogue") or text.get("utterance") or str(text)
            if text:
                parts.append(f"[{role}] {text[:100]}")

        summary = "\n".join(parts)
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
        return summary

    # ─────────────────────────────────────────────────────────
    # 헬스 체크
    # ─────────────────────────────────────────────────────────
    def health_check(self) -> bool:
        """외부 시스템 연결 상태 확인"""
        url = f"{self.base_url}/health"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self._get_headers())
            return response.status_code == 200
        except Exception as e:
            logger.warning("[ExternalAPI] 헬스 체크 실패: %s", e)
            return False


# ─────────────────────────────────────────────────────────
# 편의 함수 (싱글톤 클라이언트)
# ─────────────────────────────────────────────────────────
_client: Optional[ExternalAPIClient] = None


def get_external_client() -> ExternalAPIClient:
    """싱글톤 클라이언트 반환"""
    global _client
    if _client is None:
        _client = ExternalAPIClient()
    return _client


def send_conversation_to_external(
    case_id: str,
    round_no: int,
    turns: List[Dict[str, Any]],
    scenario: Dict[str, Any],
    victim_profile: Dict[str, Any],
    guidance: Dict[str, Any],
    judgement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """대화를 외부 시스템에 전송 (편의 함수)"""
    payload = ConversationPayload(
        case_id=case_id,
        round_no=round_no,
        turns=turns,
        scenario=scenario,
        victim_profile=victim_profile,
        guidance=guidance,
        judgement=judgement,
    )
    return get_external_client().send_conversation(payload)


def get_new_method_report(
    case_id: str,
    scenario_type: str,
    keywords: Optional[List[str]] = None,
    conversation_summary: Optional[str] = None,
) -> MethodReport:
    """새로운 수법 리포트 요청 (편의 함수)"""
    return get_external_client().request_method_report(
        case_id=case_id,
        scenario_type=scenario_type,
        keywords=keywords,
        conversation_summary=conversation_summary,
    )


# ─────────────────────────────────────────────────────────
# summary_tool 기반 외부 API 호출
# ─────────────────────────────────────────────────────────
@dataclass
class SummaryToolOutput:
    """
    summary_tool의 출력 형식
    {"첫번째 대화":"str","두번째 대화":"str","세번째 대화":"str"}
    """
    first_conversation: str   # 첫번째 대화
    second_conversation: str  # 두번째 대화
    third_conversation: str   # 세번째 대화

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "SummaryToolOutput":
        return cls(
            first_conversation=data.get("첫번째 대화", ""),
            second_conversation=data.get("두번째 대화", ""),
            third_conversation=data.get("세번째 대화", ""),
        )

    def to_conversation_summary(self) -> str:
        """VP-Web-Search에 전달할 대화 요약 문자열 생성"""
        parts = []
        if self.first_conversation:
            parts.append(f"[1차 대화]\n{self.first_conversation}")
        if self.second_conversation:
            parts.append(f"[2차 대화]\n{self.second_conversation}")
        if self.third_conversation:
            parts.append(f"[3차 대화]\n{self.third_conversation}")
        return "\n\n".join(parts)


def trigger_from_summary_tool(
    summary_data: Dict[str, str],
    case_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    summary_tool 실행 시 외부 API 호출

    summary_tool이 실행되면 이 함수를 호출하여 VP-Web-Search 시스템에
    대화 요약을 전송하고 공격 강화 리포트를 받아옴

    Args:
        summary_data: summary_tool의 출력
            {"첫번째 대화":"str","두번째 대화":"str","세번째 대화":"str"}
        case_id: 케이스 ID (없으면 자동 생성)

    Returns:
        외부 API 호출 결과 (비활성화 상태면 None)
    """
    # 1) ON/OFF 체크
    if not is_external_api_enabled():
        logger.debug("[ExternalAPI] 비활성화 상태, summary_tool 트리거 스킵")
        return None

    logger.info("[ExternalAPI] summary_tool 트리거! 외부 시스템 호출 시작...")

    # 2) summary_data 파싱
    try:
        summary = SummaryToolOutput.from_dict(summary_data)
        conversation_summary = summary.to_conversation_summary()
    except Exception as e:
        logger.error("[ExternalAPI] summary_data 파싱 실패: %s", e)
        return {
            "triggered": True,
            "reason": "summary_tool 실행",
            "error": f"summary_data 파싱 실패: {e}",
        }

    # 3) case_id 생성 (없으면)
    if not case_id:
        case_id = f"summary_{hash(conversation_summary) % 100000}"

    # 4) VP-Web-Search API 호출 (공격 강화 분석)
    try:
        client = get_external_client()
        url = f"{client.base_url}/api/attack/enhance"

        request_body = {
            "conversation_summary": conversation_summary,
        }

        logger.info(
            "[ExternalAPI] 공격 강화 분석 요청: case_id=%s, summary_length=%d",
            case_id, len(conversation_summary)
        )

        with httpx.Client(timeout=client.timeout) as http_client:
            response = http_client.post(
                url,
                json=request_body,
                headers=client._get_headers(),
            )

        result = client._handle_response(response, "공격 강화 분석")

        logger.info(
            "[ExternalAPI] 공격 강화 분석 성공! status=%s",
            result.get("status", "unknown")
        )

        return {
            "triggered": True,
            "reason": "summary_tool 실행",
            "case_id": case_id,
            "result": result,
        }

    except ExternalAPIError as e:
        logger.error("[ExternalAPI] 공격 강화 분석 실패: %s", e)
        return {
            "triggered": True,
            "reason": "summary_tool 실행",
            "case_id": case_id,
            "error": str(e),
        }
    except Exception as e:
        logger.exception("[ExternalAPI] 공격 강화 분석 예외")
        return {
            "triggered": True,
            "reason": "summary_tool 실행",
            "case_id": case_id,
            "error": str(e),
        }


# (Legacy) 판정 결과 기반 자동 외부 API 호출 - 연속 실패 체크용
# 현재는 summary_tool 트리거 방식 사용
def check_and_trigger_external_api(
    case_id: str,
    phishing: bool,
    turns: Optional[List[Dict[str, Any]]] = None,
    scenario: Optional[Dict[str, Any]] = None,
    victim_profile: Optional[Dict[str, Any]] = None,
    guidance: Optional[Dict[str, Any]] = None,
    judgement: Optional[Dict[str, Any]] = None,
    round_no: int = 1,
) -> Optional[Dict[str, Any]]:
    """
    [DEPRECATED] 연속 실패 기반 트리거 - 더 이상 사용하지 않음
    대신 trigger_from_summary_tool() 사용
    """
    logger.warning(
        "[ExternalAPI] check_and_trigger_external_api는 deprecated됨. "
        "trigger_from_summary_tool()을 사용하세요."
    )
    return None


# ─────────────────────────────────────────────────────────
# 판정 후 즉시 외부 시스템 전송 (감정 라벨 제거)
# ─────────────────────────────────────────────────────────
def _strip_emotion_labels_from_turns(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    대화 turns에서 감정 라벨링 정보를 제거하고 순수 대화 내용만 반환

    제거 대상:
    - emotion, pred4, pred8, probs4, probs8
    - hmm, hmm_summary, hmm_result
    - cue_scores, surprise_to, emotion4, emotion8

    반환:
    - role, text/content/dialogue만 포함된 clean turns
    """
    EMOTION_KEYS = {
        "emotion", "pred4", "pred8", "probs4", "probs8",
        "hmm", "hmm_summary", "hmm_result",
        "cue_scores", "surprise_to", "emotion4", "emotion8",
        "is_convinced", "thoughts",  # 피해자 내면 정보도 제거
    }

    clean_turns: List[Dict[str, Any]] = []

    for t in turns:
        if not isinstance(t, dict):
            continue

        # 기본 정보만 추출
        role = t.get("role") or t.get("speaker") or t.get("actor") or "unknown"

        # text 추출 (다양한 형식 지원)
        text = t.get("text") or t.get("content") or t.get("dialogue") or ""

        # text가 JSON 형식인 경우 dialogue만 추출
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and "dialogue" in obj:
                    text = obj.get("dialogue", "")
            except json.JSONDecodeError:
                pass
        elif isinstance(text, dict):
            text = text.get("dialogue") or text.get("text") or str(text)

        # clean turn 생성
        clean_turn = {
            "role": str(role).strip().lower(),
            "text": str(text).strip() if text else "",
            "turn_index": t.get("turn_index") or t.get("turn") or len(clean_turns),
        }

        # 유효한 턴만 추가 (빈 텍스트 제외)
        if clean_turn["text"]:
            clean_turns.append(clean_turn)

    return clean_turns


# 판정 횟수 추적기 (케이스별)
class JudgementCountTracker:
    """
    케이스별 판정 횟수 추적
    - 판정 1회 이상 시 외부 API 호출 트리거 (설정에 따라)
    """

    def __init__(self, threshold: int = JUDGEMENT_SEND_THRESHOLD):
        self.threshold = threshold
        self._counts: Dict[str, int] = {}  # case_id -> judgement count
        self._sent: Dict[str, bool] = {}   # case_id -> 이미 전송됨 여부

    def record_judgement(self, case_id: str) -> bool:
        """
        판정 결과 기록 및 외부 API 전송 필요 여부 반환

        Args:
            case_id: 케이스 ID

        Returns:
            bool: 외부 API 전송이 필요하면 True
        """
        case_id = str(case_id)

        # 카운터 증가
        current = self._counts.get(case_id, 0) + 1
        self._counts[case_id] = current

        logger.info(
            "[JudgementTracker] case=%s 판정 횟수: %d/%d",
            case_id, current, self.threshold
        )

        # 임계값 도달 체크
        if current >= self.threshold:
            # 이미 전송된 경우 중복 방지
            if self._sent.get(case_id, False):
                logger.debug("[JudgementTracker] case=%s 이미 전송됨, 스킵", case_id)
                return False

            self._sent[case_id] = True
            logger.info(
                "[JudgementTracker] case=%s %d회 판정 도달 → 외부 API 전송 트리거!",
                case_id, current
            )
            return True

        return False

    def get_count(self, case_id: str) -> int:
        """현재 판정 횟수 조회"""
        return self._counts.get(str(case_id), 0)

    def reset(self, case_id: str) -> None:
        """케이스 카운터 리셋"""
        case_id = str(case_id)
        self._counts.pop(case_id, None)
        self._sent.pop(case_id, None)

    def reset_all(self) -> None:
        """전체 카운터 리셋"""
        self._counts.clear()
        self._sent.clear()


# 싱글톤 인스턴스
_judgement_tracker: Optional[JudgementCountTracker] = None


def get_judgement_tracker() -> JudgementCountTracker:
    """싱글톤 판정 추적기 반환"""
    global _judgement_tracker
    if _judgement_tracker is None:
        _judgement_tracker = JudgementCountTracker()
    return _judgement_tracker


@dataclass
class JudgementSendPayload:
    """판정 후 외부 시스템에 전송할 데이터"""
    case_id: str
    round_no: int
    turns: List[Dict[str, Any]]  # 감정 라벨 제거된 순수 대화
    judgement: Dict[str, Any]    # 판정 결과
    scenario: Optional[Dict[str, Any]] = None
    victim_profile: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "round_no": self.round_no,
            "turns": self.turns,
            "judgement": self.judgement,
            "scenario": self.scenario or {},
            "victim_profile": self.victim_profile or {},
            "timestamp": self.timestamp,
            "source": "judgement_trigger",
        }


def send_judgement_to_external(
    case_id: str,
    round_no: int,
    turns: List[Dict[str, Any]],
    judgement: Dict[str, Any],
    scenario: Optional[Dict[str, Any]] = None,
    victim_profile: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    판정 후 즉시 외부 시스템에 대화+판정 전송

    - EXTERNAL_API_SEND_ON_JUDGEMENT=1 일 때만 동작
    - 감정 라벨이 제거된 순수 대화 내용만 전송
    - 판정 결과(phishing, risk, evidence 등) 포함

    Args:
        case_id: 케이스 ID
        round_no: 라운드 번호
        turns: 원본 대화 turns (감정 라벨 포함 가능)
        judgement: 판정 결과 (make_judgement의 verdict)
        scenario: 시나리오 정보 (선택)
        victim_profile: 피해자 프로필 (선택)

    Returns:
        전송 결과 또는 None (비활성화 상태)
    """
    # 1) ON/OFF 체크
    if not is_send_on_judgement_enabled():
        logger.debug("[ExternalAPI] 판정 시 즉시 전송 비활성화 상태, 스킵")
        return None

    # 2) 판정 횟수 체크
    tracker = get_judgement_tracker()
    should_send = tracker.record_judgement(case_id)

    if not should_send:
        logger.debug("[ExternalAPI] case=%s 아직 임계값 미도달, 전송 스킵", case_id)
        return None

    logger.info("[ExternalAPI] 판정 후 즉시 전송 트리거! case=%s, round=%d", case_id, round_no)

    # 3) 감정 라벨 제거
    clean_turns = _strip_emotion_labels_from_turns(turns)

    logger.info(
        "[ExternalAPI] 감정 라벨 제거: 원본 %d턴 → 정제 %d턴",
        len(turns), len(clean_turns)
    )

    # 4) 전송 payload 생성
    payload = JudgementSendPayload(
        case_id=str(case_id),
        round_no=round_no,
        turns=clean_turns,
        judgement=judgement,
        scenario=scenario,
        victim_profile=victim_profile,
    )

    # 5) 외부 API 호출
    try:
        client = get_external_client()
        url = f"{client.base_url}/api/v1/judgements"

        logger.info(
            "[ExternalAPI] 판정 전송 요청: case_id=%s, round=%d, turns=%d",
            case_id, round_no, len(clean_turns)
        )

        with httpx.Client(timeout=client.timeout) as http_client:
            response = http_client.post(
                url,
                json=payload.to_dict(),
                headers=client._get_headers(),
            )

        result = client._handle_response(response, "판정 전송")

        logger.info(
            "[ExternalAPI] 판정 전송 성공! case_id=%s, status=%s",
            case_id, result.get("status", "ok")
        )

        return {
            "triggered": True,
            "reason": f"판정 {tracker.get_count(case_id)}회 도달",
            "case_id": case_id,
            "round_no": round_no,
            "turns_sent": len(clean_turns),
            "result": result,
        }

    except ExternalAPIError as e:
        logger.error("[ExternalAPI] 판정 전송 실패: %s", e)
        return {
            "triggered": True,
            "reason": f"판정 {tracker.get_count(case_id)}회 도달",
            "case_id": case_id,
            "round_no": round_no,
            "error": str(e),
        }
    except Exception as e:
        logger.exception("[ExternalAPI] 판정 전송 예외")
        return {
            "triggered": True,
            "reason": f"판정 {tracker.get_count(case_id)}회 도달",
            "case_id": case_id,
            "round_no": round_no,
            "error": str(e),
        }
