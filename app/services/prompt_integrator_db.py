# app/services/prompt_integrator_db.py
from __future__ import annotations
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.schemas.simulation_request import SimulationStartRequest
from app.db import models as m
import os
from fastapi import HTTPException

ATTACKER_TEMPLATE_NAME = "ATTACKER_PROMPT_V1"
VICTIM_TEMPLATE_NAME   = "VICTIM_PROMPT_V1"

SAFETY_LINE = (
    "[규칙] 실제 기관/계좌/전화번호/링크는 금지(가명/더미만 사용). "
    "앱 설치/링크 요구는 명시적 문장으로만 표현.\n"
)

# ─────────────────────────────────────────────────────────
# 유틸: 더미 값/스키마 잔여물 정리
# ─────────────────────────────────────────────────────────
def _is_dummy(x: Any) -> bool:
    return isinstance(x, str) and x.strip().lower() == "string"

def _clean_text(x: Any) -> str:
    return "" if _is_dummy(x) else (x or "")

def _strip_schema_dummy(d: Any) -> Any:
    # {"additionalProp1": {}} 같은 스키마 더미 제거
    if isinstance(d, dict) and list(d.keys()) == ["additionalProp1"]:
        return {}
    return d

def _is_effectively_empty(d: Any) -> bool:
    """빈 dict, 더미(string/additionalProp1)만 있는 경우 True"""
    if not d or not isinstance(d, dict):
        return True
    for _, v in d.items():
        if v in (None, "", {}, [], {"additionalProp1": {}}):
            continue
        if _is_dummy(v):
            continue
        return False
    return True

