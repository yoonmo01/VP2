# app/api/routes/external_integration.py
"""
외부 시스템 연동 API 엔드포인트
- POST /api/external/send-conversation: 대화 전송
- POST /api/external/method-report: 수법 리포트 요청
- POST /api/external/send-and-report: 대화 전송 + 리포트 통합
- GET /api/external/health: 외부 시스템 헬스 체크
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.logging import get_logger
from app.services.agent.external_api import (
    ExternalAPIClient,
    ExternalAPIError,
    ConversationPayload,
    MethodReport,
    get_external_client,
    is_external_api_enabled,
    set_external_api_enabled,
    is_send_on_judgement_enabled,
    set_send_on_judgement_enabled,
    get_fail_tracker,
    get_judgement_tracker,
    CONSECUTIVE_FAIL_THRESHOLD,
    JUDGEMENT_SEND_THRESHOLD,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/external", tags=["external-integration"])


# ─────────────────────────────────────────────────────────
# 요청/응답 스키마
# ─────────────────────────────────────────────────────────
class SendConversationRequest(BaseModel):
    case_id: str = Field(..., description="케이스 ID")
    round_no: int = Field(..., ge=1, description="라운드 번호")
    turns: List[Dict[str, Any]] = Field(..., description="대화 턴 목록")
    scenario: Dict[str, Any] = Field(default_factory=dict, description="시나리오 정보")
    victim_profile: Dict[str, Any] = Field(default_factory=dict, description="피해자 프로필")
    guidance: Dict[str, Any] = Field(default_factory=dict, description="전략/수법/감정")
    judgement: Optional[Dict[str, Any]] = Field(None, description="판정 결과")


class MethodReportRequest(BaseModel):
    case_id: str = Field(..., description="케이스 ID")
    scenario_type: str = Field(..., description="시나리오 유형 (예: 검찰사칭, 대출사기)")
    keywords: List[str] = Field(default_factory=list, description="추가 검색 키워드")
    conversation_summary: Optional[str] = Field(None, description="대화 요약")


class SendAndReportRequest(BaseModel):
    case_id: str = Field(..., description="케이스 ID")
    round_no: int = Field(..., ge=1, description="라운드 번호")
    turns: List[Dict[str, Any]] = Field(..., description="대화 턴 목록")
    scenario: Dict[str, Any] = Field(default_factory=dict, description="시나리오 정보")
    victim_profile: Dict[str, Any] = Field(default_factory=dict, description="피해자 프로필")
    guidance: Dict[str, Any] = Field(default_factory=dict, description="전략/수법/감정")
    judgement: Optional[Dict[str, Any]] = Field(None, description="판정 결과")
    # 리포트 관련
    scenario_type: Optional[str] = Field(None, description="시나리오 유형 (없으면 scenario에서 추출)")
    keywords: List[str] = Field(default_factory=list, description="추가 검색 키워드")


class MethodReportResponse(BaseModel):
    ok: bool
    report_id: str
    new_methods: List[Dict[str, Any]]
    sources: List[str]
    summary: str
    recommendations: List[str]
    created_at: str


class SendConversationResponse(BaseModel):
    ok: bool
    received_id: Optional[str] = None
    message: Optional[str] = None


class SendAndReportResponse(BaseModel):
    ok: bool
    send_result: Dict[str, Any]
    report: MethodReportResponse


class HealthResponse(BaseModel):
    ok: bool
    external_system: bool
    message: str


class SettingsResponse(BaseModel):
    enabled: bool
    fail_threshold: int
    send_on_judgement_enabled: bool
    judgement_threshold: int
    message: str


class SetEnabledRequest(BaseModel):
    enabled: bool = Field(..., description="외부 API 활성화 여부")


class SetSendOnJudgementRequest(BaseModel):
    enabled: bool = Field(..., description="판정 시 즉시 전송 활성화 여부")


class JudgementTrackerStatusResponse(BaseModel):
    case_id: str
    judgement_count: int
    threshold: int
    already_sent: bool


class FailTrackerStatusResponse(BaseModel):
    case_id: str
    consecutive_fails: int
    threshold: int
    will_trigger_next_fail: bool


# ─────────────────────────────────────────────────────────
# Webhook 수신용 스키마
# ─────────────────────────────────────────────────────────
class WebhookTechnique(BaseModel):
    name: str
    description: str
    application: str
    expected_effect: str
    fit_score: float


class WebhookReport(BaseModel):
    summary: Optional[str] = None
    vulnerabilities: List[str] = []
    techniques: List[WebhookTechnique] = []
    recommendations: List[str] = []
    implementation_guide: Optional[str] = None


class WebhookPayload(BaseModel):
    type: str = Field(..., description="analysis_complete 또는 analysis_error")
    case_id: str
    analysis_id: str
    report: Optional[Dict[str, Any]] = None
    techniques: List[Dict[str, Any]] = []
    sources_count: Optional[int] = None
    error: Optional[str] = None
    analyzed_at: str


class WebhookResponse(BaseModel):
    ok: bool
    message: str
    case_id: str
    analysis_id: str


# ─────────────────────────────────────────────────────────
# 설정 엔드포인트
# ─────────────────────────────────────────────────────────
@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    외부 API 설정 조회

    - enabled: 현재 활성화 상태
    - fail_threshold: 연속 실패 임계값
    - send_on_judgement_enabled: 판정 시 즉시 전송 활성화 상태
    - judgement_threshold: 판정 횟수 임계값
    """
    return SettingsResponse(
        enabled=is_external_api_enabled(),
        fail_threshold=CONSECUTIVE_FAIL_THRESHOLD,
        send_on_judgement_enabled=is_send_on_judgement_enabled(),
        judgement_threshold=JUDGEMENT_SEND_THRESHOLD,
        message="현재 설정 조회 완료",
    )


