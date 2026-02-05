#VP/vp_mcp/mcp_server/tools/simulate_dialogue.py
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from ..schemas import SimulationInput, SimulationResult, Turn
from ..llm.providers import AttackerLLM, VictimLLM
from ..db.base import SessionLocal
from ..db.models import Conversation, TurnLog

import json
import re
from typing import Tuple
import hashlib


# FastMCP 등록용
from mcp.server.fastmcp import FastMCP

# 종료 규칙 유틸(단일 진실원)
from vp_mcp.mcp_server.utils.end_rules import (
    attacker_declared_end,      # 공격자 종료 선언 감지 ("여기서 마무리하겠습니다." 변형 포함)
    victim_declared_end,        # 피해자 dialogue 기준 종료 의사 감지
    ATTACKER_TRIGGER_PHRASE,    # "여기서 마무리하겠습니다."
    VICTIM_FINAL_JSON,          # 피해자 마지막 고정 JSON
)

# ✅ 2-call에서 Planner 출력(proc_code + proc_text) 파싱용
def _extract_proc_bundle(planner_raw: str) -> tuple[Optional[str], str]:
    t = _strip_code_fences(planner_raw or "")
    if attacker_declared_end(t):
        return (None, "")
    obj = _try_extract_first_json_obj(t)
    if isinstance(obj, dict):
        pc = obj.get("proc_code")
        proc_code = pc.strip() if isinstance(pc, str) and pc.strip() else None

        # planner가 함께 내주길 원하는 "절차 전문" 필드
        # (planner 프롬프트에서 proc_text로 통일하는 걸 권장)
        pt = (
            obj.get("proc_text")
            or obj.get("proc_label_text")
            or obj.get("procedure_text")
            or obj.get("label_text")
            or ""
        )
        proc_text = pt.strip() if isinstance(pt, str) else ""
        return (proc_code, proc_text)
    return (None, "")

def _debug_head(s: str, n: int = 140) -> str:
    return ((s or "")[:n]).replace("\n", " ")

def _build_previous_turns_block(turns: List[Turn]) -> str:
    lines = []
    for t in turns:
        role = t.role
        text = (t.text or "").replace("\n", " ")
        lines.append(f"[{role}] {text}")
    return "\n".join(lines) if lines else "직전 대화 없음."

# 하드캡(안전장치). 필요 시 .env로 이관
MAX_OFFENDER_TURNS = 60
MAX_VICTIM_TURNS = 60

# ─────────────────────────────────────────────────────────
# 공격자(JSON) 출력 방어 유틸
# ─────────────────────────────────────────────────────────
def _strip_code_fences(s: str) -> str:
    """```json ... ``` 같은 코드블록 제거"""
    t = (s or "").strip()
    # ```json\n{...}\n``` 형태 제거
    t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()

def _try_extract_first_json_obj(s: str) -> Optional[dict]:
    """
    텍스트 안에서 첫 { ... } 블록을 찾아 JSON dict로 파싱 시도.
    실패하면 None.
    """
    t = _strip_code_fences(s)
    if not t:
        return None

    # 이미 완전한 JSON처럼 보이면 바로 시도
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    # 앞뒤에 잡텍스트가 섞인 경우: 첫 { 와 마지막 } 사이를 잘라 시도
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        chunk = t[l : r + 1]
        try:
            obj = json.loads(chunk)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None

def _extract_attacker_utterance(attacker_raw: str) -> str:
    """
    공격자 출력이 JSON이면 utterance만 추출(피해자에게 전달할 텍스트).
    실패하면 원문(정리된 형태) 반환.
    """
    t = _strip_code_fences(attacker_raw)
    obj = _try_extract_first_json_obj(t)
    if isinstance(obj, dict):
        u = obj.get("utterance")
        if isinstance(u, str) and u.strip():
            return u.strip()
    return t

