# vp_mcp/mcp_server/server.py
from __future__ import annotations
import os
import uvicorn
from typing import cast
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, Callable, Awaitable, Optional
import anyio

# ✅ .env를 가장 먼저 로드 (schemas/import 이전)
# server.py 위치: VP/vp_mcp/mcp_server/server.py
# .env 위치: VP/.env
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)
print(f">> dotenv loaded: {ENV_PATH}")
print(f">> ENV ATTACKER_MODEL={os.getenv('ATTACKER_MODEL')} VICTIM_MODEL={os.getenv('VICTIM_MODEL')}")

from mcp.server.fastmcp import FastMCP
from .db.base import init_db
from .services import fetch_turns_json
from .services import fetch_turns_json   # ← ✅ 추가: 방금 만든 서비스 임포트
from sqlalchemy.orm import Session
from .db.base import SessionLocal  

# ----------------------------
# 1) Pydantic 모델을 전역으로 선언
# ----------------------------
class MCPCall(BaseModel):
    tool: str
    args: Dict[str, Any] = {}

class SimulateRequest(BaseModel):
    arguments: Dict[str, Any]

# (안전하게) 참조 재빌드
MCPCall.model_rebuild()
SimulateRequest.model_rebuild()

# ----------------------------
# 2) helper / 구현 가져오기
# ----------------------------
USE_HELPER = False
REGISTER_HELPER: Optional[Callable[[FastMCP], None]] = None
SIM_IMPL = None
SIM_SCHEMA = None

try:
    # FastMCP 툴 등록 헬퍼
    from .tools.simulate_dialogue import register_simulate_dialogue_tool_fastmcp
    REGISTER_HELPER = register_simulate_dialogue_tool_fastmcp
    USE_HELPER = True
except Exception:
    REGISTER_HELPER = None

try:
    # 순수 구현 + 스키마 + ✅ 입력 보정 함수
    from .tools.simulate_dialogue import simulate_dialogue_impl, _coerce_input_legacy  # ✅
    from .schemas import SimulationInput
    SIM_IMPL = simulate_dialogue_impl
    SIM_SCHEMA = SimulationInput
except Exception:
    SIM_IMPL = None
    SIM_SCHEMA = None
    _coerce_input_legacy = None  # type: ignore

def build_app():
    init_db()

    # ----------------------------
    # 3) FastMCP 구성
    # ----------------------------
    mcp = FastMCP("vp-mcp-sim")
    print(">> MCP: registering tools...")

    TOOL_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {}

    if USE_HELPER and REGISTER_HELPER is not None:
        REGISTER_HELPER(mcp)

        # ✅ args 한 개만 받도록 + 검증 전에 입력 보정 호출
        async def call_mcp_tool(args: Dict[str, Any]) -> Dict[str, Any]:
            if SIM_IMPL and SIM_SCHEMA:
                # ✅ 통짜 프롬프트/템플릿 → attacker/victim.system 주입
                normalized = _coerce_input_legacy(args) if _coerce_input_legacy else args

                # ✅ 핵심: templates는 스키마에서 드랍될 수 있으니 validate "전"에 보관
                raw_templates = {}
                if isinstance(normalized, dict) and isinstance(normalized.get("templates"), dict):
                    raw_templates = cast(Dict[str, Any], normalized.get("templates") or {})

                def _run_sync() -> dict:
                    model = SIM_SCHEMA.model_validate(normalized)
                    # ✅ templates를 impl로 전달 (2-call planner/realizer 분리의 핵심)
                    try:
                        return SIM_IMPL(model, templates=raw_templates)
                    except TypeError:
                        # 혹시 impl 시그니처가 templates를 안 받는 빌드면 하위호환
                        return SIM_IMPL(model)
                return await anyio.to_thread.run_sync(_run_sync)

            raise HTTPException(
                status_code=501,
                detail="Simulation tool is not directly invokable via REST in this build."
            )

        TOOL_REGISTRY["sim.simulate_dialogue"] = call_mcp_tool

    else:
        # helper가 없으면 직접 FastMCP 툴 등록 + REST 재사용
        if SIM_IMPL is None or SIM_SCHEMA is None:
            raise RuntimeError(
                "simulate_dialogue_impl 또는 SimulationInput import 실패. "
                "helper도 구현도 없어서 서버를 시작할 수 없습니다."
            )

        @mcp.tool(
            name="sim.simulate_dialogue",
            description="공격자/피해자 LLM 교대턴 시뮬레이션 실행 후 로그 저장"
        )
        async def simulate_dialogue(arguments: dict) -> dict:
            # ✅ 검증 전에 입력 보정
            normalized = _coerce_input_legacy(arguments) if _coerce_input_legacy else arguments

            def _run_sync() -> dict:
                model = SIM_SCHEMA.model_validate(normalized)
                return SIM_IMPL(model)
            return await anyio.to_thread.run_sync(_run_sync)

        TOOL_REGISTRY["sim.simulate_dialogue"] = simulate_dialogue

    print(">> MCP: tools registered OK")

    # ----------------------------
    # 4) 메인 FastAPI 앱 + 라우트
    # ----------------------------
    app = FastAPI(title="VP MCP Server", version="0.2.2")

    @app.get("/")
    def info():
        return {"name": "vp-mcp-sim", "status": "ok", "endpoint": "/mcp/"}

    # FastMCP ASGI 앱 마운트 (MCP 프로토콜)
    mount_target = getattr(mcp, "app", None) or mcp.streamable_http_app()
    app.mount("/mcp", mount_target)

    # ---- ✅ REST: 범용 MCP 호출 (POST) ----
    @app.post("/mcp/call", tags=["MCP"])
    async def mcp_call(body: MCPCall):
        func = TOOL_REGISTRY.get(body.tool)
        if not func:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {body.tool}")
        return await func(body.args)
    
    @app.get("/api/cases/{case_id}/turns", tags=["Logs"])
    def api_get_turns(case_id: str, run: Optional[int] = Query(default=None, ge=1)):
        """
        Admin이 사용하는 엔드포인트:
        GET /api/cases/{case_id}/turns?run=1
        응답: {"case_id": "...", "run": 1, "turns": [ {role,text,meta}, ... ]}
        """
        try:
            # 문자열로 들어온 UUID를 그대로 넘겨도, ORM 필드가 UUID면 자동 캐스팅되는 경우가 많음
            # 혹시 엄격히 UUID가 필요하면: case_uuid = UUID(case_id)
            db: Session = SessionLocal()
            try:
                res = fetch_turns_json(db, case_id=case_id, run_no=run)  # case_id를 그대로 전달 (ORM이 str→UUID 캐스팅)
            finally:
                db.close()
            return res
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"대화 로그 조회 중 오류: {e}")


    # ---- ✅ REST: 시뮬레이션 전용 (POST) ----
    @app.post("/api/simulate", tags=["Simulation"])
    async def api_simulate(req: SimulateRequest):
        func = TOOL_REGISTRY.get("sim.simulate_dialogue")
        if not func:
            raise HTTPException(status_code=500, detail="Simulation tool is not registered.")

        # ✅ 여기서도 검증 전에 입력 보정(안전망)
        args = _coerce_input_legacy(req.arguments) if _coerce_input_legacy else req.arguments
        return await func(args)

    # (선택) 헬스체크
    @app.get("/mcp/health", tags=["MCP"])
    async def health():
        return {"ok": True}

    return app


app = build_app()

if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "5177"))
    uvicorn.run("vp_mcp.mcp_server.server:app", host=host, port=port, reload=True)
