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
from app.services.tts_service import (
    cache_run_dialog,          # ✅ 라운드별 대화 캐시 저장
    clear_case_dialog_cache,   # ✅ 케이스 종료 시 캐시 정리
)

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# 전역 설정
# ─────────────────────────────────────────────────────────
EXPECT_GUIDANCE_KEY = "type"
EXPECT_MCP_DATA_WRAPPER = False

MIN_ROUNDS = 2
MAX_ROUNDS_DEFAULT = 5
MAX_ROUNDS_UI_LIMIT = 3

_PROMPT_CACHE: Dict[str, Dict[str, str]] = {}

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
    error_msg = str(error)
    
    # Final Answer 관련 에러 감지
    if "Final Answer" in error_msg or "final answer" in error_msg.lower():
        return (
            "⚠️ Final Answer 작성 시도 감지 - 필수 도구 체크 필요!\n"
            "\n"
            "Final Answer를 작성하기 전에 다음을 확인하세요:\n"
            "\n"
            "1. admin.make_prevention을 호출했는가?\n"
            "   Thought: 예방책을 생성해야 함\n"
            "   Action: admin.make_prevention\n"
            "   Action Input: {\"data\": {\"case_id\": \"...\", \"rounds\": N, ...}}\n"
            "   Observation: (반드시 확인)\n"
            "\n"
            "2. admin.save_prevention을 호출했는가?\n"
            "   Thought: 예방책을 저장해야 함\n"
            "   Action: admin.save_prevention\n"
            "   Action Input: {\"data\": {\"case_id\": \"...\", ...}}\n"
            "   Observation: (반드시 확인)\n"
            "\n"
            "위 2개 도구를 호출하지 않았다면, 지금 즉시 호출하세요.\n"
            "도구를 호출하지 않고 텍스트를 직접 작성하는 것은 금지됩니다.\n"
        )
    
    return (
        "Invalid Format: 이전 출력은 무시하라.\n"
        "다음 형식을 정확히 지켜 다시 출력하라.\n\n"
        "Thought: (한 줄 요약)\n"
        "Action: 도구이름 (예: mcp.simulator_run)\n"
        "Action Input: (JSON 한 줄)\n"
        "Observation: (도구 출력)\n"
        "...\n"
        "Final Answer: 최종 요약(최종 case_id, 총 라운드 수, 각 라운드 판정 요약/피싱 여부 포함)\n"
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

        # ★★★ conversation_log 감지 (MCP 대화 결과)
        if ("case_id" in data) and ("turns" in data) and ("stats" in data):
            tag = "conversation_log"

            # ✅ 여기서 TTS 캐시 저장까지 같이 처리
            try:
                case_id = str(data.get("case_id"))
                run_no = int(data.get("run_no", 1))
                raw_turns = data.get("turns", [])

                cleaned_turns = []
                for turn in raw_turns:
                    role = turn.get("role", "")
                    text = turn.get("text", "")

                    # 피해자 턴이 JSON이면 dialogue만 뽑기
                    if role == "victim":
                        s = (text or "").strip()
                        if s.startswith("{"):
                            try:
                                v_json = json.loads(s)
                                text = v_json.get("dialogue", text)
                            except Exception:
                                # 파싱 실패하면 원문 그대로 둠
                                pass

                    cleaned_turns.append(
                        {
                            "role": role,
                            "text": text,
                        }
                    )

                if case_id and cleaned_turns:
                    # TTS 캐시 저장
                    cache_run_dialog(
                        case_id=case_id,
                        run_no=run_no,
                        turns=cleaned_turns,
                    )
                    logger.info(
                        "[TTS_CACHE] cached from conversation_log: case_id=%s run_no=%s turns=%s",
                        case_id,
                        run_no,
                        len(cleaned_turns),
                    )
            except Exception as e:
                logger.error("[TTS_CACHE] _smart_print 캐시 저장 실패: %s", e)
        
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

def _wrap_sim_compose_prompts(original_tool):
    """sim.compose_prompts를 래핑하여 프롬프트를 캐시하고 ID만 반환"""
    from langchain_core.tools import tool
    from typing import Any

    @tool
    def sim_compose_prompts_cached(data: Any) -> dict:
        """프롬프트 생성 후 캐시에 저장하고 prompt_id만 반환"""

        # ★★★ 디버깅: 원본 입력 로깅
        logger.info(f"[PromptCache] 원본 data 타입: {type(data)}")
        if isinstance(data, str):
            logger.info(f"[PromptCache] 원본 data 길이: {len(data)}")
            logger.info(f"[PromptCache] 원본 data 전체: {data}")  # ★ 전체 출력으로 변경
        else:
            logger.info(f"[PromptCache] 원본 data: {data}")

        # 1) 문자열 → JSON (강화된 파싱 with 정규식 추출)
        if isinstance(data, str):
            # ★★★ JSON 부분만 추출 (줄바꿈 이후 텍스트 제거)
            s = data.strip()
            
            # 첫 번째 완전한 JSON 객체만 추출
            brace_count = 0
            json_end_idx = -1
            for i, char in enumerate(s):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end_idx = i + 1
                        break
            
            if json_end_idx > 0:
                json_str = s[:json_end_idx]
                logger.info(f"[PromptCache] 추출된 JSON 길이: {len(json_str)}")
                logger.info(f"[PromptCache] 추출된 JSON: {json_str[:300]}...")
            else:
                json_str = s
            
            try:
                parsed = json.loads(json_str)
                logger.info(f"[PromptCache] json.loads 성공")
            except Exception as e:
                logger.warning(f"[PromptCache] json.loads 실패: {e}")
                parsed = _loose_parse_json(json_str)
                logger.info(f"[PromptCache] _loose_parse_json 결과 keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'NOT_DICT'}")
        else:
            parsed = data

        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "error": f"sim.compose_prompts 입력 data는 dict여야 합니다. got={type(parsed).__name__}",
            }

        # ★★★ parsed가 비어있으면 즉시 에러 반환
        if not parsed:
            logger.error(f"[PromptCache] parsed가 완전히 비어있음!")
            return {
                "ok": False,
                "error": "json_parse_failed",
                "message": f"JSON 파싱 완전 실패. 원본 data 타입={type(data)}, 원본 data={str(data)[:500]}",
            }

        # 2) 데이터 추출 로직 강화 (다층 구조 지원)
        logger.info(f"[PromptCache] 원본 parsed keys: {list(parsed.keys())}")
        
        # 케이스 1: {"data": {"scenario": ..., "victim_profile": ..., "round_no": ...}}
        if "data" in parsed and isinstance(parsed["data"], dict):
            inner = parsed["data"]
            # round_no가 상위에 있으면 inner로 병합
            if "round_no" in parsed and "round_no" not in inner:
                inner["round_no"] = parsed["round_no"]
        # 케이스 2: {"scenario": ..., "victim_profile": ..., "round_no": ...}
        elif "scenario" in parsed or "victim_profile" in parsed:
            inner = parsed
        # 케이스 3: {"data": {"data": {...}}} (중첩된 경우)
        elif "data" in parsed:
            inner = parsed["data"]
        else:
            inner = parsed

        # 3) 필수 필드 검증 (scenario와 victim_profile 확인)
        logger.info(f"[PromptCache] inner keys: {list(inner.keys())}")
        logger.info(f"[PromptCache] scenario 존재: {'scenario' in inner}")
        logger.info(f"[PromptCache] victim_profile 존재: {'victim_profile' in inner}")

        if not inner or (not inner.get("scenario") and not inner.get("victim_profile")):
            # 디버깅 정보 강화
            logger.error(f"[PromptCache] 파싱 실패 - 원본 data 타입: {type(data)}")
            logger.error(f"[PromptCache] 파싱 실패 - parsed: {parsed}")
            logger.error(f"[PromptCache] 파싱 실패 - inner: {inner}")
            
            return {
                "ok": False,
                "error": "empty_input",
                "message": "sim.compose_prompts에 scenario 또는 victim_profile이 없습니다.",
                "parsed_keys": list(parsed.keys()),
                "inner_keys": list(inner.keys()) if inner else [],
                "debug_info": {
                    "data_type": str(type(data)),
                    "data_preview": str(data)[:300] if isinstance(data, str) else str(data)[:300],
                    "parsed_has_data": "data" in parsed,
                    "parsed_has_scenario": "scenario" in parsed,
                    "inner_is_empty": not bool(inner)
                }
            }

        # 4) scenario/victim_profile 추출
        scenario = inner.get("scenario")
        victim_profile = inner.get("victim_profile")
        round_no = inner.get("round_no", 1)

        logger.info(f"[PromptCache] 추출 완료 - scenario: {scenario is not None}, victim_profile: {victim_profile is not None}, round_no: {round_no}")

        # 5) payload 구성 (data 래핑)
        payload = {"data": inner}

        # 6) 원본 도구 호출
        try:
            logger.info(f"[PromptCache] 원본 도구 호출 시작 - payload keys: {list(payload.keys())}")
            result = original_tool.invoke(payload)
            logger.info(f"[PromptCache] 원본 도구 호출 성공")
        except Exception as e:
            logger.error(f"[sim.compose_prompts] 원본 도구 호출 실패: {e}")
            return {
                "ok": False,
                "error": f"프롬프트 생성 실패: {str(e)}"
            }

        # 7) 결과 파싱
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = _loose_parse_json(result)

        if not isinstance(result, dict):
            return {"ok": False, "error": "sim.compose_prompts 결과가 dict가 아닙니다"}

        attacker_prompt = result.get("attacker_prompt", "")
        victim_prompt = result.get("victim_prompt", "")

        if not attacker_prompt or not victim_prompt:
            return {"ok": False, "error": "프롬프트가 비어있습니다"}

        # 8) 캐시 저장
        prompt_id = f"prompts_round_{round_no}_{id(result)}"

        _PROMPT_CACHE[prompt_id] = {
            "attacker_prompt": attacker_prompt,
            "victim_prompt": victim_prompt,
            "scenario": scenario,
            "victim_profile": victim_profile,
        }

        logger.info(f"[PromptCache] 저장 완료: {prompt_id} (round={round_no})")

        # 9) 최종 검증
        if scenario is None or victim_profile is None:
            logger.warning(f"[PromptCache] 경고: scenario={scenario is not None}, victim_profile={victim_profile is not None}")
            logger.warning(f"[PromptCache] mcp.simulator_run 호출 시 에러 가능성 있음")

        return {
            "ok": True,
            "prompt_id": prompt_id,
            "message": f"프롬프트가 {prompt_id}에 저장되었습니다. mcp.simulator_run 호출 시 이 ID를 사용하세요.",
        }

    sim_compose_prompts_cached.name = "sim.compose_prompts"
    sim_compose_prompts_cached.description = (
        "시나리오와 피해자 프로필로 공격자/피해자 프롬프트를 생성합니다. "
        "결과로 prompt_id를 받아서 mcp.simulator_run에 전달하세요."
    )

    return sim_compose_prompts_cached

