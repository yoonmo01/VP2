# app/api/tts_routes.py
from __future__ import annotations
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.logging import get_logger
from app.services.tts_cache import TTS_CACHE, TTSItem
from app.services.tts_service import start_tts_for_run_background

logger = get_logger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


# ─────────────────────────────────────────────────────────
# Pydantic 모델
# ─────────────────────────────────────────────────────────
class TTSSynthesizeRequest(BaseModel):
    mode: str = "dialogue"
    case_id: Optional[str] = None   # 없으면 마지막 처리된 case_id 사용
    run_no: Optional[int] = None    # 없으면 해당 case의 모든 run 반환


class TTSItemResponse(BaseModel):
    case_id: str
    run_no: int
    turn_index: int
    speaker: str
    text: str
    audioContent: str
    contentType: str
    totalDurationSec: Optional[float] = None
    charTimeSec: Optional[float] = None


class TTSSynthesizeResponse(BaseModel):
    items: List[TTSItemResponse]

# ─────────────────────────────────────────────────────────
# TTS 생성 시작용 모델
# ─────────────────────────────────────────────────────────
class TTSTurn(BaseModel):
    role: str
    text: str


class TTSStartRequest(BaseModel):
    case_id: str
    run_no: int
    turns: List[TTSTurn]


class TTSStartResponse(BaseModel):
    ok: bool
    message: str
# ─────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────
@router.post("/synthesize", response_model=TTSSynthesizeResponse)
def synthesize_tts(req: TTSSynthesizeRequest) -> TTSSynthesizeResponse:
    """
    프론트 TTSModal에서 호출하는 엔드포인트.

    - case_id가 없으면: 마지막으로 TTS가 생성된 case_id 사용
    - run_no가 없으면: 해당 case_id의 모든 run_no 항목을 한 번에 반환
    """
    logger.info(
        f"[TTS] synthesize 요청: mode={req.mode}, case_id={req.case_id}, run_no={req.run_no}"
    )

    # case_id 결정
    if req.case_id:
        case_id = req.case_id
    else:
        case_id = TTS_CACHE.get_last_case_id()
        if not case_id:
            logger.warning("[TTS] synthesize 실패: last_case_id 없음")
            raise HTTPException(status_code=404, detail="사용 가능한 TTS 데이터가 없습니다. (case_id 없음)")

    items: List[TTSItem] = []

    if req.run_no is not None:
        # 특정 run만
        got = TTS_CACHE.get_items(case_id, req.run_no)
        if not got:
            logger.info(
                f"[TTS] synthesize: 아직 준비 안 됨 (case_id={case_id}, run_no={req.run_no})"
            )
            raise HTTPException(
                status_code=404,
                detail=f"TTS 데이터가 아직 준비되지 않았습니다. case_id={case_id}, run_no={req.run_no}",
            )
        items.extend(got)
    else:
        # 해당 케이스의 전체 run
        got = TTS_CACHE.get_all_case_items(case_id)
        if not got:
            logger.info(
                f"[TTS] synthesize: 아직 준비 안 됨 (case_id={case_id}, run=ALL)"
            )
            raise HTTPException(
                status_code=404,
                detail=f"TTS 데이터가 아직 준비되지 않았습니다. case_id={case_id}",
            )
        items.extend(got)

    # 캐시 아이템 → 응답 포맷으로 변환
    resp_items: List[TTSItemResponse] = []
    for it in items:
        resp_items.append(
            TTSItemResponse(
                case_id=it.case_id,
                run_no=it.run_no,
                turn_index=it.turn_index,
                speaker=it.speaker,
                text=it.text,
                audioContent=it.audio_b64,
                contentType=it.content_type,
                totalDurationSec=it.total_duration_sec,
                charTimeSec=it.char_time_sec,
            )
        )

    logger.info(
        f"[TTS] synthesize 응답: case_id={case_id}, run_no={req.run_no if req.run_no is not None else 'ALL'}, items={len(resp_items)}"
    )
    return TTSSynthesizeResponse(items=resp_items)

@router.post("/start", response_model=TTSStartResponse)
def start_tts(req: TTSStartRequest) -> TTSStartResponse:
    """
    프론트에서 버튼을 눌렀을 때 호출.
    - turns: [{role, text}, ...] 를 그대로 받아서 TTS 백그라운드 생성 시작
    - 바로 반환하고, 실제 생성은 thread에서 비동기로 수행
    """
    if not req.turns:
        raise HTTPException(status_code=400, detail="turns가 비어있습니다.")

    raw_turns: List[Dict[str, Any]] = [
        {"role": t.role, "text": t.text} for t in req.turns
    ]

    logger.info(
        f"[TTS] /start 호출: case_id={req.case_id}, run_no={req.run_no}, turns={len(raw_turns)}"
    )

    # 이미 생성되어 있거나 생성 중이면, tts_service 쪽에서 자체적으로 skip 처리함
    start_tts_for_run_background(req.case_id, req.run_no, raw_turns)

    return TTSStartResponse(
        ok=True,
        message="TTS 생성이 비동기로 시작되었습니다.",
    )