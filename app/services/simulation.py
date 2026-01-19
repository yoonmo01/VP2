# app/services/simulation.py

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional
from uuid import UUID
import re
import os
from datetime import datetime
import json as _json

from sqlalchemy.orm import Session
from sqlalchemy import func  # ← max(run) 계산용

from app.db import models as m
from app.core.config import settings

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from app.services.llm_providers import attacker_chat, victim_chat
from app.services.admin_summary import summarize_case

# ⬇️ DATA_PROMPT + build_data_prompt_inputs 사용
from app.services.prompts import (
    DATA_PROMPT,
    render_victim_system_string,
    build_data_prompt_inputs,
)

from app.schemas.conversation import ConversationRunRequest

MAX_OFFENDER_TURNS = settings.MAX_OFFENDER_TURNS
MAX_VICTIM_TURNS   = settings.MAX_VICTIM_TURNS

END_TRIGGERS    = [r"마무리하겠습니다"]
VICTIM_END_LINE = "시뮬레이션을 종료합니다."


def _assert_turn_role(turn_index: int, role: str):
    expected = "offender" if turn_index % 2 == 0 else "victim"
    if role != expected:
        raise ValueError(f"Turn {turn_index} must be {expected}, got {role}")


def _parse_offender_output(text: str) -> tuple[str, Optional[str], Dict[str, Any]]:
    """
    DATA_PROMPT 출력(JSON)을 파싱한다.
    - 정상: {"utterance": "...", "intent": "...", "safety_flags": [], ...}
    - 예외: 종료 훅 "여기서 마무리하겠습니다." (순수 텍스트)
    - 비정상: JSON 파싱 실패 시, 기존 규격(INTENT: 라벨) 보조 처리
    반환: (utterance_or_raw, intent_or_None, raw_dict_or_empty)
    """
    s = text.strip()
    # 종료 훅(텍스트 한 줄) 대응
    if s == "여기서 마무리하겠습니다.":
        return s, None, {}

    # JSON 기대
    try:
        data = _json.loads(s)
        if isinstance(data, dict):
            utter = str(data.get("utterance", "")).strip()
            intent = data.get("intent", None)
            return (utter or s), (str(intent).strip() if intent else None), data
    except Exception:
        pass

    # 구식 백업: INTENT 라벨 줄 제거
    m = re.search(r"(?mi)^\s*INTENT:\s*([^\r\n]+)\s*$", s)
    label = None
    if m:
        label = m.group(1).strip()
        s = re.sub(r"(?mi)^\s*INTENT:\s*[^\r\n]+\s*$", "", s).rstrip()
    return s, label, {}


def _save_turn(
    db: Session,
    case_id: UUID,
    offender_id: int,
    victim_id: int,
    turn_index: int,
    role: str,
    content: str,
    label: str | None = None,
    *,
    use_agent: bool = False,
    run: int = 1,
    guidance_type: str | None = None,
    guideline: str | None = None,
    extra_json: Optional[Dict[str, Any]] = None,
):
    _assert_turn_role(turn_index, role)
    log = m.ConversationLog(
        case_id=case_id,
        offender_id=offender_id,
        victim_id=victim_id,
        turn_index=turn_index,
        role=role,
        content=content,
        label=label,
        use_agent=use_agent,
        run=run,
        guidance_type=guidance_type,
        guideline=guideline,
    )
    db.add(log)
    db.commit()
    # (선택) offender의 action_requested 등은 별도 테이블/JSON 저장 구조가 있다면 거기에 넣어도 됨.
    # 여기서는 json_log에만 남긴다.


def _hit_end(text: str) -> bool:
    norm = text.strip()
    return any(re.search(pat, norm) for pat in END_TRIGGERS)


