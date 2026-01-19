# vp_mcp/mcp_server/llm/providers.py
from __future__ import annotations
from typing import Optional, Dict, Any, List

import os
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from app.core.logging import get_logger
logger = get_logger(__name__)

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

# ─────────────────────────────────────────────────────────
# 내부 유틸 (app/services/llm_providers.py 로직을 MCP에 맞게 이식)
# ─────────────────────────────────────────────────────────

# STOP_SAFE_DEFAULT = "gpt-4o-2024-08-06"  # 안정판 (참고용)

def _openai_like_chat(model: str, base_url: str, api_key: str, temperature: float = 0.7) -> BaseChatModel:
    """
    OpenAI 호환 엔드포인트(로컬 서버 등)에 붙을 때 사용.
    """
    if not api_key:
        raise RuntimeError("LOCAL_API_KEY not set for local provider")
    if not base_url:
        raise RuntimeError("LOCAL_BASE_URL not set for local provider")
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=600000,
    )

def _openai_chat(model: Optional[str] = None, temperature: float = 0.7) -> BaseChatModel:
    """
    OpenAI 정식 엔드포인트. o-시리즈는 temperature=1로 강제 (네 기존 코드 반영)
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    mdl = (model or os.getenv("ADMIN_MODEL")).strip()
    is_o_series = mdl.lower().startswith("o")  # "o4-mini", "o3-mini", "o1" 등

    if is_o_series:
        # 응답 API 계열은 temp=1 명시
        return ChatOpenAI(model=mdl, temperature=1, api_key=api_key, timeout=6000)
    else:
        return ChatOpenAI(model=mdl, temperature=temperature, api_key=api_key, timeout=600000)

def _gemini_chat(model: Optional[str] = None, temperature: float = 0.7) -> BaseChatModel:
    """
    Google Gemini.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return ChatGoogleGenerativeAI(
        model=model or "gemini-2.5-flash-lite",
        google_api_key=api_key,
        temperature=temperature,
        timeout=600000,
    )

def attacker_chat(model: Optional[str] = None, temperature: float = 0.7) -> BaseChatModel:
    """
    공격자 LLM. 기본은 OpenAI.
    """
    mdl = model or os.getenv("ATTACKER_MODEL") or "gpt-4o-mini-2024-07-18"
    return _openai_chat(mdl, temperature=temperature)

def victim_chat() -> BaseChatModel:
    """
    피해자 LLM. provider 선택 가능: openai | gemini | local
    - local 은 OpenAI 호환 서버 (base_url + api_key 필요)
    """
    provider = (os.getenv("VICTIM_PROVIDER", "gemini") or "gemini").lower()
    model = os.getenv("VICTIM_MODEL")

    if provider == "gemini":
        return _gemini_chat(model, temperature=0.7)
    if provider == "local":
        return _openai_like_chat(
            model,
            os.getenv("LOCAL_BASE_URL", ""),
            os.getenv("LOCAL_API_KEY", ""),
            temperature=0.7,
        )
    if provider == "openai":
        return _openai_chat(model, temperature=0.7)

    raise ValueError(f"Unsupported VICTIM_PROVIDER: {provider}. Use 'openai' | 'gemini' | 'local'.")

def agent_chat(model: Optional[str] = None, temperature: float = 0.2) -> BaseChatModel:
    """
    에이전트/플래너용 (여기서는 필요시 사용). ReAct는 저온 권장.
    alias 맵은 필요하면 추가.
    """
    name = model or os.getenv("AGENT_MODEL")
    alias_map = {
        "o4-mini": "gpt-4o-mini-2024-07-18",
        "o4": "gpt-4o-2024-08-06",
    }
    name = alias_map.get(name, name)
    return _openai_chat(name, temperature=temperature)

# ─────────────────────────────────────────────────────────
# 시뮬용 래퍼 클래스 (simulate_dialogue.py에서 사용)
# ─────────────────────────────────────────────────────────

def _compose_turn_prompt(
    role: str,
    *,
    last_peer_text: str,
    current_step: str,
    guidance: str,
    guidance_type: str,
    victim_meta: Optional[Dict[str, Any]] = None,
    victim_knowledge: Optional[Dict[str, Any]] = None,
    victim_traits: Optional[Dict[str, Any]] = None,
) -> str:
    """
    한 턴 프롬프트 합성 (공격자/피해자 공통)
    """
    lines = []
    if current_step:
        lines.append(f"[Step]\n{current_step}")
    if guidance:
        lines.append(f"[Guidance type={guidance_type or '-'}]\n{guidance}")
    if last_peer_text:
        peer = "Victim" if role == "attacker" else "Offender"
        lines.append(f"[Last {peer}]\n{last_peer_text}")
    if role == "victim":
        if victim_meta:
            lines.append(f"[Victim Meta]\n{victim_meta}")
        if victim_knowledge:
            lines.append(f"[Victim Knowledge]\n{victim_knowledge}")
        if victim_traits:
            lines.append(f"[Victim Traits]\n{victim_traits}")
    lines.append("[Instruction]\nRespond with one concise turn, staying in character.")
    return "\n\n".join(lines)

class _BaseLLM:
    def __init__(self, *, model: str, system: str, temperature: float):
        self.model_name = model
        self.temperature = temperature
        self.system = system

        # 모델명 접두로 프로바이더 선택 (app 코드 정책 반영)
        m = (model or "").lower()
        if m.startswith(("gpt", "o", "openai")):
            provider = "openai"
            self.llm: BaseChatModel = _openai_chat(model, temperature)
        elif m.startswith("gemini"):
            provider = "gemini"
            self.llm = _gemini_chat(model, temperature)
        else:
            # 기본은 OpenAI
            provider = "openai(default)"
            self.llm = _openai_chat(model or "gpt-4o-mini-2024-07-18", temperature)
        logger.info(f"[LLM:init] model={model} provider={provider} temperature={temperature}")

    def _invoke(self, messages: List):
        logger.info(f"[LLM:invoke] model={self.model_name} len_messages={len(messages)}")
        res = self.llm.invoke(messages)
        out = getattr(res, "content", str(res)).strip()
        logger.info(f"[LLM:done] model={self.model_name} out_len={len(out)}")
        return out

class AttackerLLM(_BaseLLM):
    def next(
        self,
        *,
        history: List,                 # [AIMessage/HumanMessage ...] (공격자 퍼스펙티브)
        last_victim: str,
        current_step: str,
        guidance: str,
        guidance_type: str,
    ) -> str:
        messages: List = [SystemMessage(self.system)]
        messages.extend(history or [])
        prompt = _compose_turn_prompt(
            "attacker",
            last_peer_text=last_victim,
            current_step=current_step,
            guidance=guidance,
            guidance_type=guidance_type,
        )
        messages.append(HumanMessage(prompt))
        return self._invoke(messages)

class VictimLLM(_BaseLLM):
    def next(
        self,
        *,
        history: List,                 # [AIMessage/HumanMessage ...] (피해자 퍼스펙티브)
        last_offender: str,
        meta: Optional[Dict[str, Any]],
        knowledge: Optional[Dict[str, Any]],
        traits: Optional[Dict[str, Any]],
        guidance: str,
        guidance_type: str,
    ) -> str:
        messages: List = [SystemMessage(self.system)]
        messages.extend(history or [])
        prompt = _compose_turn_prompt(
            "victim",
            last_peer_text=last_offender,
            current_step="",
            guidance=guidance,
            guidance_type=guidance_type,
            victim_meta=meta,
            victim_knowledge=knowledge,
            victim_traits=traits,
        )
        messages.append(HumanMessage(prompt))
        return self._invoke(messages)
