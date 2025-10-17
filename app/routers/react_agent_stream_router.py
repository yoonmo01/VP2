# app/routers/react_agent_stream_router.py
import json
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.agent.orchestrator_react import run_orchestrated_stream

router = APIRouter(prefix="/react-agent", tags=["React Agent"])


@router.get(
    "/simulation/stream",
    summary="오케스트레이션 SSE 스트림",
)
async def simulate_stream(
    request: Request,
    offender_id: int,
    victim_id: int,
    max_turns: int = 15,
    round_limit: int = 5,
    case_id: Optional[str] = None,
    use_tavily: bool = False,
    db: Session = Depends(get_db),
):
    """
    SSE 스트림 엔드포인트.
    - 쿼리: offender_id, victim_id, max_turns, round_limit, case_id(optional), use_tavily(optional)
    - 응답: text/event-stream
    """
    payload = {
        "offender_id": offender_id,
        "victim_id": victim_id,
        "max_turns": max_turns,
        "round_limit": round_limit,
        "case_id": case_id,
        "use_tavily": use_tavily,
    }

    async def sse_gen():
        # 초기 핑(브라우저/프록시가 스트림 열었음을 인식)
        yield "event: ping\ndata: {}\n\n"

        # 하트비트 타이머
        heartbeat_interval = 20  # 초
        last_sent = asyncio.get_event_loop().time()

        try:
            async for ev in run_orchestrated_stream(db, payload):
                # 클라이언트 중단 감지
                if await request.is_disconnected():
                    break

                # 표준 SSE 포맷으로 전송
                yield f"event: {ev.get('type','message')}\n"
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

                last_sent = asyncio.get_event_loop().time()

                # 컨텍스트 스위치
                await asyncio.sleep(0)

                # 주기 핑 (이벤트가 한동안 없을 때 연결 유지)
                now = asyncio.get_event_loop().time()
                if now - last_sent > heartbeat_interval:
                    yield "event: ping\ndata: {}\n\n"
                    last_sent = now

        except asyncio.CancelledError:
            # 클라이언트가 연결 끊으면 여기 들어옴(정상)
            raise
        except Exception as e:
            # 서버 에러 이벤트로 알림
            err = {"type": "error", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # 프록시가 압축/버퍼링하지 않도록(Nginx 등은 서버 설정도 필요)
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers=headers,
    )
