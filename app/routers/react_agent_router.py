# app/routers/react_agent_router.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.logging import get_logger
from app.services.agent.orchestrator_react import run_orchestrated

# ✅ 새 스키마 사용
from app.schemas.simulation_request import SimulationStartRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/react-agent", tags=["React Agent"])


# ---------- Response Schema (유지) ----------
from pydantic import BaseModel, Field

class SimulationResponse(BaseModel):
    success: bool
    case_id: UUID
    rounds: int
    turns_per_round: int
    timestamp: str
    meta: Dict[str, Any]


# ---------- Route (오케스트레이터 진입점 하나) ----------
@router.post(
    "/simulation",
    response_model=SimulationResponse,
    summary="툴 기반 React 오케스트레이션 시뮬레이션",
)
def start_simulation(req: SimulationStartRequest, db: Session = Depends(get_db)):
    """
    프론트 → 오케스트레이터(툴 기반) 단일 진입점.

    선택 규칙:
    - 피해자: custom_victim O → 그 데이터 사용 / 없으면 victim_id로 DB 로드
    - 시나리오: custom_scenario O → Tavily 생성→DB 저장→사용 / 없으면 offender_id로 DB 로드

    서버 고정:
    - turns_per_round = 15 (공+피 한 쌍 = 1턴)
    - 라운드 수는 오케스트레이터가 내부 판단(2~5회)
    - Tavily는 custom_scenario 있을 때 자동 활성화
    """
    try:
        # Tavily 사용 여부: 커스텀 시나리오가 있고, (프론트에서 켠 경우 OR 서버가 강제)면 True
        tavily_used_flag = bool(req.custom_scenario) and bool(req.use_tavily or True)

        # 오케스트레이터에 그대로 전달(한 곳에서 분기/DB 로딩/템플릿 패키징 처리)
        payload: Dict[str, Any] = req.model_dump(mode="python")
        payload["use_tavily"] = tavily_used_flag

        result: Dict[str, Any] = run_orchestrated(db, payload)

        if result.get("status") != "success":
            raise HTTPException(status_code=500, detail=result.get("error", "simulation failed"))

        return SimulationResponse(
            success=True,
            case_id=UUID(result["case_id"]),
            rounds=int(result.get("rounds", 0)),
            turns_per_round=int(result.get("turns_per_round", 15)),
            timestamp=result.get("timestamp", datetime.now().isoformat()),
            meta={
                "mcp_used": bool(result.get("mcp_used", True)),
                "tavily_used": bool(result.get("tavily_used", tavily_used_flag)),
                "used_tools": result.get("used_tools", []),
                "agent_type": "react_orchestrator",
                "automation_level": "full",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("React Agent 시뮬레이션 실행 실패")
        raise HTTPException(status_code=500, detail=f"시뮬레이션 실행 실패: {str(e)}")