def _wrap_mcp_simulator_run(original_tool):
    """mcp.simulator_run을 래핑하여 prompt_id로 캐시된 프롬프트 사용"""
    from langchain_core.tools import tool
    from typing import Any

    @tool
    def mcp_simulator_run_cached(data: Any) -> dict:
        """시뮬레이션 실행 (캐시된 프롬프트 사용)"""

        # 1) 문자열 → JSON
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = _loose_parse_json(data)
        else:
            parsed = data

        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "error": f"mcp.simulator_run 입력 data는 dict여야 합니다. got={type(parsed).__name__}",
            }

        # 2) {"data": {...}} / {...} 둘 다 허용
        params = parsed["data"] if isinstance(parsed.get("data"), dict) else parsed

        # 3) 필수 필드 파싱
        try:
            offender_id = int(params["offender_id"])
            victim_id = int(params["victim_id"])
            prompt_id = params["prompt_id"]
            max_turns = int(params["max_turns"])
            round_no = int(params["round_no"])
        except KeyError as e:
            return {"ok": False, "error": f"mcp.simulator_run 필수 필드 누락: {e.args[0]}"}
        except ValueError as e:
            return {"ok": False, "error": f"숫자 필드(offender_id/victim_id/max_turns/round_no) 파싱 실패: {e}"}

        case_id_override = params.get("case_id_override")
        guidance = params.get("guidance")

        # 4) prompt_id 기반 캐시 로드 (여기서 scenario/victim_profile까지 같이 가져옴)
        if prompt_id not in _PROMPT_CACHE:
            return {
                "ok": False,
                "error": f"프롬프트 {prompt_id}를 캐시에서 찾을 수 없습니다. sim.compose_prompts를 먼저 호출하세요.",
            }

        cache_entry = _PROMPT_CACHE[prompt_id]
        attacker_prompt = cache_entry.get("attacker_prompt", "")
        victim_prompt = cache_entry.get("victim_prompt", "")
        scenario = cache_entry.get("scenario")
        victim_profile = cache_entry.get("victim_profile")

        logger.info(f"[PromptCache] 로드: {prompt_id}")

        # ★ victim_profile은 반드시 있어야 함
        if victim_profile is None:
            return {
                "ok": False,
                "error": "missing_victim_profile",
                "message": "victim_profile이 캐시에 없습니다. sim.compose_prompts 호출 시 scenario/victim_profile이 제대로 전달되었는지 확인하세요.",
            }

        # 5) MCP에 넘길 payload 구성
        payload = {
            "offender_id": offender_id,
            "victim_id": victim_id,
            "scenario": scenario,          # ← offender_id에서 가져온 원본 시나리오
            "victim_profile": victim_profile,  # ← 역시 fetch_entities 기준
            "attacker_prompt": attacker_prompt,
            "victim_prompt": victim_prompt,
            "max_turns": max_turns,
            "round_no": round_no,
        }

        if case_id_override:
            payload["case_id_override"] = case_id_override
        if guidance:
            payload["guidance"] = guidance

        # 6) 원본 MCP 도구 호출 (data 래핑 필수)
        mcp_input = {"data": payload}
        result = original_tool.invoke(mcp_input)
        return result

    mcp_simulator_run_cached.name = "mcp.simulator_run"
    mcp_simulator_run_cached.description = (
        "보이스피싱 시뮬레이션을 실행합니다. "
        "prompt_id는 sim.compose_prompts에서 받은 값을 사용하세요."
    )

    return mcp_simulator_run_cached

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

