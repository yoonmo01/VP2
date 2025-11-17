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

from app.schemas.simulation_request import SimulationStartRequest
from app.services.prompt_integrator_db import build_prompt_package_from_payload

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# 전역 설정
# ─────────────────────────────────────────────────────────
EXPECT_GUIDANCE_KEY = "type"
EXPECT_MCP_DATA_WRAPPER = False

MIN_ROUNDS = 2
MAX_ROUNDS_DEFAULT = 5
MAX_ROUNDS_UI_LIMIT = 3

# SSE 모듈
import asyncio, logging, uuid, contextvars, contextlib, sys
from threading import Event as ThreadEvent
from starlette.responses import StreamingResponse
from fastapi import APIRouter, status

_StreamState = Tuple[asyncio.AbstractEventLoop, asyncio.Queue, Set[asyncio.Queue]]

_STREAMS: dict[str, _StreamState] = {}
_current_stream_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_current_stream_id", default=None)

_ACTIVE_STREAMS: Set[str] = set()
_ACTIVE_RUN_KEYS: Set[str] = set()

def _make_run_key(payload: Dict[str, Any]) -> str:
    key = {
        "offender_id": payload.get("offender_id"),
        "victim_id": payload.get("victim_id"),
        "scenario": payload.get("scenario_id") or payload.get("scenario_hash") or payload.get("scenario"),
        "victim_profile": payload.get("victim_profile_id") or payload.get("victim_profile"),
    }
    try:
        return json.dumps(key, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(key)

def _parsing_error_handler(error: Exception) -> str:
    return (
        "Invalid Format: 이전 출력은 무시하라.\n"
        "다음 형식을 정확히 지켜 다시 출력하라.\n\n"
        "Thought: (한 줄 요약)\n"
        "Action: 도구이름 (예: mcp.simulator_run)\n"
        "Action Input: (JSON 한 줄)\n"
        "Observation: (도구 출력)\n"
        "...\n"
        "Final Answer: (마지막에 한 번만)\n"
    )

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
    return _current_stream_id.get()

async def register_sink_to_current_stream(sink_q: asyncio.Queue) -> bool:
    sid = _current_stream_id.get()
    if not sid:
        return False
    _get_sinks(sid).add(sink_q)
    return True

async def unregister_sink_from_current_stream(sink_q: asyncio.Queue) -> None:
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
                logger.exception("[SSE] fan_in_from_sinks error")
                await asyncio.sleep(0.5)

    hb_task = asyncio.create_task(heartbeat())
    fanin_task = asyncio.create_task(fan_in_from_sinks())

    try:
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

def _emit_run_end(reason: str, meta: Optional[Dict[str, Any]] = None):
    try:
        payload = {"reason": reason}
        if meta:
            payload.update(meta)
        _emit_to_stream("run_end", payload)
    except Exception:
        pass

class _LogToSSEHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            try:
                text = self.format(record)
            except Exception:
                try:
                    text = record.getMessage()
                except Exception:
                    try:
                        text = str(record.msg)
                    except Exception:
                        text = "<log formatting failed>"
            if not isinstance(text, str):
                text = str(text)
            _emit_to_stream("log", text)
        except Exception:
            pass

_sse_log_handler = _LogToSSEHandler()
_sse_log_handler.setLevel(logging.INFO)
_sse_log_handler.setFormatter(logging.Formatter("%(message)s"))

_LANGCHAIN_LOGGERS = [
    "langchain",
    "langchain_core",
    "langchain_community",
]
_ATTACHED_FLAG = "_sse_handler_attached"

def _attach_global_sse_logging_handlers():
    targets = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("httpx"),
    ] + [logging.getLogger(n) for n in _LANGCHAIN_LOGGERS]

    for lg in targets:
        if not getattr(lg, _ATTACHED_FLAG, False):
            lg.addHandler(_sse_log_handler)
            try:
                if lg.level in (logging.NOTSET,) or lg.level > logging.INFO:
                    lg.setLevel(logging.INFO)
            except Exception:
                pass
            lg.propagate = True
            setattr(lg, _ATTACHED_FLAG, True)

def _detach_global_sse_logging_handlers():
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

router = APIRouter(prefix="/api/sse", tags=["sse"])