def _norm_scenario(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = raw or {}
    desc    = _clean_text(raw.get("description") or raw.get("text"))
    purpose = _clean_text(raw.get("purpose") or raw.get("type"))
    steps   = raw.get("steps") or raw.get("objectives") or []
    if not isinstance(steps, list):
        steps = []
    steps = [s for s in steps if isinstance(s, str) and not _is_dummy(s)]
    return {"description": desc, "purpose": purpose, "steps": steps}

def _norm_victim_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = raw or {}
    return {
        "meta":      _strip_schema_dummy(raw.get("meta")      or {}),
        "knowledge": _strip_schema_dummy(raw.get("knowledge") or {}),
        "traits":    _strip_schema_dummy(raw.get("traits")    or {}),
    }

# ─────────────────────────────────────────────────────────
# DB 로딩
# ─────────────────────────────────────────────────────────
def load_victim_profile(db: Session, req: SimulationStartRequest) -> Dict[str, Any]:
    # 빈 custom이면 무시하고 DB 조회
    if getattr(req, "custom_victim", None) and not _is_effectively_empty(req.custom_victim):
        cv = req.custom_victim
        if hasattr(cv, "model_dump"):
            cv = cv.model_dump()
        return _norm_victim_profile(cv)

    assert req.victim_id is not None, "victim_id가 필요합니다(커스텀 피해자 없음)."
    vic = db.get(m.Victim, int(req.victim_id))
    if not vic:
        raise HTTPException(400, detail=f"victim_id={req.victim_id} not found")
    if not getattr(vic, "is_active", True):
        raise HTTPException(400, detail=f"victim_id={req.victim_id} is not active")

    return _norm_victim_profile({
        "meta": vic.meta or (getattr(vic, "body", {}) or {}).get("meta", {}),
        "knowledge": vic.knowledge or (getattr(vic, "body", {}) or {}).get("knowledge", {}),
        "traits": vic.traits or (getattr(vic, "body", {}) or {}).get("traits", {}),
    })

def load_scenario_from_offender(db: Session, offender_id: int) -> Dict[str, Any]:
    off = db.get(m.PhishingOffender, int(offender_id))
    if not off:
        raise HTTPException(400, detail=f"offender_id={offender_id} not found")
    if not getattr(off, "is_active", True):
        raise HTTPException(400, detail=f"offender_id={offender_id} is not active")

    prof = off.profile or {}
    # description 우선순위: name > type > profile.description/text > 기본
    description = (off.name or off.type or prof.get("description") or prof.get("text") or "일반 시나리오")
    purpose     = prof.get("purpose") or "미상"
    steps       = prof.get("steps") or []
    if not isinstance(steps, list):
        steps = [str(steps)] if steps else []

    base = {"description": description, "purpose": purpose, "steps": steps}
    return _norm_scenario(base)

def build_custom_scenario(seed: Dict[str, Any], tavily_out: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # tavily 출력 우선, seed 보완
    scn = {
        "description": (tavily_out or {}).get("description") or seed.get("text") or seed.get("type") or "커스텀 시나리오",
        "purpose":     (tavily_out or {}).get("purpose")     or seed.get("purpose") or "미상",
        "steps":       (tavily_out or {}).get("steps")       or seed.get("objectives") or [],
    }
    return _norm_scenario(scn)

def save_custom_scenario_to_attack(db: Session, scenario: Dict[str, Any]) -> int:
    """
    커스텀 시나리오를 Attack 카탈로그에 저장.
    body 필드에 통째로 넣고 title은 description 앞부분을 사용.
    """
    title = str(scenario.get("description") or "custom").strip()
    atk = m.Attack(title=title[:150] or "custom", category="custom", body=scenario, is_active=True)
    db.add(atk); db.commit(); db.refresh(atk)
    return int(atk.id)

# ─────────────────────────────────────────────────────────
# 프롬프트 생성 + 통짜 프롬프트
# ─────────────────────────────────────────────────────────
def _build_attacker_prompt(scn: Dict[str, Any], guidance: Optional[Dict[str, str]]) -> str:
    step_lines = "\n".join(f"- {s}" for s in (scn.get("steps") or [])) or "(없음)"
    g = ""
    if guidance and (guidance.get("type") or "").upper() == "A" and guidance.get("text"):
        g = f"\n[지침-공격자]\n{guidance['text']}\n"
    return (
        "[보이스피싱 시뮬레이션]\n"
        f"{SAFETY_LINE}"
        f"[시나리오]\n{scn.get('description') or '(설명 없음)'}\n"
        f"[목적]\n{scn.get('purpose') or '(목적 없음)'}\n"
        f"[현재 단계 목록]\n{step_lines}\n"
        "[역할] 너는 공격자(피싱범)다. 현재 단계 범위 안에서만 말하고, 실제 정보는 생성하지 마라."
        + g
    )

def _build_victim_prompt(vpf: Dict[str, Any], guidance: Optional[Dict[str, str]]) -> str:
    g = ""
    if guidance and (guidance.get("type") or "").upper() == "P" and guidance.get("text"):
        g = f"\n[지침-피해자]\n{guidance['text']}\n"
    return (
        "[보이스피싱 시뮬레이션]\n"
        f"{SAFETY_LINE}"
        "[피해자 프로파일]\n"
        f"메타: {vpf.get('meta')}\n"
        f"지식: {vpf.get('knowledge')}\n"
        f"성격: {vpf.get('traits')}\n"
        "[역할] 너는 피해자다. 현실적 대응을 하되 실제 개인정보/계좌/링크/번호는 만들지 마라."
        + g
    )

def _combine(ap: str, vp: str) -> str:
    # MCP 서버 분리기(_split_combined_prompt)가 인식하는 마커
    return f"[ATTACKER]\n{ap}\n[/ATTACKER]\n[VICTIM]\n{vp}\n[/VICTIM]"

# ─────────────────────────────────────────────────────────
# 단일 진입점: 프롬프트 패키지 + MCP arguments 생성
# ─────────────────────────────────────────────────────────
def build_prompt_package_from_payload(
    db: Session,
    req: SimulationStartRequest,
    tavily_result: Optional[Dict[str, Any]] = None,
    *,
    is_first_run: bool = False,
    skip_catalog_write: bool = True,
    enable_scenario_enhancement: bool = True
) -> Dict[str, Any]:
    victim_profile = load_victim_profile(db, req)

    # 시나리오 로딩
    if getattr(req, "custom_scenario", None):
        seed = req.custom_scenario.model_dump()
        scenario = build_custom_scenario(seed, tavily_result)
        if is_first_run and not skip_catalog_write:
            _ = save_custom_scenario_to_attack(db, scenario)
    else:
        assert req.offender_id is not None
        scenario = load_scenario_from_offender(db, req.offender_id)

    # 🔥 시나리오 개선 적용
    if enable_scenario_enhancement and is_first_run:
        from app.services.inhanced_scenario_builder import ScenarioEnhancer
        enhancer = ScenarioEnhancer()
        scenario = enhancer.enhance_scenario_with_guidance(
            db=db, base_scenario=scenario, victim_profile=victim_profile)

    # 지침 정규화
    guidance = None
    if getattr(req, "guidance", None):
        g = req.guidance
        if hasattr(g, "model_dump"):
            g = g.model_dump()
        if isinstance(g, dict):
            guidance = {"type": (g.get("type") or "").upper(), "text": g.get("text") or ""}

    # 프롬프트 생성
    attacker_prompt = getattr(req, "attacker_prompt", None)
    victim_prompt   = getattr(req, "victim_prompt", None)
    if not attacker_prompt or not victim_prompt:
        from app.services.prompt_integrator_db import _build_attacker_prompt, _build_victim_prompt, _combine
        attacker_prompt = _build_attacker_prompt(scenario, guidance)
        victim_prompt   = _build_victim_prompt(victim_profile, guidance)

    from app.services.prompt_integrator_db import _combine
    combined_prompt = _combine(attacker_prompt, victim_prompt)

    # 모델/턴수
    attacker_model = (getattr(req, "models", {}) or {}).get("attacker") or os.getenv("ATTACKER_MODEL","gpt-4o-mini")
    victim_model   = (getattr(req, "models", {}) or {}).get("victim")   or os.getenv("VICTIM_MODEL","gpt-4o-mini")
    max_turns      = getattr(req, "max_turns", None) or 15

    # MCP 인자 구성
    mcp_args = {
        "offender_id": req.offender_id,
        "victim_id": req.victim_id,
        "scenario": scenario,
        "victim_profile": victim_profile,
        "templates": {"attacker": attacker_prompt, "victim": victim_prompt},
        "combined_prompt": combined_prompt,
        "max_turns": max_turns,
        "models": {"attacker": attacker_model, "victim": victim_model},
    }
    if getattr(req, "case_id_override", None):
        mcp_args["case_id_override"] = str(req.case_id_override)
    if getattr(req, "round_no", None):
        mcp_args["round_no"] = int(req.round_no)
    if guidance:
        mcp_args["guidance"] = guidance
    mcp_args["attacker_prompt"] = attacker_prompt
    mcp_args["victim_prompt"]   = victim_prompt

    return {
        "scenario": scenario,
        "victim_profile": victim_profile,
        "templates": {"attacker": attacker_prompt, "victim": victim_prompt},
        "attacker_prompt": attacker_prompt,
        "victim_prompt": victim_prompt,
        "combined_prompt": combined_prompt,
        "attacker_model": attacker_model,
        "victim_model": victim_model,
        "max_turns": max_turns,
        "mcp_args": mcp_args,
    }