def _validate_complete_execution(cap: ThoughtCapture, max_rounds: int) -> dict:
    """실행 완료 여부를 검증하고 누락된 단계를 반환"""
    tools_called = _extract_tool_call_sequence(cap)
    
    required = {
        "sim.fetch_entities": 1,
        "sim.compose_prompts": max_rounds,
        "mcp.simulator_run": max_rounds,
        "admin.make_judgement": max_rounds,
        "admin.generate_guidance": max(0, max_rounds - 1),
        "admin.make_prevention": 1,
        "admin.save_prevention": 1,
    }
    
    missing = []
    tool_counts = {}
    for tool in tools_called:
        tool_counts[tool] = tool_counts.get(tool, 0) + 1
    
    for tool, expected_count in required.items():
        actual_count = tool_counts.get(tool, 0)
        if actual_count < expected_count:
            missing.append(f"{tool} (예상:{expected_count}, 실제:{actual_count})")
    
    return {
        "is_complete": len(missing) == 0,
        "missing_steps": missing,
        "tools_called": tools_called,
        "tool_counts": tool_counts
    }

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
    "• 도구를 호출하지 않고 직접 결과를 작성하거나 요약하는 것은 금지된다.\n"
    "\n"
    "▼ 출력 포맷 (반드시 준수)\n"
    "  Thought: 현재 판단/계획(간결히)\n"
    "  Action: [사용할_도구_이름]\n"
    "  Action Input: (JSON 한 줄)\n"
    "  Observation: 도구 출력\n"
    "  ... 필요시 반복 ...\n"
    "  Final Answer: 최종 요약(최종 case_id, 총 라운드 수, 각 라운드 판정 요약 포함)\n"
    "\n"
    "▼ 도구/Final Answer 규칙\n"
    "  • 각 입력 미션에서 요구된 필수 도구들을 **모두 호출하여 Observation을 받은 후에만** Final Answer를 출력할 수 있다.\n"
    "  • 도구를 한 번도 호출하지 않은 채 Final Answer만 출력하는 응답은 **잘못된 출력**이며, 포맷 오류로 간주된다.\n"
    "  • 특히 admin.make_prevention과 admin.save_prevention은 **절대 생략 불가**이다.\n"
    "\n"
    "▼ Final Answer 작성 전 필수 체크리스트\n"
    "  ⚠️ Final Answer 작성 전 반드시 확인:\n"
    "  1. ✅ admin.make_prevention을 호출하여 Observation을 받았는가?\n"
    "  2. ✅ admin.save_prevention을 호출하여 Observation을 받았는가?\n"
    "  3. ✅ 위 2개 도구의 Observation에 실제 데이터가 포함되어 있는가?\n"
    "\n"
    "  ❌ 다음 행동은 절대 금지:\n"
    "  • 도구를 호출하지 않고 '최종 예방 요약'이라는 텍스트를 직접 작성\n"
    "  • admin.make_prevention 없이 예방책 내용을 날조\n"
    "  • 단계 10, 11을 건너뛰고 바로 Final Answer 작성\n"
    "\n"
    "  ✅ 올바른 순서:\n"
    "  → admin.make_prevention 호출 → Observation 확인\n"
    "  → admin.save_prevention 호출 → Observation 확인\n"
    "  → Final Answer 작성 (Observation 내용 포함)\n"
    "\n"
    "▼ Final Answer 구성 규칙\n"
    "  Final Answer에는 반드시 아래 정보를 포함한다.\n"
    "  - CASE_ID: 이 케이스에서 사용된 최종 case_id\n"
    "  - 총 라운드 수: 실제로 수행된 라운드 수\n"
    "  - 라운드별 판정 요약: 각 라운드별 보이스피싱 여부(phishing), risk.level, 근거 한 줄\n"
    "  - 예방책: admin.make_prevention의 Observation 내용 (직접 작성 금지)\n"
    "  예시 포맷:\n"
    "  Final Answer: \n"
    "  CASE_ID: <case_id>\n"
    "  총 라운드 수: <rounds_done>\n"
    "  라운드별 판정:\n"
    "    - Round 1: phishing=<true|false>, risk.level=\"<level>\", 요약=<한 줄>\n"
    "    - Round 2: ...\n"
    "  최종 예방 요약: admin.make_prevention Observation을 기반으로 한 한 단락 요약\n"
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
    # ★★★ sim.compose_prompts 래핑
    raw_sim_tools = make_sim_tools(db)
    for tool in raw_sim_tools:
        if tool.name == "sim.compose_prompts":
            tools.append(_wrap_sim_compose_prompts(tool))
        else:
            tools.append(tool)

    mcp_res = make_mcp_tools()
    if isinstance(mcp_res, tuple):
        mcp_tools, mcp_manager = mcp_res
    else:
        mcp_tools, mcp_manager = mcp_res, None
    for tool in mcp_tools:
        if tool.name == "mcp.simulator_run":
            tools.append(_wrap_mcp_simulator_run(tool))
        else:
            tools.append(tool)

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

            # ─────────────────────────────────────
            # 피해자/공격자 성별 정보 정리 (TTS용)
            # ─────────────────────────────────────
            def _normalize_gender_str(g: Optional[str]) -> Optional[str]:
                if not g:
                    return None
                s = str(g).strip().lower()
                if s in ("남", "남자", "male", "m"):
                    return "male"
                if s in ("여", "여자", "female", "f"):
                    return "female"
                return None

            victim_profile_base = _as_dict(victim_profile)
            victim_meta = victim_profile_base.get("meta", {}) if isinstance(victim_profile_base, dict) else {}

            # 1순위: 요청 payload에 담긴 victim_gender / offender_gender (FE에서 보내는 값)
            victim_gender_req = _normalize_gender_str(getattr(req, "victim_gender", None))
            offender_gender_req = _normalize_gender_str(getattr(req, "offender_gender", None))

            # 2순위: DB victim_profile.meta.gender
            victim_gender_db = _normalize_gender_str(victim_meta.get("gender"))

            victim_gender = victim_gender_req or victim_gender_db or "female"
            offender_gender = offender_gender_req or "male"

            # (선택) 나이 → age_group으로 변환 (TTS에서 쓰고 있다면)
            def _age_to_group(age: Optional[int]) -> Optional[str]:
                try:
                    a = int(age)
                except Exception:
                    return None
                if a < 30:
                    return "20s"
                if a < 40:
                    return "30s"
                if a < 50:
                    return "40s"
                if a < 60:
                    return "50s"
                if a < 70:
                    return "60s"
                return "70s+"

            victim_age_group = _age_to_group(victim_meta.get("age"))

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
당신은 보이스피싱 시뮬레이션 케이스를 최대 {max_rounds}라운드까지 실행하는 에이전트입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【중요: 최대 라운드 = {max_rounds}】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 이 케이스는 정확히 {max_rounds}라운드까지만 실행합니다.
★ 라운드 {max_rounds} 판정 완료 후 → 즉시 단계 10(예방책 생성)으로 이동
★ 라운드 {max_rounds + 1}은 절대 실행 금지

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【실행 단계】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

