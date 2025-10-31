# VP\app\services\agent\orchestrator_react.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional, Set, AsyncGenerator
from dataclasses import dataclass, field
import json
import re
import ast
from datetime import datetime

from sqlalchemy.orm import Session
from fastapi import HTTPException

from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.callbacks.base import BaseCallbackHandler

from app.services.llm_providers import agent_chat
from app.services.agent.tools_sim import make_sim_tools
from app.services.agent.tools_admin import make_admin_tools
from app.services.agent.tools_mcp import make_mcp_tools
from app.services.agent.tools_tavily import make_tavily_tools
from app.services.agent.guideline_repo_db import GuidelineRepoDB
from app.core.logging import get_logger

# 새 추가
from app.schemas.simulation_request import SimulationStartRequest
from app.services.prompt_integrator_db import build_prompt_package_from_payload

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# (SSE 추가) 전역 설정 / 헬퍼
# ─────────────────────────────────────────────────────────
# 서버가 guidance 키로 무엇을 기대하는지 고정 ("type" 또는 "kind")
EXPECT_GUIDANCE_KEY = "type"   # ← 서버가 kind를 요구하면 "kind"로 변경

# mcp.simulator_run은 Action Input 최상위 언랩을 사용
EXPECT_MCP_DATA_WRAPPER = False  # True면 {"data": {...}} 래핑, False면 언랩

# (SSE) 필요한 모듈
import asyncio, logging, uuid, contextvars, contextlib, sys
from threading import Event as ThreadEvent
from starlette.responses import StreamingResponse
from fastapi import APIRouter, status

# ── (고급 SSE) 스트림 상태: 루프, 메인 브로드캐스트 큐, 외부 구독자(sinks)
_StreamState = Tuple[asyncio.AbstractEventLoop, asyncio.Queue, Set[asyncio.Queue]]

_STREAMS: dict[str, _StreamState] = {}
_current_stream_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_current_stream_id", default=None)

_ACTIVE_STREAMS: Set[str] = set()
_ACTIVE_RUN_KEYS: Set[str] = set()

def _make_run_key(payload: Dict[str, Any]) -> str:
    """동일 입력(오퍼더/피해자/시나리오 프로필) 실행을 하나로 간주하는 키"""
    key = {
        "offender_id": payload.get("offender_id"),
        "victim_id": payload.get("victim_id"),
        # 시나리오/프로필은 식별자나 해시가 있으면 우선 사용
        "scenario": payload.get("scenario_id") or payload.get("scenario_hash") or payload.get("scenario"),
        "victim_profile": payload.get("victim_profile_id") or payload.get("victim_profile"),
    }
    try:
        return json.dumps(key, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(key)

def _ensure_stream(stream_id: str) -> _StreamState:
    state = _STREAMS.get(stream_id)
    if state is None:
        loop = asyncio.get_running_loop()
        main_q: asyncio.Queue = asyncio.Queue()
        sinks: Set[asyncio.Queue] = set()
        state = (loop, main_q, sinks)
        _STREAMS[stream_id] = state
    return state

def _get_loop(stream_id: str) -> asyncio.AbstractEventLoop:
    return _ensure_stream(stream_id)[0]

def _get_main_queue(stream_id: str) -> asyncio.Queue:
    return _ensure_stream(stream_id)[1]

def _get_sinks(stream_id: str) -> Set[asyncio.Queue]:
    return _ensure_stream(stream_id)[2]

def sse_current_stream_id() -> Optional[str]:
    """현재 실행 컨텍스트에 바인딩된 stream_id 반환 (없으면 None)"""
    return _current_stream_id.get()

async def register_sink_to_current_stream(sink_q: asyncio.Queue) -> bool:
    """외부(예: MCPController)에서 현재 스트림에 sink 큐를 구독자로 등록"""
    sid = _current_stream_id.get()
    if not sid:
        return False
    _get_sinks(sid).add(sink_q)
    return True

async def unregister_sink_from_current_stream(sink_q: asyncio.Queue) -> None:
    """현재 스트림에서 sink 큐 구독 해제"""
    sid = _current_stream_id.get()
    if not sid:
        return
    _get_sinks(sid).discard(sink_q)

async def _sse_event_generator(stream_id: str) -> AsyncGenerator[bytes, None]:
    loop, main_q, sinks = _ensure_stream(stream_id)

    async def heartbeat():
        while True:
            await asyncio.sleep(15)
            try:
                await main_q.put({"type": "heartbeat", "ts": datetime.now().isoformat()})
            except Exception:
                break

    async def fan_in_from_sinks():
        # 각 sink에서 들어오는 이벤트를 main_q로 합류
        while True:
            try:
                if not sinks:
                    await asyncio.sleep(0.1)
                    continue
                for sq in list(sinks):
                    try:
                        item = sq.get_nowait()
                    except asyncio.QueueEmpty:
                        continue
                    else:
                        await main_q.put({"type": "turn_event", "content": item, "ts": datetime.now().isoformat()})
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[SSE] fan_in_from_sinks error]")
                await asyncio.sleep(0.5)

    hb_task = asyncio.create_task(heartbeat())
    fanin_task = asyncio.create_task(fan_in_from_sinks())

    try:
        # 최초 핑
        await main_q.put({"type": "ping", "ts": datetime.now().isoformat(), "stream_id": stream_id})

        while True:
            msg = await main_q.get()
            payload = json.dumps(msg, ensure_ascii=False)
            yield f"data: {payload}\n\n".encode("utf-8")
    except asyncio.CancelledError:
        pass
    finally:
        for t in (hb_task, fanin_task):
            t.cancel()
        _STREAMS.pop(stream_id, None)

def _truncate(obj: Any, max_len: int = 800) -> Any:
    """긴 문자열을 로그용으로 안전하게 자르기"""
    try:
        if isinstance(obj, str):
            return (obj[:max_len] + "…") if len(obj) > max_len else obj
        if isinstance(obj, list):
            return [_truncate(x, max_len) for x in obj]
        if isinstance(obj, dict):
            return {k: _truncate(v, max_len) for k, v in obj.items()}
    except Exception:
        pass
    return obj

def _emit_to_stream(kind: str, content: Any):
    """스레드/쓰레드풀 어디서든 안전하게 현재 스트림으로 이벤트 emit"""
    stream_id = _current_stream_id.get()
    if not stream_id:
        return
    try:
        loop = _get_loop(stream_id)
        q = _get_main_queue(stream_id)
        ev = {"type": kind, "content": _truncate(content, 2000), "ts": datetime.now().isoformat()}
        loop.call_soon_threadsafe(q.put_nowait, ev)
    except Exception:
        pass
# ✅ run_end 전용 헬퍼(이유 메타 포함)
def _emit_run_end(reason: str, meta: Optional[Dict[str, Any]] = None):
    try:
        payload = {"reason": reason}
        if meta:
            payload.update(meta)
        _emit_to_stream("run_end", payload)
    except Exception:
        pass
class _LogToSSEHandler(logging.Handler):
    """이 모듈 logger로 찍히는 로그를 SSE로 복제 (방탄 처리)"""
    def emit(self, record: logging.LogRecord):
        try:
            # 1차: 포매터 시도
            try:
                text = self.format(record)
            except Exception:
                # 2차: 표준 로깅 방식 (msg % args 적용)
                try:
                    text = record.getMessage()
                except Exception:
                    # 3차: 최후 폴백
                    try:
                        text = str(record.msg)
                    except Exception:
                        text = "<log formatting failed>"
            if not isinstance(text, str):
                text = str(text)
            _emit_to_stream("log", text)
        except Exception:
            # 로깅 중 예외는 전체 흐름 막지 않음
            pass

_sse_log_handler = _LogToSSEHandler()
_sse_log_handler.setLevel(logging.INFO)
_sse_log_handler.setFormatter(logging.Formatter("%(message)s"))

# === (중요) LangChain/루트 로거에도 SSE 핸들러 부착/해제 (중복방지, 레벨 보정) ===
_LANGCHAIN_LOGGERS = [
    "langchain",
    "langchain_core",
    "langchain_community",
]
_ATTACHED_FLAG = "_sse_handler_attached"

