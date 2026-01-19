# app/services/agent/orchestrator_mcp.py (중 요지 변경분만)
from __future__ import annotations
from typing import Dict, Any, List, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
import json
from app.core.config import settings
from app.db import models as m
from app.services.mcp.sim_client import get_simulator
from app.services.prompt_builder import build_attacker_block, build_victim_block, build_payload_for_simulator
from app.services.webctx import fetch_web_context_if_needed
from app.services.prompts_agent import AGENT_PLANNER_PROMPT, AGENT_POSTRUN_ASSESSOR_PROMPT
from app.services.llm_providers import agent_chat


# --- LangSmith/LC tracing helper ---
def _with_trace(runnable, *, case_id: UUID, run_no: int, phase: str):
    return runnable.with_config({
        "metadata": {
            "case_id": str(case_id),
            "run": run_no,
            "phase": phase
        },
        "tags": [phase, f"case:{case_id}", f"run:{run_no}"]
    })


# --- 신호 기반 간이 리스크 추정 ---
_KEYWORDS_ATTACK = [
    "안전계좌", "원격", "앱 설치", "인증번호", "otp", "보안카드", "검찰", "금감원", "대환대출", "상품권",
    "qr", "링크"
]
_KEYWORDS_DEFENSE = [
    "신고", "차단", "대표번호", "지점 방문", "사기", "보이스피싱", "경찰", "끊겠습니다", "확인해보겠습니다"
]


def _extract_signals(rows: List[m.ConversationLog]) -> Dict[str, Any]:
    atk = defn = 0
    for r in rows:
        t = (r.content or "").lower()
        for kw in _KEYWORDS_ATTACK:
            if kw.lower() in t: atk += 1
        for kw in _KEYWORDS_DEFENSE:
            if kw.lower() in t: defn += 1
    # 간단 점수
    import math
    score = 1 / (1 + math.exp(-(atk - defn)))
    if atk == 0 and defn >= 1: level = "low"
    elif score < 0.45: level = "low"
    elif score < 0.65: level = "medium"
    else: level = "high"
    return {
        "atk": atk,
        "def": defn,
        "score": float(score),
        "risk_level": level
    }


def _risk_for_run(db: Session, case_id: UUID, run_no: int) -> str:
    rows = (db.query(m.ConversationLog).filter(
        m.ConversationLog.case_id == case_id,
        m.ConversationLog.run == run_no).all())
    return _extract_signals(rows)["risk_level"]