단계 1: 엔티티 가져오기
- 도구: sim.fetch_entities
- 입력: {{"data": {{"offender_id": {offender_id}, "victim_id": {victim_id}}}}}
- 저장: scenario, victim_profile

단계 2: 프롬프트 생성 (라운드1)
- 도구: sim.compose_prompts
- 입력: {{"data": {{"scenario": <1단계 scenario>, "victim_profile": <1단계 victim_profile>, "round_no": 1}}}}
- 주의: guidance 필드 포함 금지
- 결과: prompt_id를 받아서 PROMPT_ID_R1 변수에 저장

단계 3: 시뮬레이션 실행 (라운드1)
- 도구: mcp.simulator_run
- 입력: {{"offender_id": {offender_id}, "victim_id": {victim_id}, "scenario": <1단계 scenario>, "prompt_id": PROMPT_ID_R1, "max_turns": {req.max_turns}, "round_no": 1}}
- 저장: case_id (CASE_ID 변수), turns

단계 4: 판정 (라운드1)
- 도구: admin.make_judgement
- 입력: {{"data": {{"case_id": <3단계 case_id>, "run_no": 1, "turns": <3단계 turns>}}}}
- 저장: 판정 결과 (JUDGEMENT_R1)

단계 4-1: 라운드1 종료 조건 체크
  [A] risk.level == "critical"인가?
      → YES: 즉시 단계 10으로 이동
      → NO: 단계 4-2로
      
  [B] 현재 라운드 == {max_rounds}인가? (1 == {max_rounds}?)
      → YES: 즉시 단계 10으로 이동
      → NO: 단계 5로