@router.post("/settings/enabled", response_model=SettingsResponse)
async def set_enabled(request: SetEnabledRequest):
    """
    외부 API ON/OFF 설정

    - enabled=true: 활성화 (연속 3회 실패 시 외부 API 호출)
    - enabled=false: 비활성화
    """
    set_external_api_enabled(request.enabled)
    return SettingsResponse(
        enabled=is_external_api_enabled(),
        fail_threshold=CONSECUTIVE_FAIL_THRESHOLD,
        send_on_judgement_enabled=is_send_on_judgement_enabled(),
        judgement_threshold=JUDGEMENT_SEND_THRESHOLD,
        message=f"외부 API {'활성화' if request.enabled else '비활성화'}됨",
    )


@router.post("/settings/send-on-judgement", response_model=SettingsResponse)
async def set_send_on_judgement(request: SetSendOnJudgementRequest):
    """
    판정 시 즉시 전송 ON/OFF 설정

    - enabled=true: 판정 1회 이상 시 즉시 외부 시스템에 전송 (감정 라벨 제거)
    - enabled=false: 비활성화 (기존 연속 실패 방식만 사용)

    환경변수: EXTERNAL_API_SEND_ON_JUDGEMENT
    임계값: EXTERNAL_API_JUDGEMENT_THRESHOLD (기본 1)
    """
    set_send_on_judgement_enabled(request.enabled)
    return SettingsResponse(
        enabled=is_external_api_enabled(),
        fail_threshold=CONSECUTIVE_FAIL_THRESHOLD,
        send_on_judgement_enabled=is_send_on_judgement_enabled(),
        judgement_threshold=JUDGEMENT_SEND_THRESHOLD,
        message=f"판정 시 즉시 전송 {'활성화' if request.enabled else '비활성화'}됨",
    )


@router.get("/judgement-tracker/{case_id}", response_model=JudgementTrackerStatusResponse)
async def get_judgement_tracker_status(case_id: str):
    """
    케이스별 판정 횟수 현황 조회

    - judgement_count: 현재 판정 횟수
    - threshold: 전송 트리거 임계값
    - already_sent: 이미 전송됨 여부
    """
    tracker = get_judgement_tracker()
    count = tracker.get_count(case_id)

    return JudgementTrackerStatusResponse(
        case_id=case_id,
        judgement_count=count,
        threshold=JUDGEMENT_SEND_THRESHOLD,
        already_sent=(count >= JUDGEMENT_SEND_THRESHOLD),
    )


@router.delete("/judgement-tracker/{case_id}")
async def reset_judgement_tracker(case_id: str):
    """
    케이스의 판정 횟수 카운터 리셋
    """
    tracker = get_judgement_tracker()
    tracker.reset(case_id)
    return {"ok": True, "message": f"케이스 {case_id}의 판정 카운터가 리셋되었습니다."}


