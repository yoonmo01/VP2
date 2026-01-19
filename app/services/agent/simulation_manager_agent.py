# app/services/agent/simulation_manager_agent.py
"""
(리팩토링) 시뮬레이션 매니저: 내부 로직 없음. 오케스트레이터에 위임.
- tools_* 및 graph, orchestrator_react 가 모든 판단/툴 호출을 처리
- 여기서는 과거 호환을 위해 동일 함수 이름만 유지
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.logging import get_logger
# from app.services.agent.orchestrator_react import run_orchestrated_simulation

logger = get_logger(__name__)

class SimulationManagerAgent:
    """
    과거 호환용 껍데기 클래스.
    내부 Agent/Tool/MCP 관리하지 않음. 오케스트레이터로 위임.
    """

    def __init__(self, db: Session):
        self.db = db

    # 과거 호출 경로를 유지
    def run_comprehensive_simulation(self, user_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        user_request 예:
        {
          "victim_info": {...},
          "scenario": {...},
          "attacker_model": "...",
          "victim_model": "...",
          "objectives": [...],
          "max_turns": 15,         # 공1+피1=1턴
          "offender_id": 1,
          "victim_id": 1
        }
        """
        try:
            result = run_orchestrated_simulation(self.db, user_request)
            return {
                "status": "success",
                "analysis": result.get("final_summary", ""),
                "thought_process": result.get("trace", []),   # 에이전트 중간 스텝
                "timestamp": datetime.now().isoformat(),
                "mcp_used": result.get("mcp_used", False),
            }
        except Exception as e:
            logger.exception("종합 시뮬레이션 실패")
            return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}


# 과거 모듈 함수 호환
def create_simulation_request(victim_info: Dict[str, Any],
                              scenario: Dict[str, Any],
                              attacker_model: str = "gpt-4o-mini",
                              victim_model: str = "gpt-4o-mini",
                              objectives: list[str] | None = None) -> Dict[str, Any]:
    return {
        "victim_info": victim_info,
        "scenario": scenario,
        "attacker_model": attacker_model,
        "victim_model": victim_model,
        "objectives": objectives or ["education"],
    }


def run_managed_simulation(db: Session, user_request: Dict[str, Any]) -> Dict[str, Any]:
    mgr = SimulationManagerAgent(db)
    return mgr.run_comprehensive_simulation(user_request)