단계 5: 가이던스 생성 (라운드2용)
- 도구: admin.generate_guidance
- 입력: {{"data": {{"case_id": CASE_ID, "run_no": 1, "scenario": <1단계 scenario>, "victim_profile": <1단계 victim_profile>}}}}
- 저장: GUIDANCE_R2

▶ 라운드 N 반복 (N=2~{max_rounds})

단계 6: 프롬프트 생성 (라운드N)
- 도구: sim.compose_prompts
- 입력: {{"data": {{"scenario": <1단계 scenario>, "victim_profile": <1단계 victim_profile>, "round_no": N, "guidance": GUIDANCE_R{{N}}}}}}
- 결과: PROMPT_ID_R{{N}} 저장

단계 7: 시뮬레이션 실행 (라운드N)
- 도구: mcp.simulator_run
- 입력: {{"offender_id": {offender_id}, "victim_id": {victim_id}, "scenario": <1단계 scenario>, "prompt_id": PROMPT_ID_R{{N}}, "max_turns": {req.max_turns}, "round_no": N, "case_id_override": CASE_ID, "guidance": {{"type": "A", "text": GUIDANCE_R{{N}}.text}}}}
- 저장: turns

단계 8: 판정 (라운드N)
- 도구: admin.make_judgement
- 입력: {{"data": {{"case_id": CASE_ID, "run_no": N, "turns": <7단계 turns>}}}}
- 저장: JUDGEMENT_R{{N}}