@router.get("/fail-tracker/{case_id}", response_model=FailTrackerStatusResponse)
async def get_fail_tracker_status(case_id: str):
    """
    케이스별 연속 피싱 실패 현황 조회
    """
    tracker = get_fail_tracker()
    fail_count = tracker.get_fail_count(case_id)

    return FailTrackerStatusResponse(
        case_id=case_id,
        consecutive_fails=fail_count,
        threshold=CONSECUTIVE_FAIL_THRESHOLD,
        will_trigger_next_fail=(fail_count + 1 >= CONSECUTIVE_FAIL_THRESHOLD),
    )


@router.delete("/fail-tracker/{case_id}")
async def reset_fail_tracker(case_id: str):
    """
    케이스의 연속 실패 카운터 리셋
    """
    tracker = get_fail_tracker()
    tracker.reset(case_id)
    return {"ok": True, "message": f"케이스 {case_id}의 실패 카운터가 리셋되었습니다."}


# ─────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────
@router.post("/send-conversation", response_model=SendConversationResponse)
async def send_conversation(
    request: SendConversationRequest,
    db: Session = Depends(get_db),
):
    """
    생성된 대화를 외부 시스템에 전송

    - 시뮬레이션에서 생성된 대화 데이터를 외부 분석 시스템에 전달
    - 전략/수법/감정 guidance 정보 포함
    """
    try:
        payload = ConversationPayload(
            case_id=request.case_id,
            round_no=request.round_no,
            turns=request.turns,
            scenario=request.scenario,
            victim_profile=request.victim_profile,
            guidance=request.guidance,
            judgement=request.judgement,
        )

        client = get_external_client()
        result = client.send_conversation(payload)

        return SendConversationResponse(
            ok=result.get("ok", True),
            received_id=result.get("received_id"),
            message=result.get("message"),
        )

    except ExternalAPIError as e:
        logger.error("[API] 대화 전송 실패: %s", e)
        raise HTTPException(
            status_code=e.status_code or 502,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("[API] 대화 전송 예외")
        raise HTTPException(status_code=500, detail=f"대화 전송 실패: {e}")


@router.post("/method-report", response_model=MethodReportResponse)
async def request_method_report(
    request: MethodReportRequest,
    db: Session = Depends(get_db),
):
    """
    웹 서치 기반 새로운 수법 리포트 요청

    - 외부 시스템에서 웹 서치를 통해 최신 보이스피싱 수법 탐색
    - 시나리오 유형과 키워드 기반 맞춤 검색
    """
    try:
        client = get_external_client()
        report = client.request_method_report(
            case_id=request.case_id,
            scenario_type=request.scenario_type,
            keywords=request.keywords,
            conversation_summary=request.conversation_summary,
        )

        return MethodReportResponse(
            ok=True,
            report_id=report.report_id,
            new_methods=report.new_methods,
            sources=report.sources,
            summary=report.summary,
            recommendations=report.recommendations,
            created_at=report.created_at,
        )

    except ExternalAPIError as e:
        logger.error("[API] 수법 리포트 요청 실패: %s", e)
        raise HTTPException(
            status_code=e.status_code or 502,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("[API] 수법 리포트 요청 예외")
        raise HTTPException(status_code=500, detail=f"수법 리포트 요청 실패: {e}")


@router.post("/send-and-report", response_model=SendAndReportResponse)
async def send_conversation_and_get_report(
    request: SendAndReportRequest,
    db: Session = Depends(get_db),
):
    """
    대화 전송 + 수법 리포트 수신 통합 API

    1. 생성된 대화를 외부 시스템에 전송
    2. 해당 시나리오에 대한 최신 수법 리포트 수신
    """
    try:
        payload = ConversationPayload(
            case_id=request.case_id,
            round_no=request.round_no,
            turns=request.turns,
            scenario=request.scenario,
            victim_profile=request.victim_profile,
            guidance=request.guidance,
            judgement=request.judgement,
        )

        client = get_external_client()
        result = client.send_and_get_report(
            payload=payload,
            scenario_type=request.scenario_type,
            keywords=request.keywords,
        )

        report: MethodReport = result["report"]

        return SendAndReportResponse(
            ok=True,
            send_result=result["send_result"],
            report=MethodReportResponse(
                ok=True,
                report_id=report.report_id,
                new_methods=report.new_methods,
                sources=report.sources,
                summary=report.summary,
                recommendations=report.recommendations,
                created_at=report.created_at,
            ),
        )

    except ExternalAPIError as e:
        logger.error("[API] 통합 API 실패: %s", e)
        raise HTTPException(
            status_code=e.status_code or 502,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("[API] 통합 API 예외")
        raise HTTPException(status_code=500, detail=f"통합 API 실패: {e}")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    외부 시스템 연결 상태 확인
    """
    try:
        client = get_external_client()
        external_ok = client.health_check()

        return HealthResponse(
            ok=True,
            external_system=external_ok,
            message="정상" if external_ok else "외부 시스템 연결 실패",
        )
    except Exception as e:
        return HealthResponse(
            ok=False,
            external_system=False,
            message=f"헬스 체크 실패: {e}",
        )


# ─────────────────────────────────────────────────────────
# 내부용: DB에서 대화 조회 후 전송
# ─────────────────────────────────────────────────────────
class SendFromDBRequest(BaseModel):
    case_id: str = Field(..., description="케이스 ID (UUID)")
    round_no: int = Field(..., ge=1, description="라운드 번호")
    include_report: bool = Field(True, description="리포트도 함께 요청할지")


@router.post("/send-from-db")
async def send_conversation_from_db(
    request: SendFromDBRequest,
    db: Session = Depends(get_db),
):
    """
    DB에서 대화를 조회하여 외부 시스템에 전송

    - 케이스 ID와 라운드 번호로 저장된 대화 조회
    - 자동으로 scenario, victim_profile, guidance 정보 포함
    """
    from uuid import UUID
    from app.db import models as m
    from app.services.agent.guidance_generator import STRATEGY_DEFINITIONS, METHOD_DEFINITIONS

    try:
        case_uuid = UUID(request.case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 case_id 형식")

    # 1) 대화 로그 조회
    logs = (
        db.query(m.ConversationLog)
        .filter(
            m.ConversationLog.case_id == case_uuid,
            m.ConversationLog.run == request.round_no,
        )
        .order_by(m.ConversationLog.turn_index.asc())
        .all()
    )

    if not logs:
        raise HTTPException(status_code=404, detail="해당 라운드의 대화 로그가 없습니다")

    turns = [
        {
            "turn": log.turn_index,
            "role": log.role,
            "text": log.content,
        }
        for log in logs
    ]

    # 2) 케이스 정보 조회
    case = db.get(m.AdminCase, case_uuid)
    scenario = (case.scenario or {}) if case else {}

    # 3) 피해자 프로필 조회
    victim_profile = {}
    if case and hasattr(case, "victim_id") and case.victim_id:
        victim = db.get(m.Victim, case.victim_id)
        if victim:
            victim_profile = {
                "meta": victim.meta or {},
                "traits": victim.traits or [],
                "knowledge": victim.knowledge or {},
            }

    # 4) 최근 guidance 조회 (AdminCaseSummary에서)
    guidance = {"전략": "", "수법": "", "감정": ""}
    if hasattr(m, "AdminCaseSummary"):
        summary = (
            db.query(m.AdminCaseSummary)
            .filter(
                m.AdminCaseSummary.case_id == case_uuid,
                m.AdminCaseSummary.run == request.round_no,
            )
            .first()
        )
        if summary and hasattr(summary, "verdict_json"):
            vj = summary.verdict_json or {}
            guidance = vj.get("guidance", guidance)

    # 5) 판정 결과 조회
    judgement = None
    if hasattr(m, "AdminCaseSummary"):
        if summary:
            judgement = {
                "phishing": getattr(summary, "phishing", False),
                "risk_score": getattr(summary, "risk_score", 0),
                "risk_level": getattr(summary, "risk_level", ""),
            }

    # 6) 전송
    payload = ConversationPayload(
        case_id=request.case_id,
        round_no=request.round_no,
        turns=turns,
        scenario=scenario,
        victim_profile=victim_profile,
        guidance=guidance,
        judgement=judgement,
    )

    client = get_external_client()

    if request.include_report:
        scenario_type = scenario.get("type") or scenario.get("scenario_type") or "검찰사칭"
        result = client.send_and_get_report(payload, scenario_type=scenario_type)
        return result
    else:
        result = client.send_conversation(payload)
        return result


# ─────────────────────────────────────────────────────────
# Webhook 수신 (VP-Web-Search → VP2)
# ─────────────────────────────────────────────────────────
# 메모리 저장소 (실제 운영에서는 DB로 대체)
_received_reports: Dict[str, Dict[str, Any]] = {}


def get_latest_report_by_case(case_id: str) -> Optional[Dict[str, Any]]:
    """
    case_id로 가장 최신 웹 서치 리포트 조회
    - guidance_generator에서 호출하여 지침에 활용
    """
    results = [v for v in _received_reports.values() if v.get("case_id") == case_id]
    if not results:
        return None
    # analyzed_at 기준 최신순 정렬
    results.sort(key=lambda x: x.get("analyzed_at", ""), reverse=True)
    return results[0]


def get_techniques_by_case(case_id: str) -> List[Dict[str, Any]]:
    """
    case_id로 웹 서치에서 생성된 techniques 목록 조회
    """
    report = get_latest_report_by_case(case_id)
    if not report:
        return []
    return report.get("techniques", [])


@router.post("/webhook/receive-report", response_model=WebhookResponse)
async def receive_analysis_report(
    payload: WebhookPayload,
    db: Session = Depends(get_db),
):
    """
    VP-Web-Search 시스템에서 분석 결과를 수신하는 Webhook 엔드포인트

    - type: "analysis_complete" (성공) 또는 "analysis_error" (실패)
    - case_id: 분석 대상 케이스 ID
    - report: 분석 리포트 (summary, vulnerabilities, techniques, recommendations)
    - techniques: 생성된 공격 수법 목록
    """
    try:
        logger.info(
            f"[Webhook] 수신: type={payload.type}, case_id={payload.case_id}, "
            f"analysis_id={payload.analysis_id}"
        )

        # 메모리에 저장
        _received_reports[payload.analysis_id] = {
            "type": payload.type,
            "case_id": payload.case_id,
            "analysis_id": payload.analysis_id,
            "report": payload.report,
            "techniques": payload.techniques,
            "sources_count": payload.sources_count,
            "error": payload.error,
            "analyzed_at": payload.analyzed_at,
            "received_at": datetime.utcnow().isoformat(),
        }

        if payload.type == "analysis_complete":
            logger.info(
                f"[Webhook] 분석 완료 수신: case_id={payload.case_id}, "
                f"techniques={len(payload.techniques)}개, sources={payload.sources_count}개"
            )

            # TODO: 여기서 공격자 에이전트에 새로운 수법 전달 가능
            # 예: await update_attacker_techniques(payload.case_id, payload.techniques)

            return WebhookResponse(
                ok=True,
                message=f"분석 리포트 수신 완료: {len(payload.techniques)}개 수법",
                case_id=payload.case_id,
                analysis_id=payload.analysis_id,
            )

        elif payload.type == "analysis_error":
            logger.warning(
                f"[Webhook] 분석 에러 수신: case_id={payload.case_id}, "
                f"error={payload.error}"
            )
            return WebhookResponse(
                ok=True,
                message=f"분석 에러 수신: {payload.error}",
                case_id=payload.case_id,
                analysis_id=payload.analysis_id,
            )

        else:
            logger.warning(f"[Webhook] 알 수 없는 타입: {payload.type}")
            return WebhookResponse(
                ok=False,
                message=f"알 수 없는 타입: {payload.type}",
                case_id=payload.case_id,
                analysis_id=payload.analysis_id,
            )

    except Exception as e:
        logger.exception(f"[Webhook] 수신 처리 실패: {e}")
        raise HTTPException(status_code=500, detail=f"Webhook 처리 실패: {e}")


@router.get("/webhook/reports")
async def list_received_reports(limit: int = 50):
    """
    수신된 분석 리포트 목록 조회
    """
    items = list(_received_reports.values())[-limit:]
    return {
        "ok": True,
        "count": len(items),
        "items": items,
    }


@router.get("/webhook/reports/{analysis_id}")
async def get_received_report(analysis_id: str):
    """
    특정 분석 리포트 조회
    """
    data = _received_reports.get(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="분석 리포트 없음")
    return {"ok": True, "data": data}


@router.get("/webhook/reports/case/{case_id}")
async def get_reports_by_case(case_id: str):
    """
    케이스별 분석 리포트 조회
    """
    results = [v for v in _received_reports.values() if v.get("case_id") == case_id]
    if not results:
        raise HTTPException(status_code=404, detail="해당 케이스의 분석 리포트 없음")
    return {"ok": True, "count": len(results), "items": results}