def _force_attacker_json(attacker_raw: str) -> str:
    """
    공격자 출력이:
    - 종료 문구면 그대로 반환(한 줄)
    - 이미 JSON(dict)이고 'utterance' 있으면 (가능하면) 정규화하여 반환
    - 그 외면 utterance에 래핑해서 JSON으로 강제
    """
    t = _strip_code_fences(attacker_raw)

    # 종료 훅이면 JSON 강제하지 않음
    if attacker_declared_end(t):
        # 종료 문구는 정확히 한 줄일 필요가 있으면 여기서 정규화 가능
        # (현재 end_rules에서 변형 포함 감지라면, 트리거 문구로 강제해도 됨)
        if ATTACKER_TRIGGER_PHRASE in t:
            return ATTACKER_TRIGGER_PHRASE
        return t

    obj = _try_extract_first_json_obj(t)
    if isinstance(obj, dict) and isinstance(obj.get("utterance"), str) and obj["utterance"].strip():
        # 필드 누락 보정(ATTACKER_V2 스펙 기준)
        norm = {
            "utterance": obj.get("utterance", "").strip(),
            "proc_code": obj.get("proc_code", "") or "",
            "ppse_labels": obj.get("ppse_labels", []) or [],
        }
        # ppse_labels 타입 보정
        if not isinstance(norm["ppse_labels"], list):
            norm["ppse_labels"] = []
        norm["ppse_labels"] = [str(x) for x in norm["ppse_labels"]][:3]
        return json.dumps(norm, ensure_ascii=False)

    # 자유 텍스트면 래핑
    # 너무 길면 350자 컷
    short = (t or "").strip()
    if len(short) > 350:
        short = short[:350].rstrip()
    if not short:
        short = "확인을 위해 몇 가지 사항을 여쭙겠습니다."

    wrapped = {
        "utterance": short,
        "proc_code": "2-2",      # 기본값(목적 안내) 같은 걸로 잡아둠. 필요 시 변경
        "ppse_labels": [],
    }
    return json.dumps(wrapped, ensure_ascii=False)

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
            # ✅ templates는 스키마에서 드랍될 수 있으니 validate 전에 따로 보관
            raw_templates = (payload.get("templates") or {}) if isinstance(payload.get("templates"), dict) else {}
            out = simulate_dialogue_impl(data, templates=raw_templates)
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
    - ✅ 2-call용: templates.attacker_planner / templates.attacker_realizer도 받아둔다.
    - victim.system이 비어있고 victim_profile가 있다면 victim_profile 기반으로 system을 생성하여 주입
    """
    args = dict(arguments or {})
    attacker = args.get("attacker") or {}
    victim = args.get("victim") or {}
    tpls = (args.get("templates") or {}) if isinstance(args.get("templates"), dict) else {}

    atk_tpl = tpls.get("attacker") or ""
    vic_tpl = tpls.get("victim") or ""
    atk_planner_tpl = tpls.get("attacker_planner") or ""
    atk_realizer_tpl = tpls.get("attacker_realizer") or ""

    # 1) 템플릿이 이미 '완성된 system 프롬프트'라면 그대로 사용
    if atk_tpl and not attacker.get("system"):
        attacker["system"] = atk_tpl
    if vic_tpl and not victim.get("system"):
        victim["system"] = vic_tpl

    # ✅ 2-call 템플릿은 args에 보존 (schemas가 몰라도 impl에서 arguments로 읽어도 됨)
    #   - 가능하면 templates dict에 그대로 유지
    if isinstance(tpls, dict):
        if atk_planner_tpl:
            tpls["attacker_planner"] = atk_planner_tpl
        if atk_realizer_tpl:
            tpls["attacker_realizer"] = atk_realizer_tpl
    args["templates"] = tpls

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
def simulate_dialogue_impl(input_obj: SimulationInput, *, templates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        # ✅ 2-call(Planner→Realizer)을 MCP 서버에서만 수행:
        # - input_obj.attacker.system: 대표/호환(보통 realizer system)
        # - arguments.templates.attacker_planner / attacker_realizer: 2-call용 system
        #
        # schemas(SimulationInput)가 templates를 모를 수 있으니,
        # input_obj에 담긴 scenario/meta만으로는 알 수 없어서
        # "attacker.system을 realizer로" 유지하면서
        # planner/realizer는 templates에서 꺼내 쓰도록 구성한다.

        # templates는 SimulationInput에 직접 없을 수 있어 안전하게 우회:
        # ✅ validate 이후 스키마 드랍 대비: simulate_dialogue()에서 별도로 넘겨준 templates를 우선 사용
        templates = templates or {}

        # 만약 SimulationInput에 templates가 없으면, scenario/meta에 실려오지 않으므로
        # caller(REST /api/simulate)가 input_obj 생성 직전에 주입했어야 함.
        # 그래도 비는 경우를 대비해서 attacker.system을 폴백으로 사용한다.
        planner_system = ""
        realizer_system = ""
        if isinstance(templates, dict):
            planner_system = (templates.get("attacker_planner") or "").strip()
            realizer_system = (templates.get("attacker_realizer") or "").strip()

        if not realizer_system:
            realizer_system = (input_obj.attacker.system or "").strip()
        if not planner_system:
            # planner가 없으면 1-call처럼 동작(= realizer system으로 planner도 호출)
            planner_system = realizer_system

        atk_planner = AttackerLLM(
            model=input_obj.models["attacker"],
            system=planner_system,
            temperature=input_obj.temperature,
        )
        atk_realizer = AttackerLLM(
            model=input_obj.models["attacker"],
            system=realizer_system,
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
        # 원본(저장/피해자 히스토리용) vs 공격자 입력용(dialogue만) 분리
        last_victim_raw = ""
        last_victim_dialogue = ""
        last_offender_text = ""        # 피해자에게 넘길 "utterance"만
        last_offender_raw = ""         # DB/로그용 원본(JSON)
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

            # ✅ 2-call: (1) Planner로 proc_code 선택 → (2) Realizer로 utterancepse 생성
            previous_turns_block = _build_previous_turns_block(turns)

            # ✅ 첫 턴(공격자 시작) 강제:
            # - 직전 대화가 없으므로 planner의 proc_code 선택이 불가능/불안정
            # - 첫 공격자 턴은 proc_code를 1-1로 고정하고, planner 호출을 스킵한다.
            is_first_offender_turn = (turn_index == 0 and len(turns) == 0 and previous_turns_block == "직전 대화 없음.")

            if is_first_offender_turn:
                # 첫 턴은 안정적으로 고정 (planner를 첫턴부터 돌리고 싶으면 여기 분기를 제거해도 됨)
                proc_code = "1-1"
                proc_text = ""  # ✅ realizer 시스템에서 절차 전문을 뺄 거면, 여기도 채우는 게 좋음(아래 NOTE 참고)
                attacker_text = atk_realizer.next(
                    history=history_attacker,
                    last_victim=last_victim_dialogue,
                    current_step=proc_text,
                    guidance=guidance_text,
                    guidance_type=guidance_type,
                    previous_turns_block=previous_turns_block,
                    proc_code=proc_code,
                )
            else:
                # (1) Planner call
                planner_raw = atk_planner.next(
                    history=history_attacker,
                    last_victim=last_victim_dialogue,  # 호환: planner는 이 값만으로도 충분히 판단 가능
                    current_step="",
                    guidance="",  # planner는 guidance를 최대한 배제(라벨 선택 순수성)
                    guidance_type="",
                    # ✅ 템플릿이 previous_turns_block을 요구하는 경우를 위해 같이 전달
                    previous_turns_block=previous_turns_block,
                )

                # planner가 종료 선언하면 즉시 종료 프로토콜로 전환
                if attacker_declared_end(planner_raw or ""):
                    attacker_text = ATTACKER_TRIGGER_PHRASE
                else:
                    proc_code, proc_text = _extract_proc_bundle(planner_raw or "")
                    proc_code = proc_code or ""
                    proc_text = proc_text or ""



                    # (2) Realizer call (proc_code 고정)
                    attacker_text = atk_realizer.next(
                        history=history_attacker,
                        last_victim=last_victim_dialogue,
                        current_step=proc_text,
                        guidance=guidance_text,
                        guidance_type=guidance_type,
                        previous_turns_block=previous_turns_block,
                        proc_code=proc_code,
                    )

            # ✅ 공격자 출력 방어:
            # - 종료 문구면 그대로
            # - 그 외면 JSON 강제(ATTACKER_V2 스펙에 맞춤)
            attacker_text = _force_attacker_json(attacker_text)
            attacker_utterance = _extract_attacker_utterance(attacker_text)
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
                # 공격자는 자기 출력 형식(JSON)을 계속 유지하는 게 자연스러워서 raw를 넣고,
                history_attacker.append(AIMessage(attacker_text))
                # 피해자에게는 meta 누출 최소화를 위해 utterance만 전달
                history_victim.append(HumanMessage(attacker_utterance))
            except Exception:
                pass

            last_offender_raw = attacker_text
            last_offender_text = attacker_utterance
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
                last_offender=last_offender_text,  # ✅ 이제 utterance만 들어감
                meta=victim_meta,
                knowledge=victim_knowledge,
                traits=victim_traits,
                guidance=guidance_text,
                guidance_type=guidance_type,
            )
            # 피해자 출력 JSON 강제/정규화
            victim_text = _force_victim_json(victim_text)
            victim_dialogue = _extract_victim_dialogue(victim_text)

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
                # 피해자 히스토리에는 원본 JSON을 넣어도 괜찮음(자기 상태 유지용)
                history_victim.append(AIMessage(victim_text))
                # 공격자 히스토리에는 dialogue만 넣어 메타 유출 방지
                history_attacker.append(HumanMessage(victim_dialogue))
            except Exception:
                pass

            last_victim_raw = victim_text
            last_victim_dialogue = victim_dialogue
            turn_index += 1
            replies += 1

            # 피해자 종료 의사 → 공격자 한 줄 주입 후 즉시 종료
            # 종료 판정은 원본 JSON 기반(내부 util이 dialogue 파싱할 가능성 높음)
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

def _extract_victim_dialogue(text: str) -> str:
    """
    피해자 출력이 JSON이면 dialogue만 추출해서 공격자 입력에 사용.
    실패하면 원문 그대로 반환.
    """
    t = (text or "").strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict):
                d = obj.get("dialogue")
                if isinstance(d, str) and d.strip():
                    return d.strip()
        except Exception:
            pass
    return t

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