단계 8-1: 라운드N 종료 조건 체크 ← **매우 중요**
  
  [체크 A] risk.level == "critical"인가?
      → YES: **즉시 단계 10으로 이동** (라운드 수 무관)
      → NO: 체크 B로
  
  [체크 B] N == {max_rounds}인가?
      예시: N=5일 때 {max_rounds}=5이면 5 == 5 → TRUE
      → YES: **즉시 단계 10으로 이동** (최대 라운드 도달)
      → NO: 단계 9로 (다음 라운드 준비)

단계 9: 가이던스 생성 (다음 라운드용)
- **진입 조건**: N < {max_rounds} AND risk.level != "critical"
- 도구: admin.generate_guidance
- 입력: {{"data": {{"case_id": CASE_ID, "run_no": N, "scenario": <1단계 scenario>, "victim_profile": <1단계 victim_profile>}}}}
- 저장: GUIDANCE_R{{N+1}}
- **다음**: 단계 6으로 이동 (N을 N+1로 증가)

▶ 종료 단계 (필수)

단계 10: 예방책 생성 ← **필수**
- **진입 조건**: 
  * risk.level == "critical" OR
  * N == {max_rounds}
- 도구: admin.make_prevention
- 입력: {{"data": {{"case_id": CASE_ID, "rounds": N, "turns": [모든라운드turns], "judgements": [모든judgement], "guidances": [모든guidance]}}}}
- 저장: prevention_result

단계 11: 예방책 저장 ← **필수**
- 도구: admin.save_prevention
- 입력: {{"data": {{"case_id": CASE_ID, "offender_id": {offender_id}, "victim_id": {victim_id}, "run_no": N, "summary": <10단계 summary>, "steps": <10단계 steps>}}}}

단계 12: Final Answer
- 모든 단계 완료 후 최종 요약

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【중요 규칙】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **라운드 카운터 N 추적**
   - 라운드1: N=1
   - 라운드2: N=2
   - 라운드3: N=3
   - 라운드4: N=4
   - 라운드5: N=5 (최대)
   - N이 {max_rounds}에 도달하면 단계 10으로

2. **종료 조건 우선순위**
   - 1순위: risk.level == "critical" → 즉시 단계 10
   - 2순위: N == {max_rounds} → 즉시 단계 10
   - 3순위: 계속 진행 (N < {max_rounds} AND not critical)

3. **변수 재사용**
   - scenario, victim_profile: 1단계에서 받아서 모든 라운드 재사용
   - CASE_ID: 단계 3에서 받아서 모든 후속 단계 재사용
   - PROMPT_ID_RN: 각 라운드마다 새로 생성
   - GUIDANCE_RN: 이전 라운드 판정 기반 생성

4. **도구별 입력 형식**
   - mcp.simulator_run: data 래핑 없음
   - 나머지 도구: {{"data": {{...}}}} 형식

5. **Action Input 작성**
   - 반드시 한 줄로 작성
   - 줄바꿈, 들여쓰기, 주석 금지

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【실행 흐름 예시 - max_rounds={max_rounds}】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

초기화: 1 (엔티티 로드)

라운드1:
  2→3→4→4-1 체크: critical? NO, 1=={max_rounds}? NO → 5

라운드2:
  6→7→8→8-1 체크: critical? NO, 2=={max_rounds}? NO → 9→6

라운드3:
  6→7→8→8-1 체크: critical? NO, 3=={max_rounds}? NO → 9→6

라운드4:
  6→7→8→8-1 체크: critical? NO, 4=={max_rounds}? NO → 9→6

라운드5:
  6→7→8→8-1 체크: critical? NO, 5=={max_rounds}? YES → **10**

종료: 10 (예방책 생성) → 11 (예방책 저장) → 12 (Final Answer)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【조기 종료 예시 - critical 발생】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

라운드3에서 critical 발생 시:
  6→7→8→8-1 체크: critical? YES → **즉시 10**

종료: 10 (예방책 생성) → 11 (예방책 저장) → 12 (Final Answer)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【절대 금지 사항】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ 라운드 {max_rounds + 1} 실행 금지
❌ 단계 10, 11 생략 금지
❌ N > {max_rounds} 상태 진입 금지

**핵심**: 라운드 {max_rounds} 판정(단계 8) 완료 후 → 무조건 단계 10

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【Final Answer 작성 조건】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
다음을 **모두 완료**한 후에만 Final Answer 작성:
✓ admin.make_prevention 호출 및 Observation 확인
✓ admin.save_prevention 호출 및 Observation 확인