def _attach_global_sse_logging_handlers():
    """루트/uvicorn/httpx + LangChain 계열 로거에 SSE 핸들러 부착(중복 방지)."""
    targets = [
        logging.getLogger(),                 # root
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("httpx"),
    ] + [logging.getLogger(n) for n in _LANGCHAIN_LOGGERS]

    for lg in targets:
        if not getattr(lg, _ATTACHED_FLAG, False):
            lg.addHandler(_sse_log_handler)
            # LangChain verbose를 SSE로 보려면 최소 INFO 권장
            try:
                if lg.level in (logging.NOTSET,) or lg.level > logging.INFO:
                    lg.setLevel(logging.INFO)
            except Exception:
                pass
            # 상위 전파 유지
            lg.propagate = True
            setattr(lg, _ATTACHED_FLAG, True)

def _detach_global_sse_logging_handlers():
    """부착했던 로거들에서 SSE 핸들러 제거."""
    targets = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("httpx"),
    ] + [logging.getLogger(n) for n in _LANGCHAIN_LOGGERS]

    for lg in targets:
        with contextlib.suppress(Exception):
            lg.removeHandler(_sse_log_handler)
        if getattr(lg, _ATTACHED_FLAG, False):
            with contextlib.suppress(Exception):
                delattr(lg, _ATTACHED_FLAG)

# (SSE) 라우터: /api/sse/agent/{stream_id}
router = APIRouter(prefix="/api/sse", tags=["sse"])

@router.get("/agent/{stream_id}")
async def sse_agent_stream(stream_id: str):
    return StreamingResponse(_sse_event_generator(stream_id), media_type="text/event-stream", status_code=status.HTTP_200_OK)

