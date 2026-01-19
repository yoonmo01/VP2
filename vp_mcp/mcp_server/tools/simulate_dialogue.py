from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from ..schemas import SimulationInput, SimulationResult, Turn
from ..llm.providers import AttackerLLM, VictimLLM
from ..db.base import SessionLocal
from ..db.models import Conversation, TurnLog

import json
import re

# FastMCP 등록용
from mcp.server.fastmcp import FastMCP

# 종료 규칙 유틸(단일 진실원)
from vp_mcp.mcp_server.utils.end_rules import (
    attacker_declared_end,      # 공격자 종료 선언 감지 ("여기서 마무리하겠습니다." 변형 포함)
    victim_declared_end,        # 피해자 dialogue 기준 종료 의사 감지
    ATTACKER_TRIGGER_PHRASE,    # "여기서 마무리하겠습니다."
    VICTIM_FINAL_JSON,          # 피해자 마지막 고정 JSON
)

# 하드캡(안전장치). 필요 시 .env로 이관
MAX_OFFENDER_TURNS = 60
MAX_VICTIM_TURNS = 60


# ─────────────────────────────────────────────────────────
# FastMCP에 툴 등록 (server.py에서 호출)
# ─────────────────────────────────────────────────────────
def register_simulate_dialogue_tool_fastmcp(mcp: FastMCP):
    print(">> registering sim.simulate_dialogue and system.echo")

    @mcp.tool(name="system.echo", description="Echo back arguments.")
    async def system_echo(arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "echo": arguments}

    @mcp.tool(
        name="sim.simulate_dialogue",
        description="공격자/피해자 LLM 교대턴 시뮬레이션 실행 후 로그 반환 및 DB 저장"
    )
    async def simulate_dialogue(arguments: Dict[str, Any]) -> Dict[str, Any]:
        # 1) 입력 스키마 검증 (⚠️ 템플릿 주입 payload로 검증해야 실제 system 반영)
        try:
            payload = _coerce_input_legacy(arguments)
            data = SimulationInput.model_validate(payload)
        except ValidationError as ve:
            return {
                "ok": False,
                "error": "validation_error",
                "pydantic_errors": ve.errors(),
                "received": arguments,
            }

        # 2) 실제 실행
        try:
            out = simulate_dialogue_impl(data)
            # out은 dict(평탄화된 결과)로 반환됨. 하위 호환 위해 보호 로직.
            if hasattr(out, "model_dump"):
                core = out.model_dump()
            elif isinstance(out, dict) and "result" in out and len(out) == 1:
                core = out["result"]
            else:
                core = out

            # 최상위에 case_id 동시 제공(오케스트레이터 호환)
            if isinstance(core, dict):
                conv_id = core.get("conversation_id")
                if conv_id and "case_id" not in core:
                    core["case_id"] = conv_id
            return {"ok": True, **core}
        except Exception as e:
            import traceback
            # ❗예외를 밖으로 던지지 말고 JSON으로 반환
            return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def _coerce_input_legacy(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    - templates.attacker / templates.victim 이 '완성된 시스템 프롬프트'면 그대로 system에 주입
    - victim.system이 비어있고 victim_profile가 있다면 victim_profile 기반으로 system을 생성하여 주입
    """
    args = dict(arguments or {})
    attacker = args.get("attacker") or {}
    victim = args.get("victim") or {}
    tpls = (args.get("templates") or {}) if isinstance(args.get("templates"), dict) else {}

    atk_tpl = tpls.get("attacker") or ""
    vic_tpl = tpls.get("victim") or ""

    # 1) 템플릿이 이미 '완성된 system 프롬프트'라면 그대로 사용
    if atk_tpl and not attacker.get("system"):
        attacker["system"] = atk_tpl
    if vic_tpl and not victim.get("system"):
        victim["system"] = vic_tpl

    # 2) 피해자 system이 여전히 비어있다면 victim_profile로 완성
    if not victim.get("system"):
        vp = args.get("victim_profile") or {}
        victim["system"] = _build_victim_system(
            vp.get("meta", "정보 없음"),
            vp.get("knowledge", "정보 없음"),
            vp.get("traits", "정보 없음"),
        )

    args["attacker"] = attacker
    args["victim"] = victim
    return args


def _build_victim_system(meta: Any, knowledge: Any, traits: Any) -> str:
    """
    피해자 LLM용 고정 시스템 프롬프트 (JSON 출력 강제 규칙 포함).
    필요 시 템플릿/로케일에 맞게 확장 가능.
    """
    return (
        "이것은 보이스피싱 시뮬레이션이며, 당신은 피해자 역할입니다.\n\n"
        "[캐릭터 정보]\n"
        f"메타정보: {meta}\n"
        f"지식정보: {knowledge}\n"
        f"성격정보: {traits}\n\n"
        "[응답 규칙]\n"
        "반드시 JSON 한 객체만 출력:\n"
        "{\n"
        '  "is_convinced": 0~10,\n'
        '  "thoughts": "(속마음 한두 문장)",\n'
        '  "dialogue": "실제 말하는 대화(1~2문장)"\n'
        "}\n"
        "개인정보(주민등록/계좌/카드/CVC 등) 제공 금지, 시뮬레이션 언급 금지.\n"
    )


# ─────────────────────────────────────────────────────────
# 순수 구현 함수 (입력 → 실행 → dict 반환)
# ─────────────────────────────────────────────────────────
def simulate_dialogue_impl(input_obj: SimulationInput) -> Dict[str, Any]:
    """
    핵심 시뮬 엔진: 공격자/피해자 교대턴, MCP DB 저장, JSON 결과 반환.
    FastMCP에서 바로 호출 가능하도록 '순수 함수'로 분리.
    """
    db = SessionLocal()
    try:
        # 1) 대화 컨테이너/ID 결정
        #    - round 1: 새 conversation 생성
        #    - 이어달리기: case_id_override가 있으면 그 ID로 같은 대화에 이어쓰기
        conversation_id: Optional[str] = input_obj.case_id_override

        if conversation_id:
            conv = db.get(Conversation, conversation_id)
            if conv is None:
                conv = None
        else:
            meta = {
                "offender_id": input_obj.offender_id,
                "victim_id": input_obj.victim_id,
                "round_no": input_obj.round_no or 1,
                "guidance": input_obj.guidance or {},
                "scenario": input_obj.scenario,
            }
            conv = Conversation.create(db, meta=meta)
            conversation_id = conv.id

        print(">> models:", input_obj.models)

        # 2) LLM 준비
        atk = AttackerLLM(
            model=input_obj.models["attacker"],
            system=input_obj.attacker.system,
            temperature=input_obj.temperature,
        )
        vic = VictimLLM(
            model=input_obj.models["victim"],
            system=input_obj.victim.system,
            temperature=input_obj.temperature,
        )

        # 3) 상태
        turns: List[Turn] = []
        history_attacker: list = []
        history_victim: list = []
        turn_index = 0
        attacks = replies = 0
        last_victim_text = ""
        last_offender_text = ""
        guidance_text = (input_obj.guidance or {}).get("text") or ""
        guidance_type = (input_obj.guidance or {}).get("type") or ""
        max_turns = input_obj.max_turns

        # 상태 관리 변수
        state = "running"  # running | awaiting_victim_final | ended
        ended_by = ""
        end_reason = ""
        end_turn: Optional[int] = None

        # 4) 루프 (티키타카 기준)
        for _ in range(max_turns):
            if state != "running":
                break

            # ── 공격자 발화 ─────────────────────────────
            if attacks >= MAX_OFFENDER_TURNS:
                ended_by = "max_offender_turns"
                end_reason = "offender_turn_cap"
                state = "ended"
                end_turn = (turn_index - 1) if (turn_index - 1) >= 0 else None
                break

            attacker_text = atk.next(
                history=history_attacker,
                last_victim=last_victim_text,
                current_step="",  # 필요 시 단계 주입
                guidance=guidance_text,
                guidance_type=guidance_type,
            )

            # 저장(반쪽턴: 공격자)
            db.add(TurnLog(
                conversation_id=conversation_id,
                idx=turn_index,
                role="offender",
                text=attacker_text,
            ))
            db.commit()
            turns.append(Turn(role="offender", text=attacker_text))

            # 히스토리
            try:
                from langchain_core.messages import AIMessage, HumanMessage
                history_attacker.append(AIMessage(attacker_text))
                history_victim.append(HumanMessage(attacker_text))
            except Exception:
                pass

            last_offender_text = attacker_text
            turn_index += 1
            attacks += 1

            # 공격자 종료 선언 → 피해자 고정 한 줄 후 종료
            if attacker_declared_end(attacker_text):
                state = "awaiting_victim_final"
                ended_by = "attacker_end"
                end_reason = "protocol_termination"

                if replies < MAX_VICTIM_TURNS:
                    victim_text = VICTIM_FINAL_JSON
                    db.add(TurnLog(
                        conversation_id=conversation_id,
                        idx=turn_index,
                        role="victim",
                        text=victim_text,
                    ))
                    db.commit()
                    turns.append(Turn(role="victim", text=victim_text))
                    try:
                        from langchain_core.messages import AIMessage, HumanMessage
                        history_victim.append(AIMessage(victim_text))
                        history_attacker.append(HumanMessage(victim_text))
                    except Exception:
                        pass
                    turn_index += 1
                    replies += 1

                if conv is not None:
                    conv.ended_by = ended_by
                    db.add(conv); db.commit()

                state = "ended"
                end_turn = (turn_index - 1) if (turn_index - 1) >= 0 else None
                break

            # ── 피해자 발화 ─────────────────────────────
            if replies >= MAX_VICTIM_TURNS:
                ended_by = "max_victim_turns"
                end_reason = "victim_turn_cap"
                state = "ended"
                end_turn = (turn_index - 1) if (turn_index - 1) >= 0 else None
                break

            victim_meta = input_obj.victim_profile.get("meta")
            victim_knowledge = input_obj.victim_profile.get("knowledge")
            victim_traits = input_obj.victim_profile.get("traits")

            victim_text = vic.next(
                history=history_victim,
                last_offender=last_offender_text,
                meta=victim_meta,
                knowledge=victim_knowledge,
                traits=victim_traits,
                guidance=guidance_text,
                guidance_type=guidance_type,
            )
            # 피해자 출력 JSON 강제/정규화
            victim_text = _force_victim_json(victim_text)

            db.add(TurnLog(
                conversation_id=conversation_id,
                idx=turn_index,
                role="victim",
                text=victim_text,
            ))
            db.commit()
            turns.append(Turn(role="victim", text=victim_text))

            try:
                from langchain_core.messages import AIMessage, HumanMessage
                history_victim.append(AIMessage(victim_text))
                history_attacker.append(HumanMessage(victim_text))
            except Exception:
                pass

            last_victim_text = victim_text
            turn_index += 1
            replies += 1

            # 피해자 종료 의사 → 공격자 한 줄 주입 후 즉시 종료
            if victim_declared_end(victim_text):
                if attacks < MAX_OFFENDER_TURNS:
                    attacker_text = ATTACKER_TRIGGER_PHRASE  # "여기서 마무리하겠습니다."
                    db.add(TurnLog(
                        conversation_id=conversation_id,
                        idx=turn_index,
                        role="offender",
                        text=attacker_text,
                    ))
                    db.commit()
                    turns.append(Turn(role="offender", text=attacker_text))
                    try:
                        from langchain_core.messages import AIMessage, HumanMessage
                        history_attacker.append(AIMessage(attacker_text))
                        history_victim.append(HumanMessage(attacker_text))
                    except Exception:
                        pass
                    turn_index += 1
                    attacks += 1

                ended_by = "victim_end_mapped"
                end_reason = "victim_termination_signal"
                if conv is not None:
                    conv.ended_by = ended_by
                    db.add(conv); db.commit()

                state = "ended"
                end_turn = (turn_index - 1) if (turn_index - 1) >= 0 else None
                break

        else:
            # 루프가 break 없이 자연 종료됨 (max_turns 소진 등)
            if state == "running":
                state = "ended"
                ended_by = ended_by or "turn_limit"
                end_reason = end_reason or "max_turns_reached"
                end_turn = (turn_index - 1) if (turn_index - 1) >= 0 else None

        # 루프 이후 ended_by 보정(하드캡/기타 사유로 종료 시 DB ended_by 비어있을 수 있음)
        if 'ended_by' in locals():
            if (conv is not None) and ((conv.ended_by or "") == "") and ((ended_by or "") != ""):
                conv.ended_by = ended_by
                db.add(conv)
                db.commit()

        # 5) 결과 구성
        meta_out = {
            "offender_id": input_obj.offender_id,
            "victim_id": input_obj.victim_id,
            "round_no": input_obj.round_no or 1,
            "guidance": input_obj.guidance or {},
            "scenario": input_obj.scenario,
            "models": input_obj.models,
            "state": state,
            "ended_by": (ended_by or ((conv.ended_by if conv is not None else "") or "")),
            "end_reason": end_reason,
            "end_turn": end_turn,
        }
        result = SimulationResult(
            conversation_id=conversation_id,
            turns=turns,
            ended_by=(conv.ended_by if conv is not None else "") or (ended_by or ""),
            stats={"half_turns": turn_index, "turns": turn_index // 2},
            meta=meta_out,
        )
        out = result.model_dump()
        # ✅ 최상위에 round_no 노출 (프론트/소비처가 meta를 안 파도 접근 가능)
        try:
            run_no_val = int(input_obj.round_no or 1)
        except Exception:
            run_no_val = int(meta_out.get("round_no") or 1)
        # ✅ run_no 별칭도 같이 제공(다른 파일 수정 없이 run_no로 소비 가능)
        out["run_no"] = run_no_val
        out.pop("round_no", None)
        return out
    finally:
        db.close()


# ─────────────────────────────────────────────────────────
# 출력 보정 유틸
# ─────────────────────────────────────────────────────────
def _force_victim_json(text: str) -> str:
    """
    피해자 발화를 JSON 한 객체로 강제하는 임시 가드.
    - 이미 JSON이면 그대로 통과
    - 자유 텍스트면 1~2문장으로 자르고 JSON 래핑
    """
    t = (text or "").strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict) and {"is_convinced", "thoughts", "dialogue"} <= set(obj.keys()):
                return t
        except Exception:
            pass

    parts = re.split(r"([.!?])", t)
    short = "".join(parts[:4]).strip()
    if not short:
        short = "그 정보는 전화로 드릴 수 없습니다."

    obj = {
        "is_convinced": 2,
        "thoughts": "(조심스럽다.)",
        "dialogue": short
    }
    return json.dumps(obj, ensure_ascii=False)