위 2개 도구를 호출하지 않고 Final Answer 작성 시 **포맷 오류**로 처리됩니다.
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

            logger.info(f"[DEBUG] ===== cap.events 전체 ({len(cap.events)}개) =====")
            for i, ev in enumerate(cap.events):
                logger.info(f"[DEBUG] Event {i}: type={ev.get('type')}, tool={ev.get('tool', 'N/A')}")

            for ev in cap.events:
                if ev.get("type") == "observation":
                    tool_name = ev.get("tool")
                    output = ev.get("output")
                    logger.info(f"[DEBUG] Observation detected: tool={tool_name}, output_len={len(str(output))}")
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
                    
                    # mcp.simulator_run 결과 처리: 대화 로그를 testdb + TTS 캐시에 저장
                    elif tool_name == "mcp.simulator_run":
                        sim_run_idx += 1
                        logger.info(f"[DEBUG] mcp.simulator_run 처리 시작: sim_run_idx={sim_run_idx}")
                        logger.info(f"[DEBUG] output 타입: {type(output)}")
                        logger.info(f"[DEBUG] output 길이: {len(str(output))}")
                        # 1) MCP 결과 파싱
                        sim_dict = _loose_parse_json(output)
                        if not isinstance(sim_dict, dict):
                            logger.warning(
                                "[MCP] simulator_run output이 dict가 아님: type=%s value=%s",
                                type(sim_dict).__name__,
                                _truncate(sim_dict, 300),
                            )
                            continue
                        logger.info(f"[DEBUG] sim_dict keys: {list(sim_dict.keys())}")

                        # 2) data 래퍼 지원: {"ok": true, "data": {...}} 형태 처리
                        body = sim_dict.get("data") if isinstance(sim_dict.get("data"), dict) else sim_dict
                        logger.info(f"[DEBUG] body keys: {list(body.keys())}")


                        # ★★★ log.turns 우선 사용 (중복 구조 해결)
                        if "log" in body and isinstance(body["log"], dict):
                            raw_turns = body["log"].get("turns", [])
                        else:
                            raw_turns = body.get("turns", [])
                        if not isinstance(raw_turns, list) or not raw_turns:
                            logger.warning(
                                "[MCP] simulator_run 결과에 turns 리스트가 없음: keys=%s",
                                list(body.keys()),
                            )
                            continue  # turns 없으면 저장/캐시도 의미 없음

                        # case_id / stats / ended_by는 body 기준으로 우선
                        sim_case_id = body.get("case_id") or case_id
                        stats = body.get("stats") or {}
                        ended_by = body.get("ended_by")
                        # ★★★ victim dialogue 추출 (JSON → text)
                        cleaned_turns = []
                        for turn in raw_turns:
                            role = turn.get("role", "")
                            text = turn.get("text", "")
                            
                            # victim의 JSON 응답 처리
                            if role == "victim" and text.strip().startswith("{"):
                                try:
                                    victim_json = json.loads(text)
                                    text = victim_json.get("dialogue", text)
                                except:
                                    pass
                            
                            cleaned = {
                                "role": role,
                                "text": text,
                            }

                            # 🔊 TTS용 성별/나이 정보 주입
                            if role == "victim":
                                cleaned["gender"] = victim_gender       # "male"/"female"
                                if victim_age_group:
                                    cleaned["age_group"] = victim_age_group
                            elif role == "offender":
                                cleaned["gender"] = offender_gender     # "male"/"female"

                            cleaned_turns.append(cleaned)
                        turns_all.extend(cleaned_turns)

                        # ── SSE: 라운드 단위 대화 전달 (TTS 모달 버튼 생성용) ─────────────
                        try:
                            _emit_to_stream(
                                "conversation_round",
                                {
                                    "case_id": str(sim_case_id) if sim_case_id else None,
                                    "run_no": sim_run_idx,
                                    "turns": _truncate(cleaned_turns, 2000),
                                    "ended_by": ended_by,
                                    "stats": _truncate(stats, 2000),
                                },
                            )
                        except Exception as e:
                            logger.warning(f"[SSE] conversation_round emit 실패: {e}")

                        # ── DB 저장 (라운드별: conversation_round) ───────────────────────
                        try:
                            round_row = (
                                db.query(m.ConversationRound)
                                .filter(
                                    m.ConversationRound.case_id == sim_case_id,
                                    m.ConversationRound.run == sim_run_idx,
                                )
                                .first()
                            )
                            if not round_row:
                                round_row = m.ConversationRound(
                                    case_id=sim_case_id,
                                    run=sim_run_idx,
                                    offender_id=offender_id,
                                    victim_id=victim_id,
                                    turns=cleaned_turns,
                                    ended_by=ended_by,
                                    stats=stats,
                                )
                                db.add(round_row)
                            else:
                                round_row.turns = cleaned_turns
                                round_row.ended_by = ended_by
                                round_row.stats = stats
                            db.commit()
                            logger.info(
                                "[DB] ConversationRound stored: case_id=%s run=%s turns=%s",
                                sim_case_id,
                                sim_run_idx,
                                len(cleaned_turns),
                            )
                        except Exception as e:
                            logger.warning(f"[DB] round {sim_run_idx} 저장 실패: {e}")

                        # ── DB 저장 (턴 단위: conversationlog) ────────────────────────────
                        try:
                            (
                                db.query(m.ConversationLog)
                                .filter(
                                    m.ConversationLog.case_id == sim_case_id,
                                    m.ConversationLog.run == sim_run_idx,
                                )
                                .delete(synchronize_session=False)
                            )

                            for idx, turn in enumerate(cleaned_turns, start=1):
                                role = (turn.get("role") or "").strip() or "unknown"
                                text = turn.get("text") or ""

                                log_row = m.ConversationLog(
                                    case_id=sim_case_id,
                                    offender_id=offender_id,
                                    victim_id=victim_id,
                                    turn_index=idx,
                                    role=role,
                                    content=text,
                                    label=None,
                                    payload=turn,
                                    use_agent=True,
                                    run=sim_run_idx,
                                    guidance_type=None,
                                    guideline=None,
                                )
                                db.add(log_row)

                            db.commit()
                            logger.info(
                                "[DB] ConversationLog stored: case_id=%s run=%s turns=%s",
                                sim_case_id,
                                sim_run_idx,
                                len(cleaned_turns),
                            )
                        except Exception as e:
                            logger.warning(
                                "[DB] ConversationLog 저장 실패: case_id=%s run=%s error=%s",
                                sim_case_id,
                                sim_run_idx,
                                e,
                            )

                        # ✅ TTS용 메모리 캐시에 라운드별 대화 저장
                        try:
                            cache_run_dialog(
                                case_id=str(sim_case_id),
                                run_no=sim_run_idx,
                                turns=cleaned_turns,
                                victim_age=victim_meta.get("age"),
                                victim_gender=victim_gender,
                            )
                            logger.info(
                                "[TTS_CACHE] cached dialog for case_id=%s run_no=%s (turns=%s, age=%s, gender=%s)",
                                sim_case_id,
                                sim_run_idx,
                                len(cleaned_turns),
                                victim_meta.get("age"),
                                victim_gender,
                            )
                        except Exception as e:
                            logger.warning(
                                "[TTS_CACHE] cache_run_dialog failed for case_id=%s run_no=%s: %s",
                                sim_case_id,
                                sim_run_idx,
                                e,
                            )
                    
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

            # 6. 실행 완료 검증
            validation = _validate_complete_execution(cap, max_rounds)
            if not validation["is_complete"]:
                logger.warning(
                    f"[Validation] 누락된 단계: {validation['missing_steps']}\n"
                    f"[Validation] 호출된 도구: {validation['tool_counts']}"
                )
                _emit_to_stream("validation_warning", {
                    "type": "incomplete_execution",
                    "missing_steps": validation["missing_steps"],
                    "tool_counts": validation["tool_counts"],
                    "message": "에이전트가 일부 필수 단계를 건너뛰었습니다. 프롬프트 개선이 필요합니다."
                })
            else:
                logger.info("[Validation] 모든 필수 단계 완료 확인")

            # 7. 예방책 추출
            prevention_obj = _extract_prevention_from_last_observation(cap)

            if not prevention_obj:
                logger.error(
                    "[Prevention] 에이전트가 make_prevention을 호출하지 않았습니다.\n"
                    "[Prevention] 프롬프트 엔지니어링 개선이 필요합니다.\n"
                    f"[Prevention] 호출된 도구: {validation['tool_counts']}"
                )
                _emit_to_stream("error", {
                    "type": "missing_prevention",
                    "message": "예방책 생성이 누락되었습니다",
                    "validation": validation
                })
            
            # 8. 예방책 SSE 및 finished_chain emit
            if prevention_obj:
                logger.info("[Prevention] 예방책 최종 확보 완료")
                # 프론트에서 바로 사용할 수 있도록 prevention 이벤트도 전송
                _emit_to_stream("prevention", prevention_obj)

                _emit_to_stream("finished_chain", {
                    "case_id": case_id,
                    "rounds": rounds_done,
                    "finished_reason": finished_reason,
                    "prevention": _truncate(prevention_obj, 2000),
                })
            else:
                logger.warning("[Prevention] 예방책 객체를 끝내 확보하지 못했습니다.")

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
                "round_judgements": judgements_history,  # ★ 라운드별 판정 요약
            }

            with contextlib.suppress(Exception):
                _emit_run_end("success", {"case_id": case_id, "rounds": rounds_done})
                _emitted_run_end = True

            return result_obj

    finally:
        with contextlib.suppress(Exception):
            case_id = locals().get("case_id")
            if case_id:
                # 이 케이스 관련 프롬프트 캐시만 정리
                keys_to_remove = [k for k in _PROMPT_CACHE.keys() if case_id in k or "round_" in k]
                for k in keys_to_remove:
                    _PROMPT_CACHE.pop(k, None)
                logger.info(f"[PromptCache] 정리: {len(keys_to_remove)}개 항목 제거")

                # 🔊 TTS용 대화 캐시도 함께 정리
                try:
                    clear_case_dialog_cache(str(case_id))
                except Exception as e:
                    logger.warning("[TTS_CACHE] clear_case_dialog_cache 실패: case_id=%s error=%s", case_id, e)
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