def run_two_bot_simulation(db: Session, req: ConversationRunRequest) -> Tuple[UUID, int]:
    # ── 케이스 준비 ─────────────────────────────────────
    # case_id_override: Optional[UUID] = getattr(req, "case_id_override", None)
    # incoming_scenario: Dict[str, Any] = (
    #     getattr(req, "case_scenario", None)
    #     or getattr(req, "scenario", None)
    #     or {}
    # )

    # if case_id_override:
    #     case = db.get(m.AdminCase, case_id_override)
    #     if not case:
    #         raise ValueError(f"AdminCase {case_id_override} not found")
    #     scenario = (case.scenario or {}).copy()
    #     scenario.update(incoming_scenario)
    #     case.scenario = scenario
    #     db.add(case)
    #     db.commit()
    #     db.refresh(case)
    # else:
    #     case = m.AdminCase(scenario=incoming_scenario)
    #     db.add(case)
    #     db.commit()
    #     db.refresh(case)
    # 항상 "요청에서 온 시나리오"만 사용 (DB 시나리오 병합/읽기 금지)
    incoming_scenario: Dict[str, Any] = (
        getattr(req, "case_scenario", None)
        or getattr(req, "scenario", None)
        or {}
    )
    case = m.AdminCase(scenario=incoming_scenario)
    db.add(case)
    db.commit()
    db.refresh(case)

    offender = db.get(m.PhishingOffender, req.offender_id)
    victim   = db.get(m.Victim,          req.victim_id)
    if offender is None:
        raise ValueError(f"Offender {req.offender_id} not found")
    if victim is None:
        raise ValueError(f"Victim {req.victim_id} not found")

    use_agent: bool = bool(getattr(req, "use_agent", False))

    # run_no_attr = getattr(req, "run_no", None)
    # if run_no_attr is None:
    #     run_no_attr = getattr(req, "round_no", None)

    # if case_id_override:
    #     if run_no_attr is None:
    #         last_run = (
    #             db.query(func.max(m.ConversationLog.run))
    #             .filter(m.ConversationLog.case_id == case.id)
    #             .scalar()
    #         )
    #         run_no = int((last_run or 0) + 1)
    #     else:
    #         run_no = int(run_no_attr)
    # else:
    #     run_no = int(run_no_attr or 1)
    run_no_attr = getattr(req, "run_no", None) or getattr(req, "round_no", None)
    run_no = int(run_no_attr or 1)

    cs: Dict[str, Any] = getattr(req, "case_scenario", None) or getattr(req, "scenario", None) or {}
    guidance_dict: Dict[str, Any] | None = getattr(req, "guidance", None)
    guidance_text: Optional[str] = None
    guidance_type: Optional[str] = None
    if isinstance(guidance_dict, dict):
        guidance_text = guidance_dict.get("text") or None
        guidance_type = guidance_dict.get("type") or None
    if not guidance_text:
        guidance_text = getattr(req, "guideline", None) or cs.get("guideline")
    if not guidance_type:
        guidance_type = getattr(req, "guidance_type", None) or cs.get("guidance_type")

    attacker_llm = attacker_chat()
    victim_llm   = victim_chat()

    victim_profile: Dict[str, Any] = getattr(req, "victim_profile", {}) or {}
    meta_override       = victim_profile.get("meta")
    knowledge_override  = victim_profile.get("knowledge")
    traits_override     = victim_profile.get("traits")

    # 두 모델 각각의 히스토리(LC 메시지)
    history_attacker: list = []
    history_victim:  list  = []

    # previous_turns(문맥) 구성을 위한 단순 구조
    prev_struct: List[Dict[str, str]] = []

    turn_index = 0
    attacks = replies = 0
    turns_executed = 0

    # scenario_all = (getattr(req, "case_scenario", None) or getattr(req, "scenario", None) or {}) if not case_id_override else (case.scenario or {})
    # 위에서 case.scenario = incoming_scenario 로 저장했으므로 동일
    scenario_all = incoming_scenario
    steps: List[str] = (scenario_all.get("steps") or [])
    if not steps:
        raise ValueError("시나리오 steps가 비어 있습니다. request.case_scenario.steps 를 지정하세요.")

    last_victim_text   = ""
    last_offender_text = ""

    # ⬇️ max_rounds 우선
    max_turns = getattr(req, "max_rounds", None) or getattr(req, "max_turns", None) or 15

    guidance_meta = {"text": guidance_text or "", "type": guidance_type or ""} if (guidance_text or guidance_type) else None

    is_convinced_prev: Optional[int] = None
    previous_experience: str = ""

    # JSON 저장용 버퍼
    json_log: Dict[str, Any] = {
        "case_id": str(case.id),
        "run_no": run_no,
        "offender_id": offender.id,
        "victim_id": victim.id,
        "scenario": scenario_all,
        "guidance": {"text": guidance_text, "type": guidance_type},
        "turns": [],  # 각 턴: {turn_index, role, content, label, extra?}
        "meta": {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "max_turns": max_turns,
            "limits": {"offender": MAX_OFFENDER_TURNS, "victim": MAX_VICTIM_TURNS},
        },
    }

    for _ in range(max_turns):
        # ---- 공격자 발화 ----
        if attacks >= MAX_OFFENDER_TURNS:
            break

        # DATA_PROMPT 입력 블록 조립 (최근 6발화만 사용하여 토큰 절약)
        prompt_inputs = build_data_prompt_inputs(
            SCENARIO=scenario_all,          # ⬅️ 키워드 이름 수정
            previous_turns=prev_struct[-6:],
        )

        # DATA_PROMPT 호출
        attacker_chain = DATA_PROMPT | attacker_llm
        attacker_msg = attacker_chain.invoke({
            "history": history_attacker,
            **prompt_inputs,   # scenario_name / previous_turns_block / steps_reference_block
        })
        raw_attacker_text = getattr(attacker_msg, "content", str(attacker_msg)).strip()

        # 파싱(JSON 우선)
        attacker_text, attacker_intent, attacker_raw = _parse_offender_output(raw_attacker_text)

        _save_turn(
            db, case.id, offender.id, victim.id,
            turn_index, "offender", attacker_text,
            label=attacker_intent,
            use_agent=use_agent, run=run_no,
            guidance_type=guidance_type, guideline=guidance_text,
            extra_json=attacker_raw or None,
        )
        json_turn = {
            "turn_index": turn_index,
            "role": "offender",
            "content": attacker_text,
            "label": attacker_intent,
        }
        if attacker_raw:
            # action_requested / safety_flags 등 보존
            for k in ("action_requested", "safety_flags", "referenced_step", "intent"):
                if k in attacker_raw:
                    json_turn[k] = attacker_raw[k]
        json_log["turns"].append(json_turn)

        history_attacker.append(AIMessage(attacker_text))
        history_victim.append(HumanMessage(attacker_text))
        prev_struct.append({"role": "attacker", "text": attacker_text})

        last_offender_text = attacker_text
        turn_index += 1
        attacks += 1

        # 종료 훅 처리
        if _hit_end(attacker_text):
            if replies < MAX_VICTIM_TURNS:
                victim_text = VICTIM_END_LINE
                _save_turn(
                    db, case.id, offender.id, victim.id,
                    turn_index, "victim", victim_text,
                    label=None,
                    use_agent=use_agent, run=run_no,
                    guidance_type=guidance_type, guideline=guidance_text,
                )
                json_log["turns"].append({
                    "turn_index": turn_index,
                    "role": "victim",
                    "content": victim_text,
                    "label": None,
                })
                history_victim.append(AIMessage(victim_text))
                history_attacker.append(HumanMessage(victim_text))
                prev_struct.append({"role": "victim", "text": victim_text})
                last_victim_text = victim_text
                turn_index += 1
                replies += 1
            break

        # ---- 피해자 발화 ----
        if replies >= MAX_VICTIM_TURNS:
            break

        victim_system = render_victim_system_string(
            victim_profile={
                "meta":      (meta_override if meta_override is not None else getattr(victim, "meta", "정보 없음")),
                "knowledge": (knowledge_override if knowledge_override is not None else getattr(victim, "knowledge", "정보 없음")),
                "traits":    (traits_override if traits_override is not None else getattr(victim, "traits", "정보 없음")),
            },
            round_no=run_no,
            previous_experience=previous_experience,
            is_convinced_prev=is_convinced_prev,
        )
        victim_prompt = ChatPromptTemplate.from_messages([
            ("system", "{victim_system}"),
            MessagesPlaceholder("history"),
            ("human", "{last_offender}"),
        ])
        victim_chain = victim_prompt | victim_llm
        victim_msg = victim_chain.invoke({
            "victim_system":  victim_system,
            "history":        history_victim,
            "last_offender":  last_offender_text,
        })
        victim_text = getattr(victim_msg, "content", str(victim_msg)).strip()

        _save_turn(
            db, case.id, offender.id, victim.id,
            turn_index, "victim", victim_text,
            label=None,
            use_agent=use_agent, run=run_no,
            guidance_type=guidance_type, guideline=guidance_text,
        )
        json_log["turns"].append({
            "turn_index": turn_index,
            "role": "victim",
            "content": victim_text,
            "label": None,
        })
        history_victim.append(AIMessage(victim_text))
        history_attacker.append(HumanMessage(victim_text))
        prev_struct.append({"role": "victim", "text": victim_text})

        last_victim_text = victim_text
        turn_index += 1
        replies += 1

        # 피해자 JSON에서 is_convinced 업데이트 시도
        try:
            parsed = _json.loads(victim_text)
            if isinstance(parsed, dict) and isinstance(parsed.get("is_convinced"), int):
                is_convinced_prev = parsed["is_convinced"]
        except Exception:
            pass

        turns_executed += 1

    # 관리자 요약/판정
    summarize_case(db, case.id)

    # ── JSON 파일 저장 ─────────────────────────────────
    out_dir = getattr(settings, "SIM_OUTPUT_DIR", "runs_몸캠")
    os.makedirs(out_dir, exist_ok=True)
    fname = os.path.join(out_dir, f"sim_{case.id}_run{run_no}.json")
    with open(fname, "w", encoding="utf-8") as f:
        _json.dump(json_log, f, ensure_ascii=False, indent=2)

    return case.id, turns_executed