@router.get("/agent/{stream_id}")
async def sse_agent_stream(stream_id: str):
    return StreamingResponse(_sse_event_generator(stream_id), media_type="text/event-stream", status_code=status.HTTP_200_OK)

def _ensure_console_stream_handler():
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter(
            "[%(levelname)s] %(asctime)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        root.addHandler(sh)

class TeeTerminal:
    def __init__(self, stream_id: str, which: str = "stdout"):
        self.stream_id = stream_id
        self.which = which
        self.orig = sys.__stdout__ if which == "stdout" else sys.__stderr__
        self.buffer = ""
        self.loop = _get_loop(stream_id)
        self.q = _get_main_queue(stream_id)

    def write(self, text: str):
        if not text:
            return
        try:
            self.orig.write(text)
            self.orig.flush()
        except Exception:
            pass

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
                pass

    def flush(self):
        if self.buffer.strip():
            msg = {"type": "terminal", "content": self.buffer.strip(), "ts": datetime.now().isoformat()}
            try:
                self.loop.call_soon_threadsafe(self.q.put_nowait, msg)
            except Exception:
                pass
            self.buffer = ""
        try:
            self.orig.flush()
        except Exception:
            pass

# ─────────────────────────────────────────────────────────
# JSON/파싱 유틸
# ─────────────────────────────────────────────────────────
def _extract_json_block(agent_result: Any) -> Dict[str, Any]:
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
    return (obj.get("reason") or obj.get("evidence") or "").strip()

def _extract_guidance_text(agent_result: Any) -> str:
    try:
        obj = _extract_json_block(agent_result)
        if isinstance(obj, dict):
            txt = obj.get("text") or (obj.get("guidance") or {}).get("text")
            if isinstance(txt, str):
                return txt.strip()
    except Exception:
        pass
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
    if isinstance(obj, dict):
        return obj
    s = str(obj).strip()
    j = _safe_json(s)
    if j:
        return j
    try:
        if s.startswith("{") and s.endswith("}"):
            pyobj = ast.literal_eval(s)
            if isinstance(pyobj, dict):
                return pyobj
    except Exception:
        pass
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

def _as_dict(x):
    import copy
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return copy.deepcopy(x)

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

def _make_action_input_for_mcp(payload: Dict[str, Any]) -> str:
    if EXPECT_MCP_DATA_WRAPPER:
        return json.dumps({"data": payload}, ensure_ascii=False)
    else:
        return json.dumps(payload, ensure_ascii=False)

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

from app.db import models as m

def _ensure_admincase(db: Session, case_id: str, scenario_json: Dict[str, Any]) -> None:
    try:
        case = db.get(m.AdminCase, case_id)
        if not case:
            case = m.AdminCase(
                id=case_id,
                scenario=scenario_json,
                phishing=False,
                status="running",
                defense_count=0,
            )
            db.add(case)
            created = True
        else:
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
# LangChain 콜백
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
        _emit_to_stream("agent_action", {"tool": rec["tool"], "input": rec["tool_input"]})

    def on_tool_end(self, output: Any, **kwargs):
        self.events.append({
            "type": "observation",
            "tool": self.last_tool,
            "output": output,
        })
        logger.info("[ToolObservation] Tool=%s | Output=%s", self.last_tool, _truncate(output, 1200))
        _emit_to_stream("tool_observation", {"tool": self.last_tool, "output": output})

    def on_agent_finish(self, finish, **kwargs):
        self.events.append({"type": "finish", "log": finish.log})
        logger.info("[AgentFinish] %s", _truncate(finish.log, 1200))
        _emit_to_stream("agent_finish", {"log": getattr(finish, "log", "")})

# ─────────────────────────────────────────────────────────
# Smart Print
# ─────────────────────────────────────────────────────────
import builtins as _builtins

_ORIG_PRINT = _builtins.print

def _smart_print(*args, **kwargs):
    _ORIG_PRINT(*args, **kwargs)

    try:
        if len(args) != 1:
            return
        obj = args[0]

        data = obj if isinstance(obj, dict) else _loose_parse_json(obj)
        if not isinstance(data, dict) or not data:
            return

        tag = None
        if ("case_id" in data) and ("turns" in data) and ("stats" in data):
            tag = "conversation_log"
        elif ("persisted" in data) and ("phishing" in data) and ("risk" in data):
            tag = "judgement"
        elif ("type" in data) and ("text" in data) and (("categories" in data) or ("targets" in data)):
            tag = "guidance"
        elif ("personalized_prevention" in data):
            tag = "prevention"

        if tag:
            safe = _truncate(data, 2000)
            logger.info("[%s] %s", tag, json.dumps(safe, ensure_ascii=False))
            _emit_to_stream(tag, safe)
    except Exception:
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
# 도구 호출 순서 추출 및 검증 헬퍼
# ─────────────────────────────────────────────────────────
def _extract_tool_call_sequence(cap: ThoughtCapture, tool_filter: Optional[List[str]] = None) -> List[str]:
    """ThoughtCapture에서 실제 호출된 도구 순서를 추출"""
    tools = []
    for ev in cap.events:
        if ev.get("type") == "action":
            tool_name = ev.get("tool")
            if tool_filter is None or tool_name in tool_filter:
                tools.append(tool_name)
    return tools

def _validate_tool_sequence(actual: List[str], expected: List[str]) -> bool:
    """실제 도구 호출 순서가 기대 순서와 일치하는지 검증 (retry 중복 허용)"""
    actual_unique = []
    for tool in actual:
        base_tool = tool.split("(")[0] if "(" in tool else tool
        if not actual_unique or actual_unique[-1] != base_tool:
            actual_unique.append(base_tool)
    
    return actual_unique == expected

def _extract_case_id_from_agent_output(result: Any, cap: ThoughtCapture) -> Optional[str]:
    """에이전트 출력 또는 mcp.simulator_run Observation에서 case_id 추출"""
    try:
        output_text = str(result.get("output", ""))
        match = re.search(r"CASE_ID:\s*([a-f0-9\-]+)", output_text, re.I)
        if match:
            return match.group(1)
    except:
        pass
    
    sim_obs = _last_observation(cap, "mcp.simulator_run")
    sim_dict = _loose_parse_json(sim_obs)
    case_id = sim_dict.get("case_id")
    if case_id:
        return str(case_id)
    
    return None

def _extract_last_judgement(cap: ThoughtCapture) -> Dict[str, Any]:
    """가장 최근 admin.make_judgement Observation에서 판정 추출"""
    judge_obs = _last_observation(cap, "admin.make_judgement")
    if not judge_obs:
        return {}
    
    judgement = _loose_parse_json(judge_obs)
    return judgement if isinstance(judgement, dict) else {}

def _extract_prevention_from_last_observation(cap: ThoughtCapture) -> Dict[str, Any]:
    """admin.make_prevention Observation에서 예방책 추출"""
    prev_obs = _last_observation(cap, "admin.make_prevention")
    if not prev_obs:
        return {}
    
    prev_dict = _loose_parse_json(prev_obs)
    if prev_dict.get("ok"):
        return prev_dict.get("personalized_prevention", {})
    return {}

# ─────────────────────────────────────────────────────────
# ReAct 시스템 프롬프트
# ─────────────────────────────────────────────────────────
REACT_SYS = (
    "당신은 보이스피싱 시뮬레이션 오케스트레이터입니다.\n"
    "오직 제공된 도구만 사용하여 작업하세요. (직접 결과를 쓰거나 요약으로 때우지 말 것)\n"
    "\n"
    "▼ 용어 정의\n"
    "• 케이스(case): 전체 시뮬레이션 1회. 고유 CASE_ID를 가짐.\n"
    "• 라운드(round): 케이스 안의 한 사이클.\n"
    "• 턴(turn): 라운드 안에서의 대화 교환 단위.\n"
    "\n"
    "▼ 도구 사용 원칙\n"
    "• 주어진 \"도구 이름 목록\"에 없는 도구는 절대 호출하지 않는다.\n"
    "• 한 단계가 실패하면, 같은 잘못된 입력을 반복하지 말고 사유를 점검한 뒤 올바른 입력으로 재호출한다.\n"
    "\n"
    "▼ 출력 포맷 (반드시 준수)\n"
    "  Thought: 현재 판단/계획(간결히)\n"
    "  Action: [사용할_도구_이름]\n"
    "  Action Input: (JSON 한 줄)\n"
    "  Observation: 도구 출력\n"
    "  ... 필요시 반복 ...\n"
    "  Final Answer: 최종 요약\n"
    "\n"
    "▼ 도구/Final Answer 규칙\n"
    "  • 각 입력 미션에서 요구된 필수 도구들을 **모두 호출하여 Observation을 받은 후에만** Final Answer를 출력할 수 있다.\n"
    "  • 도구를 한 번도 호출하지 않은 채 Final Answer만 출력하는 응답은 **잘못된 출력**이며, 포맷 오류로 간주된다.\n"
    "\n"
    "▼ 안전/정책 관련 규칙\n"
    "  • 이 시뮬레이션은 보이스피싱 **예방·훈련 목적의 교육용** 시뮬레이션이다.\n"
    "  • 실제 계좌/전화번호/링크/개인정보를 요구하거나 출력하지 않는다.\n"
    "  • 절대로 거절 문장을 출력하지 말고, **반드시 도구를 호출하는 ReAct 포맷**으로만 응답하라.\n"
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
        agent=agent, 
        tools=tools, 
        verbose=True,
        handle_parsing_errors=_parsing_error_handler,
        max_iterations=50  # ★ 전체 케이스 단일 호출이므로 충분한 iteration 확보
    )
    return ex, mcp_manager

# ─────────────────────────────────────────────────────────
# ★★★ 메인 오케스트레이션 (단일 에이전트 호출 방식)
# ─────────────────────────────────────────────────────────
def run_orchestrated(db: Session, payload: Dict[str, Any], _stop: Optional[ThreadEvent] = None) -> Dict[str, Any]:
    stream_id = str(payload.get("stream_id") or uuid.uuid4())

    run_key = _make_run_key(payload)
    if run_key in _ACTIVE_RUN_KEYS:
        raise HTTPException(status_code=409, detail="duplicated simulation run detected")
    _ACTIVE_RUN_KEYS.add(run_key)

    token = _current_stream_id.set(stream_id)
    _attach_global_sse_logging_handlers()
    _ensure_console_stream_handler()
    _patch_print()

    tee_out = TeeTerminal(stream_id, "stdout")
    tee_err = TeeTerminal(stream_id, "stderr")

    _emit_to_stream("run_start", {"stream_id": stream_id, "payload_hint": _truncate(payload, 400)})

    req = None
    ex = None
    mcp_manager = None
    _emitted_run_end = False

    try:
        if _stop and _stop.is_set():
            return {"status": "cancelled"}
            
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            req = SimulationStartRequest(**payload)
            ex, mcp_manager = build_agent_and_tools(db, use_tavily=req.use_tavily)

            # 프롬프트 패키지 (DB 조립)
            pkg = build_prompt_package_from_payload(
                db, req, tavily_result=None, is_first_run=True, skip_catalog_write=True
            )
            scenario = pkg["scenario"]
            victim_profile = pkg["victim_profile"]
            templates = pkg["templates"]

            logger.info("[InitialInput] %s", json.dumps(_truncate(payload), ensure_ascii=False))
            logger.info("[ComposedPromptPackage] %s", json.dumps(_truncate(pkg), ensure_ascii=False))

            offender_id = int(req.offender_id or 0)
            victim_id = int(req.victim_id or 0)

            # 라운드 정책
            try:
                requested_rounds = int(getattr(req, "round_limit", MAX_ROUNDS_DEFAULT) or MAX_ROUNDS_DEFAULT)
            except Exception:
                requested_rounds = MAX_ROUNDS_DEFAULT

            requested_rounds = max(MIN_ROUNDS, requested_rounds)
            max_rounds = min(requested_rounds, MAX_ROUNDS_UI_LIMIT)

            scenario_base = _as_dict(scenario)
            victim_profile_base = _as_dict(victim_profile)
            templates_base = _as_dict(templates)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # ★★★ 전체 케이스 미션 구성 (동적 라운드)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            case_mission = f"""
[보이스피싱 시뮬레이션 케이스 전체 실행]

당신의 임무는 최대 {max_rounds}라운드까지의 보이스피싱 시뮬레이션 케이스를 완료하는 것이다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【라운드1 실행】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. sim.fetch_entities 호출
   - offender_id: {offender_id}
   - victim_id: {victim_id}

2. sim.compose_prompts 호출
   - ★★★ Action Input 형식: {{"data": {{"scenario": "...", "victim_profile": "...", "round_no": 1}}}}
   - ★ guidance 필드는 절대 포함하지 말 것 (라운드1이므로)
   
3. mcp.simulator_run 호출
   - ★ 이 도구는 data 래핑 없이 최상위에 직접 필드를 넣음
   - ★ guidance 필드는 절대 포함하지 말 것
   - max_turns: {req.max_turns}
   
4. admin.make_judgement 호출
   - ★★★ Action Input 형식: {{"data": {{"case_id": "...", "run_no": 1, "turns": [...]}}}}
   - ★★★ run_no는 반드시 1이어야 함

5. 라운드1 판정 결과 확인:
   - risk.level == "critical" → 【케이스 종료】로 이동
   - 그 외 → 6단계 진행

6. admin.generate_guidance 호출 (라운드2용 가이던스 생성)
   - ★★★ Action Input 형식: {{"data": {{"case_id": "...", "run_no": 1, "data.type": "A", ...}}}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【라운드 2~{max_rounds} 반복 실행】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
각 라운드 N (N = 2, 3, 4, 5...)에 대해 다음을 수행:

7-N-1. sim.compose_prompts 호출
   - ★★★ Action Input 형식: {{"data": {{"scenario": "...", "victim_profile": "...", "round_no": N, "guidance": {{"type": "A", "text": "..."}}}}}}
   - case_id: (라운드1에서 받은 case_id)
   - round_no: N (현재 라운드 번호)
   - guidance: (이전 라운드에서 생성한 가이던스)
   
7-N-2. mcp.simulator_run 호출
   - case_id_override: (라운드1 case_id)
   - round_no: N
   - guidance: (이전 라운드 가이던스)
   
7-N-3. admin.make_judgement 호출
   - ★★★ Action Input 형식: {{"data": {{"case_id": "...", "run_no": N, "turns": [...]}}}}
   - ★★★ run_no는 반드시 현재 라운드 번호 N과 일치해야 함
   - 예: 라운드2면 run_no=2, 라운드3이면 run_no=3, 라운드4면 run_no=4, 라운드5면 run_no=5

7-N-4. 판정 결과 확인:
   - risk.level == "critical" → 【케이스 종료】로 이동
   - 현재 라운드 N == {max_rounds} → 【케이스 종료】로 이동
   - 그 외 → 7-N-5 진행

7-N-5. admin.generate_guidance 호출 (다음 라운드용)
   - ★★★ Action Input 형식: {{"data": {{"case_id": "...", "run_no": N, "data.type": "A", ...}}}}
   - run_no: 현재 라운드 N
   - 다음 라운드 N+1을 위한 가이던스 생성

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【케이스 종료】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8. admin.make_prevention 호출
   - ★★★ Action Input 형식: {{"data": {{"case_id": "...", "rounds": N, "turns": [...], "judgements": [...], "guidances": [...]}}}}
   - turns: 모든 라운드의 대화 내역을 하나의 배열로 통합
   - judgements: 모든 라운드의 판정 결과 배열
   - guidances: 사용된 모든 가이던스 배열
   - ★ 도구 내부에서 자동으로 데이터 타입을 정규화하므로 형식 걱정 불필요

9. admin.save_prevention 호출
   - 8단계 결과 저장

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 중요 규칙 (문제 1, 2 해결)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【문제 1 해결: Pydantic 에러 방지】
- sim.compose_prompts 호출 시 반드시 {{"data": {{...}}}} 형식 사용
- 라운드1: guidance 필드 절대 포함 금지
- 라운드2~{max_rounds}: guidance 필드 필수 포함

【문제 2 해결: run_no 정확성】
- admin.make_judgement의 run_no는 해당 라운드 번호와 정확히 일치해야 함
- 라운드1 → run_no=1
- 라운드2 → run_no=2
- 라운드3 → run_no=3
- 라운드4 → run_no=4
- 라운드5 → run_no=5

▼ 도구별 Action Input 규칙 요약
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- [mcp.simulator_run] 최상위 언랩 JSON (data 래핑 없음)
- [admin.*] {{"data": {{...}}}} 래핑 필수
- [sim.*] {{"data": {{...}}}} 래핑 필수
"""

            logger.info("[CaseMission] 전체 케이스 미션 시작")
            logger.info(f"[CaseMission] max_rounds={max_rounds}")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # ★★★ 에이전트 단일 호출 (전체 케이스)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            try:
                cap = ThoughtCapture()
                result = ex.invoke({"input": case_mission}, callbacks=[cap])
                logger.info(f"[CaseMission] Agent result: {_truncate(result)}")
            except Exception as e:
                logger.error(f"[CaseMission] Agent execution failed: {e}")
                raise HTTPException(500, f"케이스 실행 실패: {e}")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 결과 추출 및 검증
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            # 1. 도구 호출 순서 확인
            actual_tools = _extract_tool_call_sequence(cap)
            logger.info(f"[CaseMission] 호출된 도구들: {actual_tools}")

            if not actual_tools:
                logger.error("[CaseMission] 도구가 하나도 호출되지 않았습니다")
                raise HTTPException(500, "에이전트가 도구를 호출하지 않았습니다")

            used_tools = actual_tools

            # 2. case_id 추출
            case_id = _extract_case_id_from_agent_output(result, cap)
            if not case_id:
                logger.error("[CaseMission] case_id 추출 실패")
                raise HTTPException(500, "case_id 추출 실패")

            _ensure_admincase(db, case_id, scenario_base)
            logger.info(f"[CaseMission] case_id 확정: {case_id}")

            # 3. 완료된 라운드 수 계산
            judgement_count = sum(1 for tool in actual_tools if tool == "admin.make_judgement")
            rounds_done = judgement_count
            logger.info(f"[CaseMission] 완료된 라운드: {rounds_done}")

            # 4. 각 라운드 판정 및 turns 추출
            judgements_history = []
            turns_all = []
            guidance_history = []

            # ThoughtCapture에서 순서대로 추출
            judgement_idx = 0
            guidance_idx = 0
            sim_run_idx = 0

            for ev in cap.events:
                if ev.get("type") == "observation":
                    tool_name = ev.get("tool")
                    output = ev.get("output")
                    
                    # admin.make_judgement
                    if tool_name == "admin.make_judgement":
                        judgement_idx += 1
                        judgement = _loose_parse_json(output)
                        if judgement:
                            judgements_history.append({
                                "run_no": judgement_idx,
                                "phishing": judgement.get("phishing", False),
                                "risk": judgement.get("risk", {}),
                                "evidence": judgement.get("evidence", "")
                            })
                    
                    # mcp.simulator_run
                    elif tool_name == "mcp.simulator_run":
                        sim_run_idx += 1
                        sim_dict = _loose_parse_json(output)
                        turns = sim_dict.get("turns") or []
                        if isinstance(turns, list):
                            turns_all.extend(turns)
                            
                            # DB 저장 (라운드별)
                            try:
                                round_row = (
                                    db.query(m.ConversationRound)
                                    .filter(m.ConversationRound.case_id == case_id,
                                            m.ConversationRound.run == sim_run_idx)
                                    .first()
                                )
                                if not round_row:
                                    round_row = m.ConversationRound(
                                        case_id=case_id,
                                        run=sim_run_idx,
                                        offender_id=offender_id,
                                        victim_id=victim_id,
                                        turns=turns,
                                        ended_by=sim_dict.get("ended_by"),
                                        stats=sim_dict.get("stats", {}),
                                    )
                                    db.add(round_row)
                                else:
                                    round_row.turns = turns
                                    round_row.ended_by = sim_dict.get("ended_by")
                                    round_row.stats = sim_dict.get("stats", {})
                                db.commit()
                            except Exception as e:
                                logger.warning(f"[DB] round {sim_run_idx} 저장 실패: {e}")
                    
                    # admin.generate_guidance
                    elif tool_name == "admin.generate_guidance":
                        guidance_idx += 1
                        guidance_obj = _loose_parse_json(output)
                        if guidance_obj:
                            guidance_history.append({
                                "for_round": guidance_idx + 1,
                                "kind": guidance_obj.get("type", ""),
                                "text": guidance_obj.get("text", "")
                            })

            logger.info(f"[CaseMission] 판정 수: {len(judgements_history)}, turns 총 {len(turns_all)}개")

            # 5. 종료 사유 판단
            last_judgement = judgements_history[-1] if judgements_history else {}
            risk_lvl = (last_judgement.get("risk", {}).get("level") or "").lower()

            if risk_lvl == "critical":
                finished_reason = "critical"
            elif rounds_done >= max_rounds:
                finished_reason = "max_rounds"
            else:
                finished_reason = "unknown"

            logger.info(f"[CaseMission] 종료 사유: {finished_reason}")

            # 6. 예방책 추출
            prevention_obj = _extract_prevention_from_last_observation(cap)

            if prevention_obj:
                logger.info("[Prevention] 예방책 추출 성공")
                _emit_to_stream("finished_chain", {
                    "case_id": case_id,
                    "rounds": rounds_done,
                    "finished_reason": finished_reason,
                })
            else:
                logger.warning("[Prevention] 예방책 객체 추출 실패")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 정상 종료 전 정리
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            try:
                if mcp_manager and getattr(mcp_manager, "is_running", False):
                    mcp_manager.stop_mcp_server()
                    logger.info("[MCP] stop_mcp_server called for case_id=%s", case_id)
            except Exception:
                logger.exception("[MCP] stop_mcp_server failed")

            result_obj = {
                "status": "success",
                "case_id": case_id,
                "rounds": rounds_done,
                "turns_per_round": req.max_turns,
                "timestamp": datetime.now().isoformat(),
                "used_tools": used_tools,
                "mcp_used": True,
                "tavily_used": False,
                "personalized_prevention": prevention_obj,
                "finished_reason": finished_reason,
            }

            with contextlib.suppress(Exception):
                _emit_run_end("success", {"case_id": case_id, "rounds": rounds_done})
                _emitted_run_end = True

            return result_obj

    finally:
        with contextlib.suppress(Exception):
            _ACTIVE_RUN_KEYS.discard(run_key)
        with contextlib.suppress(Exception):
            tee_out.flush()
            tee_err.flush()
        with contextlib.suppress(Exception):
            _unpatch_print()
        with contextlib.suppress(Exception):
            _current_stream_id.reset(token)
        with contextlib.suppress(Exception):
            logger.removeHandler(_sse_log_handler)
        _detach_global_sse_logging_handlers()
        with contextlib.suppress(Exception):
            if locals().get("mcp_manager") and getattr(mcp_manager, "is_running", False):
                mcp_manager.stop_mcp_server()

# ─────────────────────────────────────────────────────────
# SSE 스트림
# ─────────────────────────────────────────────────────────
_RUN_TASKS: dict[str, asyncio.Task] = {}
_STREAM_CONN_COUNT: dict[str, int] = {}

async def run_orchestrated_stream(db: Session, payload: Dict[str, Any], stop_event: Optional[asyncio.Event] = None):
    stream_id = str(payload.get("stream_id") or uuid.uuid4())
    _ensure_stream(stream_id)
    main_q = _get_main_queue(stream_id)

    thread_stop = ThreadEvent()

    async def _bridge_cancel():
        if stop_event is None:
            return
        await stop_event.wait()
        thread_stop.set()

    bridge_task = None
    if stop_event is not None:
        bridge_task = asyncio.create_task(_bridge_cancel())

    async def _runner():
        try:
            def _work():
                from app.db.session import SessionLocal
                with SessionLocal() as thread_db:
                    return run_orchestrated(thread_db, {**payload, "stream_id": stream_id}, thread_stop)
            res = await asyncio.to_thread(_work)
            ev = {"type": "result", "content": res, "ts": datetime.now().isoformat()}
            loop = _get_loop(stream_id)
            loop.call_soon_threadsafe(main_q.put_nowait, ev)
        except Exception as e:
            loop = _get_loop(stream_id)
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

    _STREAM_CONN_COUNT[stream_id] = _STREAM_CONN_COUNT.get(stream_id, 0) + 1

    try:
        while True:
            ev = await main_q.get()
            yield ev

            if ev.get("type") in ("run_end", "error", "result"):
                break

            await asyncio.sleep(0)
    finally:
        try:
            _STREAM_CONN_COUNT[stream_id] = max(0, _STREAM_CONN_COUNT.get(stream_id, 1) - 1)
        except Exception:
            _STREAM_CONN_COUNT[stream_id] = 0

        if _STREAM_CONN_COUNT.get(stream_id, 0) == 0:
            thread_stop.set()
            _STREAMS.pop(stream_id, None)

            t = _RUN_TASKS.get(stream_id)
            if t and t.done():
                _RUN_TASKS.pop(stream_id, None)
        
        if bridge_task:
            with contextlib.suppress(Exception):
                bridge_task.cancel()