def run_agent_loop(db: Session,
                   *,
                   case_id: UUID,
                   offender_id: int,
                   victim_id: int,
                   attacker_model: str,
                   victim_model: str,
                   base_run: int,
                   scenario: Dict[str, Any],
                   stream_cb=None) -> Dict[str, Any]:
    sim = get_simulator()
    web_ctx = fetch_web_context_if_needed(scenario, settings.ENABLE_WEB_SEARCH)

    outcomes: List[str] = []  # "attacker_success" | "attacker_fail"
    risks: List[str] = []  # "low"|"medium"|"high"
    last_run = base_run
    final_post = {}

    for i in range(1, int(settings.MAX_AGENT_ITER) + 1):
        guidance_type = scenario.get("guidance_type")
        guideline = scenario.get("guideline")

        attacker_block = build_attacker_block(scenario=scenario,
                                              guidance_type=guidance_type,
                                              guideline=guideline,
                                              web_ctx=web_ctx)
        vrow = db.get(m.Victim, victim_id)
        victim_block = build_victim_block(victim={
            "meta": vrow.meta,
            "knowledge": vrow.knowledge,
            "traits": vrow.traits
        },
                                          guidance_type=guidance_type,
                                          guideline=guideline,
                                          web_ctx=web_ctx)
        payload = build_payload_for_simulator(attacker_prompt=attacker_block,
                                              victim_prompt=victim_block,
                                              attacker_model=attacker_model,
                                              victim_model=victim_model,
                                              max_turns=30)

        # 1) 시뮬레이션 (MCP or 폴백)
        try:
            logs = sim.simulate_dialogue(payload) if settings.USE_MCP else []
        except Exception:
            logs = []
        if not logs:
            # 폴백: 기존 엔진 1회
            from .orchestrator import _append_methods_used, _update_case_analysis  # re-use utils
            from app.services.simulation import run_two_bot_simulation
            from types import SimpleNamespace
            args = SimpleNamespace(offender_id=offender_id,
                                   victim_id=victim_id,
                                   include_judgement=True,
                                   max_rounds=30,
                                   case_scenario=scenario,
                                   case_id_override=case_id,
                                   run_no=last_run,
                                   use_agent=True,
                                   guidance_type=guidance_type,
                                   guideline=guideline)
            _cid, _turns = run_two_bot_simulation(db, args)
        else:
            # DB 저장
            from app.services.simulation import _save_turn
            turn = 0
            for it in logs:
                role = "offender" if it["role"] == "offender" else "victim"
                _save_turn(db,
                           case_id,
                           offender_id,
                           victim_id,
                           turn,
                           role,
                           it["text"],
                           use_agent=True,
                           run=last_run,
                           guidance_type=guidance_type,
                           guideline=guideline)
                turn += 1
            db.commit()

        if stream_cb: stream_cb({"type": "run_complete", "run": last_run})

        # 2) Planner (LangSmith trace on)
        planner = _with_trace(AGENT_PLANNER_PROMPT | agent_chat(),
                              case_id=case_id,
                              run_no=last_run,
                              phase="planner")
        resp = planner.invoke({
            "scenario_json":
            json.dumps(scenario, ensure_ascii=False),
            "logs_json":
            _json_logs_for_run(db, case_id, last_run),
        })
        plan = json.loads(getattr(resp, "content", str(resp)).strip())
        outcomes.append(plan.get("outcome") or "attacker_fail")

        # run 리스크 측정(간이)
        risks.append(_risk_for_run(db, case_id, last_run))

        # 프리뷰 스트림
        if stream_cb:
            stream_cb({
                "type": "plan",
                "run": last_run,
                "preview": {
                    "phishing": plan.get("phishing"),
                    "outcome": plan.get("outcome"),
                    "reasons": (plan.get("reasons") or [])[:5],
                    "guidance": (plan.get("guidance") or {})
                }
            })

        # 종료 판단: 최근 2회 연속 실패 + 최근 리스크 "low"
        if len(outcomes) >= 2 and outcomes[-1] == outcomes[
                -2] == "attacker_fail" and risks[-1] == "low":
            assessor = _with_trace(AGENT_POSTRUN_ASSESSOR_PROMPT
                                   | agent_chat(),
                                   case_id=case_id,
                                   run_no=last_run,
                                   phase="assessor")
            aresp = assessor.invoke({
                "scenario_json":
                json.dumps(scenario, ensure_ascii=False),
                "logs_json":
                _json_logs_for_run(db, case_id, last_run),
            })
            final_post = json.loads(
                getattr(aresp, "content", str(aresp)).strip())
            break

        # 다음 루프용 지침 주입
        g = plan.get("guidance") or {}
        scenario["guidance_type"] = g.get("type")
        scenario["guideline"] = g.get("text")
        last_run += 1

        # 최대 반복 도달 시 마무리
        if i == int(settings.MAX_AGENT_ITER):
            assessor = _with_trace(AGENT_POSTRUN_ASSESSOR_PROMPT
                                   | agent_chat(),
                                   case_id=case_id,
                                   run_no=last_run - 1,
                                   phase="assessor")
            aresp = assessor.invoke({
                "scenario_json":
                json.dumps(scenario, ensure_ascii=False),
                "logs_json":
                _json_logs_for_run(db, case_id, last_run - 1),
            })
            final_post = json.loads(
                getattr(aresp, "content", str(aresp)).strip())
            break

    return {"case_id": case_id, "final": final_post, "last_run": last_run}


# 보조: 기존 util 재사용
from sqlalchemy import asc


def _json_logs_for_run(db: Session, case_id: UUID, run_no: int) -> str:
    rows = (db.query(m.ConversationLog).filter(
        m.ConversationLog.case_id == case_id,
        m.ConversationLog.run == run_no).order_by(
            asc(m.ConversationLog.turn_index),
            asc(m.ConversationLog.created_at)).all())
    items = [{
        "turn": r.turn_index,
        "role": r.role,
        "text": r.content
    } for r in rows]
    return json.dumps(items, ensure_ascii=False)