# ─────────────────────────────────────────────────────────
# ★ 콘솔 스트림 보장 + Tee 터미널 (콘솔 + SSE 동시 출력)
# ─────────────────────────────────────────────────────────
def _ensure_console_stream_handler():
    """루트 로거에 콘솔 StreamHandler가 없다면 하나 추가 (중복 안전)."""
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        # ❌ 기존: logging.Formatter("[%(levelname)s] %s %(name)s: %(message)s" % ("%Y-%m-%d %H:%M:%S"))
        # ✅ 수정:
        sh.setFormatter(logging.Formatter(
            "[%(levelname)s] %(asctime)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        root.addHandler(sh)

class TeeTerminal:
    """
    sys.stdout/sys.stderr를 Tee 방식으로 교체:
    - 원본 콘솔(sys.__stdout__/__stderr__) 에 그대로 출력
    - 동시에 현재 stream_id의 SSE main_q 로 'terminal' 이벤트 push
    """
    def __init__(self, stream_id: str, which: str = "stdout"):
        self.stream_id = stream_id
        self.which = which  # "stdout" | "stderr"
        self.orig = sys.__stdout__ if which == "stdout" else sys.__stderr__
        self.buffer = ""
        self.loop = _get_loop(stream_id)
        self.q = _get_main_queue(stream_id)

    def write(self, text: str):
        if not text:
            return
        # 1) 원본 콘솔로 그대로 내보내기
        try:
            self.orig.write(text)
            self.orig.flush()
        except Exception:
            pass

        # 2) SSE 쪽으로는 개행 단위로 나눠서 보냄
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.rstrip()
            if not line:
                continue
            msg = {"type": "terminal", "content": line, "ts": datetime.now().isoformat()}
            try:
                self.loop.call_soon_threadsafe(self.q.put_nowait, msg)
            except Exception:
                # SSE 실패는 콘솔만 찍히게 무시
                pass

    def flush(self):
        # 남은 버퍼 한 번 더 SSE로 내보내기
        if self.buffer.strip():
            msg = {"type": "terminal", "content": self.buffer.strip(), "ts": datetime.now().isoformat()}
            try:
                self.loop.call_soon_threadsafe(self.q.put_nowait, msg)
            except Exception:
                pass
            self.buffer = ""
        # 원본도 flush
        try:
            self.orig.flush()
        except Exception:
            pass

# ─────────────────────────────────────────────────────────
# JSON/파싱 유틸
# ─────────────────────────────────────────────────────────
def _extract_json_block(agent_result: Any) -> Dict[str, Any]:
    """툴 Observation에서 JSON 객체를 최대한 안전하게 추출."""
    try:
        if isinstance(agent_result, dict):
            maybe = agent_result.get("output") if "output" in agent_result else agent_result
            if isinstance(maybe, str) and maybe.strip().startswith("{"):
                return json.loads(maybe)
            if isinstance(maybe, dict):
                return maybe
        s = str(agent_result)
        m = re.search(r"\{.*\"phishing\".*\}", s, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return {}

def _extract_phishing_from_judgement(obj: Dict[str, Any]) -> bool:
    return bool(obj.get("phishing"))

def _extract_reason_from_judgement(obj: Dict[str, Any]) -> str:
    # reason 우선, 없으면 evidence 사용
    return (obj.get("reason") or obj.get("evidence") or "").strip()

def _extract_guidance_text(agent_result: Any) -> str:
    """지침 Observation에서 text 회수"""
    try:
        obj = _extract_json_block(agent_result)
        if isinstance(obj, dict):
            txt = obj.get("text") or (obj.get("guidance") or {}).get("text")
            if isinstance(txt, str):
                return txt.strip()
    except Exception:
        pass
    # fallback: 정규식
    try:
        s = str(agent_result)
        m = re.search(r"\{.*\"type\".*\"text\".*\}", s, re.S)
        if m:
            o = json.loads(m.group(0))
            return (o.get("text") or "").strip()
    except Exception:
        pass
    m2 = re.search(r"text['\"]\s*:\s*['\"]([^'\"]+)['\"]", str(agent_result))
    return m2.group(1).strip() if m2 else ""

def _safe_json(obj: Any) -> Dict[str, Any]:
    """dict면 그대로, 정확한 JSON 문자열이면 json.loads, 아니면 빈 dict."""
    if isinstance(obj, dict):
        return obj
    s = str(obj).strip()
    try:
        if s.startswith("{") and s.endswith("}"):
            return json.loads(s)
    except Exception:
        pass
    return {}

def _loose_parse_json(obj: Any) -> Dict[str, Any]:
    """JSON이 아니어도, python dict literal 문자열(작은따옴표) 등 느슨하게 파싱."""
    if isinstance(obj, dict):
        return obj
    s = str(obj).strip()
    # 1) 정확 JSON 시도
    j = _safe_json(s)
    if j:
        return j
    # 2) python literal 시도: {'ok': True, ...}
    try:
        if s.startswith("{") and s.endswith("}"):
            pyobj = ast.literal_eval(s)
            if isinstance(pyobj, dict):
                return pyobj
    except Exception:
        pass
    # 3) 본문 속에 dict가 섞여 있으면 가장 바깥 {} 뽑기
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        sub = m.group(0)
        j = _safe_json(sub)
        if j:
            return j
        try:
            pyobj = ast.literal_eval(sub)
            if isinstance(pyobj, dict):
                return pyobj
        except Exception:
            pass
    return {}

def _last_observation(cap: "ThoughtCapture", tool_name: str) -> Any:
    for ev in reversed(cap.events):
        if ev.get("type") == "observation" and ev.get("tool") == tool_name:
            return ev.get("output")
    return None

# ★ 추가: dict 보장(모델/dict/TypedDict까지 deep copy)
def _as_dict(x):
    import copy
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return copy.deepcopy(x)

# ★ 추가: guidance 정규화(문자열 방지, 키 통일, 값 검증)
def _normalize_guidance(g: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not g:
        return None
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except Exception:
            raise HTTPException(400, detail="guidance는 문자열이 아닌 객체(dict)여야 합니다.")
    g = dict(g)
    val = g.get("kind") or g.get("type")
    text = g.get("text", "")
    if val is None:
        raise HTTPException(400, detail="guidance.{kind|type} 누락")
    if val not in ("P", "A"):
        raise HTTPException(400, detail=f"guidance 값은 'P' 또는 'A' 여야 합니다. got={val}")
    return {EXPECT_GUIDANCE_KEY: val, "text": text}

# ★ 추가: payload 클린( None 제거 / forbid 대비 허용키만 유지 )
def _clean_payload(
    d: Dict[str, Any],
    *,
    allow_extras: bool = True,
    allowed_keys: Optional[List[str]] = None
) -> Dict[str, Any]:
    out = {k: v for k, v in d.items() if v is not None}
    if not allow_extras and allowed_keys is not None:
        out = {k: v for k, v in out.items() if k in allowed_keys}
    return out

# ★ 추가: mcp.simulator_run용 Action Input 생성기 (언랩/래핑 선택)
def _make_action_input_for_mcp(payload: Dict[str, Any]) -> str:
    if EXPECT_MCP_DATA_WRAPPER:
        return json.dumps({"data": payload}, ensure_ascii=False)
    else:
        return json.dumps(payload, ensure_ascii=False)

# ★ 추가: 래핑으로 넣어서 pydantic이 최상위 필드 missing이라 말할 때 탐지
def _looks_like_missing_top_fields_error(err_obj: Dict[str, Any]) -> bool:
    try:
        pes = err_obj.get("pydantic_errors") or []
        text = json.dumps(err_obj, ensure_ascii=False)
        has_data_literal = '"data":' in text or "'data':" in text
        miss_top = any(
            e.get("type") == "missing"
            and isinstance(e.get("loc"), list)
            and e["loc"][0] in ("offender_id", "victim_id", "scenario", "victim_profile")
            for e in pes
        )
        return has_data_literal and miss_top
    except Exception:
        return False

def _get_tool(executor: AgentExecutor, name: str):
    for t in executor.tools:
        if t.name == name:
            return t
    return None

# orchestrator_react.py
from app.db import models as m

def _ensure_admincase(db: Session, case_id: str, scenario_json: Dict[str, Any]) -> None:
    """라운드1에서 case_id 확정되자마자 AdminCase가 반드시 존재하도록 보장."""
    try:
        case = db.get(m.AdminCase, case_id)
        if not case:
            case = m.AdminCase(
                id=case_id,              # UUID 문자열이어도 SQLAlchemy가 캐스팅해줌
                scenario=scenario_json,  # build_prompt_package_from_payload 에서 받은 scenario
                phishing=False,
                status="running",
                defense_count=0,
            )
            db.add(case)
            created = True
        else:
            # 기존 레코드가 있으면 최소한 상태/시나리오만 보정
            if not case.scenario:
                case.scenario = scenario_json
            case.status = case.status or "running"
            created = False
        db.flush()
        db.commit()
        logger.info("[AdminCase upsert] case_id=%s | created=%s", case_id, created)
    except Exception as e:
        logger.warning(f"[AdminCase upsert] failed: {e}")

# ─────────────────────────────────────────────────────────
# LangChain 콜백: Thought/Action/Observation 캡처
# ─────────────────────────────────────────────────────────
@dataclass
class ThoughtCapture(BaseCallbackHandler):
    last_tool: Optional[str] = None
    last_tool_input: Optional[Any] = None
    events: list = field(default_factory=list)

    def on_agent_action(self, action, **kwargs):
        rec = {
            "type": "action",
            "tool": getattr(action, "tool", "?"),
            "tool_input": getattr(action, "tool_input", None),
        }
        self.last_tool = rec["tool"]
        self.last_tool_input = rec["tool_input"]
        self.events.append(rec)
        logger.info(
            "[AgentThought] Tool=%s | Input=%s",
            rec["tool"],
            _truncate(rec["tool_input"]),
        )
        # (SSE) 에이전트 액션 전달
        _emit_to_stream("agent_action", {"tool": rec["tool"], "input": rec["tool_input"]})

    def on_tool_end(self, output: Any, **kwargs):
        self.events.append({
            "type": "observation",
            "tool": self.last_tool,
            "output": output,
        })
        logger.info("[ToolObservation] Tool=%s | Output=%s", self.last_tool, _truncate(output, 1200))
        # (SSE) 툴 관찰 전달
        _emit_to_stream("tool_observation", {"tool": self.last_tool, "output": output})

    def on_agent_finish(self, finish, **kwargs):
        self.events.append({"type": "finish", "log": finish.log})
        logger.info("[AgentFinish] %s", _truncate(finish.log, 1200))
        # (SSE) 에이전트 종료 전달
        _emit_to_stream("agent_finish", {"log": getattr(finish, "log", "")})

# ─────────────────────────────────────────────────────────
# ★★★ ADDED: Smart Print (print → 로그 + SSE 동시 전송)
# ─────────────────────────────────────────────────────────
import builtins as _builtins

_ORIG_PRINT = _builtins.print

def _smart_print(*args, **kwargs):
    # 1) 원래 print 동작은 그대로 수행 (콘솔 + TeeTerminal → 'terminal' 이벤트 유지)
    _ORIG_PRINT(*args, **kwargs)

    # 2) 단일 인자(dict 또는 repr 문자열)일 때만 구조화 판별 → 로그+SSE
    try:
        if len(args) != 1:
            return
        obj = args[0]

        data = obj if isinstance(obj, dict) else _loose_parse_json(obj)
        if not isinstance(data, dict) or not data:
            return

        # 태그 판별
        tag = None
        # (1) mcp 대화로그
        if ("case_id" in data) and ("turns" in data) and ("stats" in data):
            tag = "conversation_log"
        # (2) judgement
        elif ("persisted" in data) and ("phishing" in data) and ("risk" in data):
            tag = "judgement"
        # (3) guidance
        elif ("type" in data) and ("text" in data) and (("categories" in data) or ("targets" in data)):
            tag = "guidance"
        # (4) prevention
        elif ("personalized_prevention" in data):
            tag = "prevention"

        if tag:
            safe = _truncate(data, 2000)
            logger.info("[%s] %s", tag, json.dumps(safe, ensure_ascii=False))
            _emit_to_stream(tag, safe)
    except Exception:
        # 로깅 중 예외는 전체 흐름 막지 않음
        pass

def _patch_print():
    if getattr(_builtins, "_smart_print_patched", False):
        return
    _builtins.print = _smart_print
    setattr(_builtins, "_smart_print_patched", True)

def _unpatch_print():
    if getattr(_builtins, "_smart_print_patched", False):
        _builtins.print = _ORIG_PRINT
        try:
            delattr(_builtins, "_smart_print_patched")
        except Exception:
            pass

# ─────────────────────────────────────────────────────────
# ReAct 시스템 프롬프트 (프롬프트는 요청대로 그대로 유지)
# ─────────────────────────────────────────────────────────
REACT_SYS = (
    "당신은 보이스피싱 시뮬레이션 오케스트레이터입니다.\n"
    "오직 제공된 도구만 사용하여 작업하세요. (직접 결과를 쓰거나 요약으로 때우지 말 것)\n"
    "\n"
    "▼ 용어 정의\n"
    "• 케이스(case): 전체 시뮬레이션 1회. 고유 CASE_ID를 가짐.\n"
    "• 라운드(round): 케이스 안의 한 사이클(1~5).\n"
    "• 턴(turn): 라운드 안에서의 대화 교환 단위.\n"
    "\n"
    "▼ 도구 사용 원칙\n"
    "• 주어진 \"도구 이름 목록\"에 없는 도구는 절대 호출하지 않는다. (이름이 비슷해도 호출 금지)\n"
    "• 한 단계가 실패하면, 같은 잘못된 입력을 반복하지 말고 사유를 점검한 뒤 올바른 입력으로 재호출한다.\n"
    "• ★ 각 단계에서 명시된 도구 외에는 절대 호출하지 말 것. (특히 admin.make_prevention 은 케이스 종료 시 단 1회만 허용)\n"
    "\n"
    "▼ 전체 사이클 규칙\n"
    "  [라운드1]\n"
    "    1) sim.fetch_entities 로 시나리오/피해자 정보를 확보한다.\n"
    "    2) sim.compose_prompts 를 호출한다. (★ guidance 금지)\n"
    "    3) mcp.simulator_run 을 실행한다. (★ guidance 금지)\n"
    "    4) admin.make_judgement 를 호출해 **판정/리스크/취약성/계속여부**를 생성한다.\n"
    "       └ 이때 (case_id, run_no)만 보내지 말고, 반드시 방금 mcp.simulator_run Observation에서 받은\n"
    "          {{\"turns\": [...]}} 또는 {{\"log\": {{\"turns\": [...]}}}} 를 함께 전달한다.\n"
    "    5) (라운드가 2 이상인 경우에만) admin.generate_guidance 로 다음 라운드 지침을 생성한다.\n"
    "       └ 호출 전, 직전 admin.make_judgement 응답의 **persisted==true**를 확인한다.\n"
    "\n"
    "  [라운드2~N]\n"
    "    6) admin.generate_guidance 로 다음 라운드 지침을 만든다. (type='P' 또는 'A')\n"
    "       └ 매핑 규칙: 직전 판정에서 phishing==true → 'P'(Protect), phishing==false → 'A'(Attack)\n"
    "       └ 입력은 저장된 판정이 존재한다는 전제하에 진행한다. (persisted 확인 필수)\n"
    "    7) mcp.simulator_run 을 다시 실행하되 아래 조건을 반드시 지킨다:\n"
    "       • case_id_override = (라운드1에서 획득한 case_id)\n"
    "       • round_no = 현재 라운드 번호 (정수)\n"
    "       • guidance = {{\"type\": \"P\"|\"A\", \"text\": \"...\"}} 만 포함\n"
    "    8) admin.make_judgement 로 해당 라운드 판정을 생성하고 저장한다.\n"
    "\n"
    "▼ 판정 저장 규칙 (매우 중요)\n"
    "  • admin.make_judgement 호출 후 응답에서 persisted 필드를 확인한다.\n"
    "    - persisted == true → 다음 단계 진행\n"
    "    - persisted == false → 동일 payload로 admin.make_judgement 를 1회 재호출하여 저장을 보장한 후 진행\n"
    "\n"
    "▼ 하드 제약 (어기면 안 됨)\n"
    "  • 1라운드에는 guidance를 어느 도구에도 넣지 않는다.\n"
    "  • 2라운드부터 guidance는 오직 mcp.simulator_run.arguments.guidance 로만 전달한다.\n"
    "  • offender_id / victim_id / scenario / victim_profile / templates 는 라운드 간 불변. (값 변경 금지)\n"
    "  • 동일 case_id 유지: 라운드1에서 받은 case_id 를 2라운드부터 case_id_override 로 반드시 넣는다.\n"
    "  • round_no 는 2부터 1씩 증가하는 정수로 설정한다.\n"
    "  • ★ admin.make_prevention 은 오직 케이스 종료 조건(risk.level=='critical' 또는 round_no==5) 충족 시 단 1회만 호출 가능.\n"
    "  • ★ 케이스 진행 중(=라운드 진행 중)에 admin.make_prevention 을 호출하면 즉시 실패로 간주한다.\n"
    "\n"
    "▼ 도구별 Action Input 규칙\n"
    "  • [mcp.simulator_run] Action Input은 **최상위 언랩 JSON**이다. (예: {{\"offender_id\":..., \"victim_id\":..., ...}})\n"
    "    절대 'data'로 감싸지 말 것.\n"
    "  • [admin.* / sim.*] Action Input은 **{{\"data\": {{...}}}} 래핑**을 사용한다.\n"
    "\n"
    "▼ 종료/마무리 규칙\n"
    "  • 케이스 종료 조건은 오직 두 가지뿐이다:\n"
    "    (1) 마지막 판정의 risk.level == 'critical'\n"
    "    (2) 현재 round_no == max_rounds(기본 5)\n"
    "  • 위 케이스 종료 조건 중 하나라도 만족할 때에만 Final Answer 와 admin.make_prevention 을 실행한다.\n"
    "  • 케이스가 종료되면 **오직 한 번만** admin.make_prevention 을 호출하여 최종 예방책을 생성한다.\n"
    "    입력에는 누적된 대화 {{\"turns\": [...]}} , 각 라운드 판정 목록 {{\"judgements\": [...]}} , 실제 적용된 지침 목록 {{\"guidances\": [...]}} 를 넣고,\n"
    "    지정 스키마(personalized_prevention)의 JSON만 반환하도록 한다.\n"
    "  • 케이스 진행 중(=라운드 진행 중)이나 종료 조건 미충족 상태에서는 admin.make_prevention 호출 금지.\n"
    "\n"
    "▼ 오류/예외 복구 규칙\n"
    "  • 라운드1에서 case_id 추출 실패 → mcp.latest_case(offender_id, victim_id) 로 복구.\n"
    "  • 도구가 JSON 파싱 오류를 반환하면, 같은 JSON을 그대로 재시도하지 말고 스키마(언랩 vs 'data' 래핑)를 점검 후 올바른 형식으로 재호출.\n"
    "  • 동일 (case_id, run, turn_index) 중복 오류 → round_no 설정을 재검토하고 수정.\n"
    "\n"
    "▼ 출력 포맷 (반드시 준수)\n"
    "  Thought: 현재 판단/계획(간결히)\n"
    "  Action: [사용할_도구_이름]\n"
    "  Action Input: (툴별 규칙을 따른 JSON 한 줄)\n"
    "  Observation: 도구 출력\n"
    "  ... 필요시 반복 ...\n"
    "  Final Answer: 최종 요약(최종 case_id, 총 라운드 수, 각 라운드 판정 요약 포함)\n"
)

def build_agent_and_tools(db: Session, use_tavily: bool) -> Tuple[AgentExecutor, Any]:
    llm = agent_chat(temperature=0.2)
    logger.info("[AgentLLM] model=%s", getattr(llm, "model_name", "unknown"))

    tools: List = []
    tools += make_sim_tools(db)

    mcp_res = make_mcp_tools()
    if isinstance(mcp_res, tuple):
        mcp_tools, mcp_manager = mcp_res
    else:
        mcp_tools, mcp_manager = mcp_res, None
    tools += mcp_tools

    tools += make_admin_tools(db, GuidelineRepoDB(db))
    if use_tavily:
        tools += make_tavily_tools()

    logger.info("[Agent] TOOLS REGISTERED: %s", [t.name for t in tools])

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", REACT_SYS),
            (
                "human",
                "사용 가능한 도구들:\n{tools}\n\n"
                "도구 이름 목록: {tool_names}\n\n"
                "아래 포맷을 정확히 따르세요. 포맷 외 임의 텍스트/코드펜스/주석 금지.\n"
                "Thought: 한 줄\n"
                "Action: 도구이름  (예: mcp.simulator_run)\n"
                "Action Input: (툴별 규칙)\n"
                "Observation: (도구 출력)\n"
                "... 반복 ...\n"
                "Final Answer: 결론\n\n"
                "입력:\n{input}\n\n"
                "{agent_scratchpad}",
            ),
        ]
    )

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    ex = AgentExecutor(
        agent=agent, tools=tools, verbose=True, handle_parsing_errors=True, max_iterations=30
    )
    return ex, mcp_manager

# ─────────────────────────────────────────────────────────
# 메인 오케스트레이션
# ─────────────────────────────────────────────────────────
def run_orchestrated(db: Session, payload: Dict[str, Any], _stop: Optional[ThreadEvent] = None) -> Dict[str, Any]:
    # (SSE) 스트림 컨텍스트 시작: 프론트가 전달한 stream_id 사용(없으면 내부 생성)
    stream_id = str(payload.get("stream_id") or uuid.uuid4())

    run_key = _make_run_key(payload)
    if run_key in _ACTIVE_RUN_KEYS:
        raise HTTPException(status_code=409, detail="duplicated simulation run detected")
    # stream_id는 “실행”의 유일키가 아닙니다. 연결이 여러 개일 수 있으므로 여기선 추적하지 않음.
    _ACTIVE_RUN_KEYS.add(run_key)

    token = _current_stream_id.set(stream_id)

    # (고급 SSE) 전역/외부 로거 핸들러 부착
    logger.addHandler(_sse_log_handler)
    _attach_global_sse_logging_handlers()

    # 콘솔 스트림 보장(중복 안전)
    _ensure_console_stream_handler()

    # ★★★ ADDED: Smart Print 활성화 (print → 로그+SSE 동시 송출)
    _patch_print()

    # ✅ 터미널 Tee: 콘솔에도 찍고, SSE로도 보냄
    tee_out = TeeTerminal(stream_id, "stdout")
    tee_err = TeeTerminal(stream_id, "stderr")

    _emit_to_stream("run_start", {"stream_id": stream_id, "payload_hint": _truncate(payload, 400)})

    req = None
    ex = None
    mcp_manager = None
    _emitted_run_end = False  # run_end 중복 방지 플래그

    try:
        # 즉시 중단 체크(라우터에서 이미 stop 신호가 온 경우)
        if _stop and _stop.is_set():
            return {"status": "cancelled"}
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            req = SimulationStartRequest(**payload)
            ex, mcp_manager = build_agent_and_tools(db, use_tavily=req.use_tavily)

            cap = ThoughtCapture()
            used_tools: List[str] = []
            tavily_used = False
            rounds_done = 0
            case_id = ""

            # ★ 누적용 컨테이너 (최종예방책 1회 생성을 위해)
            guidance_history: List[Dict[str, Any]] = []
            judgements_history: List[Dict[str, Any]] = []
            turns_all: List[Dict[str, str]] = []
            prevention_created: bool = False   # 중복 예방책 생성/저장 방지
            prevention_obj: Dict[str, Any] = {}  # 반환용
            finished_reason: Optional[str] = None  # "critical" | "rounds_exhausted"

            # 1) 프롬프트 패키지 (DB 조립)
            pkg = build_prompt_package_from_payload(
                db, req, tavily_result=None, is_first_run=True, skip_catalog_write=True
            )
            scenario = pkg["scenario"]
            victim_profile = pkg["victim_profile"]
            templates = pkg["templates"]

            # 입력/패키지 스냅샷
            logger.info("[InitialInput] %s", json.dumps(_truncate(payload), ensure_ascii=False))
            logger.info("[ComposedPromptPackage] %s", json.dumps(_truncate(pkg), ensure_ascii=False))

            offender_id = int(req.offender_id or 0)
            victim_id = int(req.victim_id or 0)

            # 라운드 정책: 최소 2, 최대 req.round_limit(기본 5). 종료는 오직 critical 또는 max_rounds 도달 시.
            min_rounds = 2
            try:
                max_rounds = int(getattr(req, "round_limit", 5) or 5)
            except Exception:
                max_rounds = 5
            if max_rounds < min_rounds:
                max_rounds = min_rounds

            guidance_kind: Optional[str] = None
            guidance_text: Optional[str] = None

            # dict 보장
            scenario_base = _as_dict(scenario)
            victim_profile_base = _as_dict(victim_profile)
            templates_base = _as_dict(templates)

            base_payload: Dict[str, Any] = {
                "offender_id": offender_id,
                "victim_id": victim_id,
                "scenario": scenario_base,
                "victim_profile": victim_profile_base,
                "templates": templates_base,  # 스키마에 없다면 allowed_keys에서 제거
                "max_turns": req.max_turns,
            }

            # ★★ added: sim.compose_prompts 직접 호출 헬퍼
            def _compose_prompts_for_round(
                round_no: int,
                scenario: Dict[str, Any],
                victim_profile: Dict[str, Any],
                guidance: Optional[Dict[str, Any]],
                case_id_for_round: Optional[str],
            ) -> Dict[str, str]:
                tool = None
                for t in ex.tools:
                    if t.name == "sim.compose_prompts":
                        tool = t
                        break
                if not tool:
                    raise HTTPException(status_code=500, detail="sim.compose_prompts tool not registered")

                payload_obj = {
                    "scenario": scenario,
                    "victim_profile": victim_profile,
                    "round_no": round_no,
                }
                if guidance:
                    payload_obj["guidance"] = guidance
                if case_id_for_round:
                    payload_obj["case_id"] = case_id_for_round

                # sim.* 계열은 {"data": {...}} 래핑 규칙
                res_cp = tool.invoke({"data": payload_obj})
                if isinstance(res_cp, str):
                    try:
                        res_cp = json.loads(res_cp)
                    except Exception:
                        res_cp = {}
                if not isinstance(res_cp, dict):
                    raise HTTPException(status_code=500, detail="sim.compose_prompts returned non-dict")

                return res_cp

            for round_no in range(1, max_rounds + 1):
                # 라운드 시작 시 중단 체크
                if _stop and _stop.is_set():
                    logger.info("[StopToken] client_disconnected → stop at round=%s", round_no)
                    return {"status": "cancelled", "case_id": case_id or "", "rounds": rounds_done}

                # ★★ added: 이번 라운드용 guidance 준비 (2라운드 이상일 때만)
                round_guidance = None
                if round_no >= 2 and guidance_kind and guidance_text:
                    round_guidance = {"type": guidance_kind, "text": guidance_text}

                # ★★ added: 이번 라운드용 prompt.py 기반 프롬프트 생성
                composed_prompts = _compose_prompts_for_round(
                    round_no=round_no,
                    scenario=scenario_base,
                    victim_profile=victim_profile_base,
                    guidance=round_guidance,
                    case_id_for_round=case_id if round_no >= 2 else None,
                )
                logger.info("[ComposePrompts] round=%s guidance=%s", round_no, round_guidance)
                attacker_prompt = composed_prompts.get("attacker_prompt")
                victim_prompt = composed_prompts.get("victim_prompt")
                if not attacker_prompt or not victim_prompt:
                    logger.error("[ComposePrompts] round=%s 프롬프트 생성 실패", round_no)
                    raise HTTPException(status_code=500, detail="sim.compose_prompts failed to return prompts")

                # ---- (A) 시뮬레이션 실행 ----
                sim_payload: Dict[str, Any] = dict(base_payload)

                if round_no >= 2:
                    if not case_id:
                        logger.error("round>=2 인데 case_id가 없습니다. 라운드1 결과 저장/파싱 확인 요망.")
                        raise HTTPException(status_code=500, detail="missing case_id for subsequent rounds")
                    sim_payload.update({
                        "case_id_override": case_id,
                        "round_no": round_no,
                    })
                    if guidance_kind and guidance_text:
                        normalized = _normalize_guidance({"type": guidance_kind, "text": guidance_text})
                        sim_payload["guidance"] = normalized
                        # ★ 실제 적용된 지침(해당 라운드 번호)에 대해서만 히스토리 기록
                        guidance_history.append({
                            "run_no": round_no,
                            "kind": normalized.get(EXPECT_GUIDANCE_KEY),
                            "text": normalized.get("text", "")
                        })

                # ★★ added: 이번 라운드에서 만든 프롬프트를 실 payload에 직접 태운다
                sim_payload["attacker_prompt"] = attacker_prompt
                sim_payload["victim_prompt"] = victim_prompt
                logger.info(
                    "[SimPayloadPrompt] round=%s | attacker_head=%s",
                    round_no,
                    (attacker_prompt or "")[:160],
                )

                # forbid 대비: 허용키만 유지 + None 제거
                allowed_keys = [
                    "offender_id","victim_id","scenario","victim_profile",
                    "attacker_prompt","victim_prompt",  # ★★ added
                    "templates","max_turns",
                    "case_id_override","round_no","guidance"
                ]
                sim_payload = _clean_payload(sim_payload, allow_extras=False, allowed_keys=allowed_keys)

                # 스냅샷 로그
                snapshot = {
                    "round_no": round_no,
                    "offender_id": sim_payload.get("offender_id"),
                    "victim_id": sim_payload.get("victim_id"),
                    "case_id_override": sim_payload.get("case_id_override"),
                    "round_no_field": sim_payload.get("round_no"),
                    "guidance": sim_payload.get("guidance"),
                    "scenario": sim_payload.get("scenario"),
                    "victim_profile": sim_payload.get("victim_profile"),
                    "attacker_prompt": (attacker_prompt[:120] + "…") if len(attacker_prompt or "") > 120 else attacker_prompt,
                    "victim_prompt":   (victim_prompt[:120] + "…")   if len(victim_prompt   or "") > 120 else victim_prompt,
                    "templates": {
                        "attacker": sim_payload.get("templates", {}).get("attacker", ""),
                        "victim": sim_payload.get("templates", {}).get("victim", ""),
                    } if "templates" in sim_payload else {},
                    "max_turns": sim_payload.get("max_turns"),
                }
                logger.info("[PromptSnapshot] %s", json.dumps(_truncate(snapshot), ensure_ascii=False))

                # 필수키 점검
                required = ["offender_id","victim_id","scenario","victim_profile","max_turns"]
                missing = [k for k in required if k not in sim_payload]
                if missing:
                    logger.error("[mcp.simulator_run] missing base keys: %s | sim_payload=%s",
                                missing, json.dumps(sim_payload, ensure_ascii=False)[:800])
                    raise HTTPException(status_code=500, detail=f"sim payload missing: {missing}")

                # ====== mcp.simulator_run 호출 (언랩 우선) ======
                def _parsed_agent_input(x):
                    from json import JSONDecoder
                    if isinstance(x, str):
                        try:
                            return JSONDecoder().raw_decode(x.strip())[0]
                        except Exception:
                            return x
                    return x

                def _invoke_mcp_simulator_via_agent(action_input: str):
                    llm_call = {
                        "input": (
                            "아래 JSON이 **Action Input 전체**다. 이 JSON을 그대로 사용하고, "
                            "추가/변형 금지. 반드시 아래 JSON 한 줄만 출력하라.\n"
                            "Action: mcp.simulator_run\n"
                            f"Action Input: {action_input}"
                        )
                    }
                    # 중단 체크 후 LLM/툴 호출
                    if _stop and _stop.is_set():
                        raise HTTPException(status_code=499, detail="client_disconnected")
                    res = ex.invoke(llm_call, callbacks=[cap])
                    used_tools.append("mcp.simulator_run")
                    return res

                # 언랩/래핑 설정에 맞춰 Action Input 생성
                action_input_json = _make_action_input_for_mcp(sim_payload)

                # 1차 호출 (에이전트 경유)
                res_run = _invoke_mcp_simulator_via_agent(action_input_json)

                # 도구 입력 불일치시 1회 재시도(그대로 다시)
                if cap.last_tool == "mcp.simulator_run":
                    try:
                        agent_input = _parsed_agent_input(cap.last_tool_input)
                        intended = json.loads(action_input_json)
                        if agent_input != intended:
                            logger.warning(
                                "[ToolInputMismatch] intended!=actual | intended=%s | actual=%s",
                                json.dumps(_truncate(intended), ensure_ascii=False),
                                json.dumps(_truncate(agent_input), ensure_ascii=False),
                            )
                            res_run = _invoke_mcp_simulator_via_agent(action_input_json)
                            used_tools.append("mcp.simulator_run(retry)")
                    except Exception as e:
                        logger.warning("[ToolInputCheckError] %s", e)

                # Observation 파싱
                sim_obs = _last_observation(cap, "mcp.simulator_run")
                sim_dict = _loose_parse_json(sim_obs)

                # (1) 휴리스틱 기반 1차 폴백
                bad_top = _looks_like_missing_top_fields_error(sim_dict)
                sent_wrapped = (cap.last_tool_input == {"data": sim_payload})
                if (not sim_dict.get("ok") and bad_top) or sent_wrapped:
                    logger.warning("[MCPFallback] agent가 data 래핑 또는 top-level missing → 툴 직접 호출(언랩)")
                    tool = _get_tool(ex, "mcp.simulator_run")
                    if not tool:
                        raise HTTPException(500, detail="mcp.simulator_run tool not found")
                    if _stop and _stop.is_set():
                        raise HTTPException(status_code=499, detail="client_disconnected")
                    tool_res = tool.invoke(sim_payload)  # 언랩 직접 호출
                    sim_dict = _loose_parse_json(tool_res)

                # (2) 반대 형태 재시도
                if not sim_dict.get("ok"):
                    _emit_to_stream("debug", {"where": "mcp.simulator_run", "hint": "first_shape_failed_try_opposite"})
                    tool = _get_tool(ex, "mcp.simulator_run")
                    if not tool:
                        raise HTTPException(500, detail="mcp.simulator_run tool not found")

                    try:
                        if _stop and _stop.is_set():
                            raise HTTPException(status_code=499, detail="client_disconnected")
                        if EXPECT_MCP_DATA_WRAPPER:
                            tool_res2 = tool.invoke(_clean_payload(sim_payload, allow_extras=False, allowed_keys=list(sim_payload.keys())))
                        else:
                            tool_res2 = tool.invoke({"data": sim_payload})

                        sim_dict2 = _loose_parse_json(tool_res2)
                        _emit_to_stream("tool_observation", {"tool": "mcp.simulator_run(retry-opposite)", "output": _truncate(sim_dict2, 1000)})

                        if sim_dict2.get("ok"):
                            sim_dict = sim_dict2
                        else:
                            _emit_to_stream("debug", {
                                "where": "mcp.simulator_run",
                                "retry_opposite_failed": True,
                                "first_shape": "wrapped" if EXPECT_MCP_DATA_WRAPPER else "unwrapped",
                                "second_shape": "unwrapped" if EXPECT_MCP_DATA_WRAPPER else "wrapped",
                                "err_first": _truncate(sim_dict, 800),
                                "err_second": _truncate(sim_dict2, 800),
                            })
                    except Exception as e:
                        _emit_to_stream("debug", {"where": "mcp.simulator_run", "retry_opposite_exception": str(e)})

                # 최종 실패 처리
                if not sim_dict.get("ok"):
                    logger.error(
                        "[SimulatorRunFail] error=%s | payload=%s",
                        _truncate(sim_dict, 800),
                        json.dumps(sim_payload, ensure_ascii=False),
                    )
                    _emit_to_stream("error", {"where": "mcp.simulator_run", "error": _truncate(sim_dict, 800)})
                    raise HTTPException(status_code=500, detail=f"simulator_run failed: {sim_dict.get('error') or 'unknown'}")

                # case_id 확정/검증
                if round_no == 1:
                    case_id = str(sim_dict.get("case_id") or "")
                    if not case_id:
                        logger.error("[CaseID] 라운드1 case_id 추출 실패 | obs=%s", _truncate(sim_dict))
                        raise HTTPException(status_code=500, detail="case_id 추출 실패(라운드1)")
                    _ensure_admincase(db, case_id, scenario_base)
                else:
                    got = str(sim_dict.get("case_id") or "")
                    if got and got != case_id:
                        logger.warning("[CaseID] 이어달리기 불일치 감지: expected=%s, got=%s", case_id, got)

                rounds_done += 1

                # 판정용 turns 확보 및 누적
                turns = sim_dict.get("turns") or (sim_dict.get("log") or {}).get("turns") or []
                ended_by = sim_dict.get("ended_by")
                stats = sim_dict.get("stats") or {}
                try:
                    round_row = (
                        db.query(m.ConversationRound)
                        .filter(m.ConversationRound.case_id == case_id,
                                m.ConversationRound.run == round_no)
                        .first()
                    )
                    if not round_row:
                        round_row = m.ConversationRound(
                            case_id=case_id,
                            run=round_no,
                            offender_id=offender_id,
                            victim_id=victim_id,
                            turns=turns,
                            ended_by=ended_by,
                            stats=stats,
                        )
                        db.add(round_row)
                    else:
                        round_row.turns = turns
                        round_row.ended_by = ended_by
                        round_row.stats = stats

                    db.commit()
                except Exception as e:
                    logger.warning(f"[DB] save conversation_round failed: {e}")
                logger.info("[SIM] case_id=%s turns=%s ended_by=%s",
                            sim_dict.get("case_id"), len(turns), sim_dict.get("ended_by"))
                if isinstance(turns, list):
                    turns_all.extend(turns)

                # ── (B) 판정 생성 ──
                make_payload = {
                    "data": {
                        "case_id": case_id,
                        "run_no": round_no,
                        "turns": turns
                    }
                }
                if _stop and _stop.is_set():
                    raise HTTPException(status_code=499, detail="client_disconnected")
                res_make = ex.invoke(
                    {"input": "admin.make_judgement 호출.\n" + json.dumps(make_payload, ensure_ascii=False)},
                    callbacks=[cap],
                )
                used_tools.append("admin.make_judgement")

                judge_obs = _last_observation(cap, "admin.make_judgement")
                judgement = _loose_parse_json(judge_obs) or _loose_parse_json(res_make)
                if not judgement:
                    for ev in reversed(cap.events):
                        if ev.get("type") == "observation":
                            cand = _loose_parse_json(ev.get("output"))
                            if isinstance(cand, dict) and ("phishing" in cand or "risk" in cand):
                                judgement = cand
                                break
                if not judgement:
                    logger.error(
                        "[JudgementParse] 판정 JSON 추출 실패 | obs=%s | res=%s",
                        _truncate(judge_obs),
                        _truncate(res_make),
                    )
                    raise HTTPException(status_code=500, detail="판정 JSON 추출 실패(admin.make_judgement)")

                # 기본 파생 필드 계산
                phishing = _extract_phishing_from_judgement(judgement)
                reason = _extract_reason_from_judgement(judgement)
                risk_obj = judgement.get("risk") or {}
                risk_lvl = (risk_obj.get("level") or "").lower()  # low|medium|high|critical
                risk_scr = int(risk_obj.get("score") or 0)
                cont_obj = judgement.get("continue") or {}
                cont_rec = (cont_obj.get("recommendation") or "").lower()  # continue|stop
                cont_msg = cont_obj.get("reason") or ""

                # ★★★ persisted 게이트: persisted=false면 동일 payload로 MAKE_JUDGEMENT 1회 재호출
                persisted = bool(judgement.get("persisted"))
                if not persisted:
                    logger.info("[PersistGuard] persisted==false → admin.make_judgement 재호출")
                    if _stop and _stop.is_set():
                        raise HTTPException(status_code=499, detail="client_disconnected")
                    res_make2 = ex.invoke(
                        {"input": "admin.make_judgement 호출(재시도).\n" + json.dumps(make_payload, ensure_ascii=False)},
                        callbacks=[cap],
                    )
                    used_tools.append("admin.make_judgement(retry)")

                    judge_obs2 = _last_observation(cap, "admin.make_judgement")
                    judgement2 = _loose_parse_json(judge_obs2) or _loose_parse_json(res_make2)
                    if not judgement2:
                        logger.error("[JudgementParse] 재시도 판정 JSON 추출 실패 | obs=%s | res=%s",
                                     _truncate(judge_obs2), _truncate(res_make2))
                        raise HTTPException(status_code=500, detail="판정 저장 실패(admin.make_judgement 재호출)")

                    if not bool(judgement2.get("persisted")):
                        logger.error("[PersistGuard] 재시도 후에도 persisted=false | judgement=%s", _truncate(judgement2))
                        raise HTTPException(status_code=500, detail="persisted=false: 판정 저장 실패")

                    # 최신 판정으로 교체 + 파생 필드 재계산
                    judgement = judgement2
                    phishing = _extract_phishing_from_judgement(judgement)
                    reason = _extract_reason_from_judgement(judgement)
                    risk_obj = judgement.get("risk") or {}
                    risk_lvl = (risk_obj.get("level") or "").lower()
                    risk_scr = int(risk_obj.get("score") or 0)
                    cont_obj = judgement.get("continue") or {}
                    cont_rec = (cont_obj.get("recommendation") or "").lower()
                    cont_msg = cont_obj.get("reason") or ""

                logger.info(
                    "[Judgement] round=%s | phishing=%s | risk=%s(%s) | continue=%s (%s) | persisted=%s",
                    round_no, phishing, risk_lvl, risk_scr, cont_rec, _truncate(cont_msg, 200), bool(judgement.get("persisted")),
                )

                # ── (B-2) 판정 히스토리 누적 ── (persisted 보장 후에만 기록)
                judgements_history.append({
                    "run_no": round_no,
                    "phishing": phishing,
                    "risk": risk_obj,
                    "evidence": judgement.get("evidence") or reason
                })

                # ── (C) 종료 조건: critical / 최대라운드 ──
                stop_on_critical = (risk_lvl == "critical")
                hit_round5       = (round_no >= max_rounds)  # max_rounds 기준
                will_stop_now = (stop_on_critical or hit_round5)

                if will_stop_now:
                    finished_reason = "critical" if stop_on_critical else "rounds_exhausted"
                    logger.info("[StopCondition] 종료 | reason=%s | round=%s", finished_reason, round_no)
                    # 예방책은 루프 밖 (F) 게이트에서 단 한 번 생성
                    break

                # ── (D) 다음 라운드를 위한 지침 생성 ──
                if round_no < max_rounds:
                    # 보수적 가드: persisted=false 상태에서 지침 생성 금지
                    if not bool(judgement.get("persisted")):
                        logger.error("[GuidanceGuard] persisted=false 상태에서 guidance 생성 시도 차단")
                        raise HTTPException(status_code=500, detail="persisted=false: guidance 생성 금지")

                    guidance_kind = "P" if phishing else "A"
                    logger.info("[GuidanceKind] round=%s | phishing=%s | kind=%s", round_no, phishing, guidance_kind)

                    gen_payload = {
                        "data": {
                            "case_id": case_id,
                            "run_no": round_no,
                            "scenario": scenario_base,
                            "victim_profile": victim_profile_base,
                            "previous_judgements": judgements_history
                        }
                    }
                    if _stop and _stop.is_set():
                        raise HTTPException(status_code=499, detail="client_disconnected")
                    res_gen = ex.invoke(
                        {"input": "admin.generate_guidance 호출.\n" + json.dumps(gen_payload, ensure_ascii=False)},
                        callbacks=[cap],
                    )
                    used_tools.append("admin.generate_guidance")

                    # Observation 기반으로 지침 텍스트 뽑기 (다음 라운드 적용 예정)
                    gen_obs = _last_observation(cap, "admin.generate_guidance")
                    guidance_text = _extract_guidance_text(gen_obs) or _extract_guidance_text(res_gen) or "기본 예방 수칙을 따르세요."
                    logger.info("[GuidancePicked] round=%s | kind=%s | text=%s", round_no, guidance_kind, _truncate(guidance_text, 300))
                    logger.info("[GuidanceSavedForNextRound] will_use_on_round=%s -> {%s, %s}",
                            round_no + 1, guidance_kind, guidance_text)

            # ---- (F) 최종예방책: 모든 라운드 종료 후 단 한 번 호출 ----
            logger.info("[LoopSummary] rounds_done=%s max_rounds=%s finished_reason=%s", rounds_done, max_rounds, finished_reason)

            if not prevention_created:
                # critical 또는 최대 라운드 소진으로 종료된 경우에만 실행
                if finished_reason not in ("critical", "rounds_exhausted"):
                    logger.warning("[PreventionGuard] finished_reason 없음 → 예방책 생성 스킵 (중간 종료로 판단). rounds_done=%s", rounds_done)
                    prevention_obj = {}
                else:
                    prevention_payload = {
                        "data": {
                            "case_id": case_id,
                            "rounds": rounds_done,
                            "turns": turns_all,
                            "judgements": judgements_history,
                            "guidances": guidance_history,
                            "format": "personalized_prevention"
                        }
                    }
                    if _stop and _stop.is_set():
                        raise HTTPException(status_code=499, detail="client_disconnected")
                    # 중복 호출 방지 재확인
                    if prevention_created:
                        logger.info("[Prevention] already created -> skipping admin.make_prevention")
                        res_prev = {}
                    else:
                        res_prev = ex.invoke(
                            {"input": "admin.make_prevention 호출.\n" + json.dumps(prevention_payload, ensure_ascii=False)},
                            callbacks=[cap],
                        )
                        used_tools.append("admin.make_prevention")

                    prev_obs = _last_observation(cap, "admin.make_prevention")
                    prev_dict = _loose_parse_json(prev_obs) or _loose_parse_json(res_prev)
                    if not prev_dict.get("ok"):
                        logger.error("[PreventionFail] obs=%s | res=%s", _truncate(prev_obs), _truncate(res_prev))
                        prevention_obj = {}
                    else:
                        prevention_obj = prev_dict.get("personalized_prevention") or {}

                    if prevention_obj:
                        summary = prevention_obj.get("summary", "")
                        steps = prevention_obj.get("steps", [])
                        save_payload = {
                            "data": {
                                "case_id": case_id,
                                "offender_id": offender_id,
                                "victim_id": victim_id,
                                "run_no": rounds_done,
                                "summary": summary,
                                "steps": steps
                            }
                        }
                        if _stop and _stop.is_set():
                            raise HTTPException(status_code=499, detail="client_disconnected")
                        ex.invoke(
                            {"input": "admin.save_prevention 호출.\n" + json.dumps(save_payload, ensure_ascii=False)},
                            callbacks=[cap],
                        )
                        used_tools.append("admin.save_prevention")
                        prevention_created = True
                        logger.info("[Prevention] prevention_created set True for case_id=%s", case_id)
                        # ✅ 여기서 '최종예방책 생성 완료' 전용 신호 송신
                        _emit_to_stream("chain_finished", {
                            "case_id": case_id,
                            "rounds": rounds_done,
                            "finished_reason": finished_reason,  # "critical" | "rounds_exhausted"
                        })

            # (정상 종료 전 정리) MCP 서버 중지 보장 + run_end 즉시 알림
            try:
                if mcp_manager and getattr(mcp_manager, "is_running", False):
                    mcp_manager.stop_mcp_server()
                    logger.info("[MCP] stop_mcp_server called before return for case_id=%s", case_id)
            except Exception:
                logger.exception("[MCP] stop_mcp_server failed in return-cleanup")

            result_obj = {
                "status": "success",
                "case_id": case_id,
                "rounds": rounds_done,
                "turns_per_round": req.max_turns,
                "timestamp": datetime.now().isoformat(),
                "used_tools": used_tools,
                "mcp_used": True,
                "tavily_used": tavily_used,
                "personalized_prevention": prevention_obj,  # ★ 최종예방책 포함
            }
            with contextlib.suppress(Exception):
                _emit_run_end("success", {"case_id": case_id, "rounds": rounds_done})
                _emitted_run_end = True
            return result_obj

    finally:

        with contextlib.suppress(Exception):
            #_ACTIVE_STREAMS.discard(stream_id)
            _ACTIVE_RUN_KEYS.discard(run_key)
        # 남은 버퍼 강제 flush
        with contextlib.suppress(Exception):
            tee_out.flush()
            tee_err.flush()

        # ★★★ ADDED: Smart Print 원복
        with contextlib.suppress(Exception):
            _unpatch_print()

        # (SSE) run 종료 이벤트 + 정리 (이미 보냈다면 생략)
        # with contextlib.suppress(Exception):
        #     if not _emitted_run_end:
        #         _emit_to_stream("run_end", {"case_id": locals().get("case_id", ""), "rounds": locals().get("rounds_done", 0)})
        with contextlib.suppress(Exception):
            _current_stream_id.reset(token)
        with contextlib.suppress(Exception):
            logger.removeHandler(_sse_log_handler)
        # 외부 로거에서 SSE 핸들러 제거
        _detach_global_sse_logging_handlers()
        with contextlib.suppress(Exception):
            if locals().get("mcp_manager") and getattr(mcp_manager, "is_running", False):
                mcp_manager.stop_mcp_server()

# orchestrator_react.py 안에 추가
# (import 는 파일 상단에 이미 있음: asyncio, uuid, Optional, AsyncGenerator 등)

# 스트림/런 상태 캐시
_RUN_TASKS: dict[str, asyncio.Task] = {}          # stream_id -> 백그라운드 런 task
_STREAM_CONN_COUNT: dict[str, int] = {}           # stream_id -> 현재 구독자 수(연결수)
async def run_orchestrated_stream(db: Session, payload: Dict[str, Any], stop_event: Optional[asyncio.Event] = None):
    """
    라우터에서 직접 호출하는 SSE 제너레이터.
    - 동일 stream_id로 재접속이 와도 기존 런에 '구독'만 붙고, 새 런은 만들지 않는다.
    - 마지막 구독자가 떠난 뒤에만 스트림 자원 정리.
    """
    # 1) stream_id 고정/보장
    stream_id = str(payload.get("stream_id") or uuid.uuid4())
    _ensure_stream(stream_id)
    main_q = _get_main_queue(stream_id)

    # asyncio.Event → ThreadEvent 브릿지 (to_thread 대상용)
    thread_stop = ThreadEvent()

    async def _bridge_cancel():
        if stop_event is None:
            return
        await stop_event.wait()
        thread_stop.set()

    bridge_task = None
    if stop_event is not None:
        bridge_task = asyncio.create_task(_bridge_cancel())

    # 2) 기존 런(task) 재사용: 없거나 종료된 경우에만 새로 시작
    async def _runner():
        try:
            def _work():
                # 워커 스레드 내에서 세션 생성/종료
                from app.db.session import SessionLocal
                with SessionLocal() as thread_db:
                    return run_orchestrated(thread_db, {**payload, "stream_id": stream_id}, thread_stop)
            res = await asyncio.to_thread(_work)
            ev = {"type": "result", "content": res, "ts": datetime.now().isoformat()}
            loop = _get_loop(stream_id)
            loop.call_soon_threadsafe(main_q.put_nowait, ev)
        except Exception as e:
            loop = _get_loop(stream_id)
            # 499는 정상 취소로 간주하여 result 이벤트로 통일
            try:
                from fastapi import HTTPException as _HTTPEx
                if isinstance(e, _HTTPEx) and getattr(e, "status_code", None) == 499:
                    loop.call_soon_threadsafe(
                        main_q.put_nowait,
                        {"type": "result", "content": {"status": "cancelled"}, "ts": datetime.now().isoformat()},
                    )
                else:
                    loop.call_soon_threadsafe(main_q.put_nowait, {"type": "error", "message": str(e)})
            except Exception:
                loop.call_soon_threadsafe(main_q.put_nowait, {"type": "error", "message": str(e)})

    task = _RUN_TASKS.get(stream_id)
    if task is None or task.done():
        task = asyncio.create_task(_runner())
        _RUN_TASKS[stream_id] = task

    # 3) 구독자 수 +1 (이 커넥션만의 라이프사이클)
    _STREAM_CONN_COUNT[stream_id] = _STREAM_CONN_COUNT.get(stream_id, 0) + 1

    try:
        # 메인 큐에서 이벤트를 하나씩 꺼내서 제너레이터로 내보냄
        while True:
            ev = await main_q.get()
            # 라우터에서 event/data로 감쌀 것이므로 dict 그대로 yield
            yield ev

            # 참고: 여기서 task.done()을 강제 종료 조건으로 쓰지 않는다.
            # 개별 구독자는 'run_end'/'result'/'error' 수신 시 스스로 종료하면 된다.
            if ev.get("type") in ("run_end", "error", "result"):
                break

            # 다른 코루틴에 양보
            await asyncio.sleep(0)
    finally:
        # 4) 구독자 수 -1
        try:
            _STREAM_CONN_COUNT[stream_id] = max(0, _STREAM_CONN_COUNT.get(stream_id, 1) - 1)
        except Exception:
            _STREAM_CONN_COUNT[stream_id] = 0

        # 5) 이 커넥션 정리: (런 task는 취소하지 않는다 — 다른 구독자가 있을 수 있음)
        #    마지막 구독자라면 자원 정리
        if _STREAM_CONN_COUNT.get(stream_id, 0) == 0:
            # 마지막 구독자면 백엔드 런 중단 신호
            thread_stop.set()
            # 스트림 큐/상태 제거
            _STREAMS.pop(stream_id, None)

            # task가 끝난 상태면 캐시도 정리
            t = _RUN_TASKS.get(stream_id)
            if t and t.done():
                _RUN_TASKS.pop(stream_id, None)
        if bridge_task:
            with contextlib.suppress(Exception):
                bridge_task.cancel()
