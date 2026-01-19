# app/services/prompt_builder.py
from __future__ import annotations
from typing import Dict, Any, List


def _render_web_context(web_ctx: Dict[str, Any] | None) -> str:
    if not web_ctx: return ""
    items = web_ctx.get("items", [])[:5]
    lines = [f"- {x.get('title')}: {x.get('summary')}" for x in items]
    return "[참고자료]\n" + "\n".join(lines)


def build_attacker_block(*, scenario: dict, guidance_type: str | None,
                         guideline: str | None,
                         web_ctx: Dict[str, Any] | None) -> str:
    steps: List[str] = (scenario.get("steps") or
                        (scenario.get("profile", {}) or {}).get("steps", [])
                        or [])
    step_lines = "\n".join(f"- {s}" for s in steps) if steps else "(없음)"
    guide = f"\n[지침]\n유형: {guidance_type}\n내용: {guideline}\n" if guideline else ""
    web = ("\n" + _render_web_context(web_ctx)) if web_ctx else ""
    return f"""[역할] 피싱범
[현재 단계 목록]
{step_lines}{guide}{web}""".strip()


def build_victim_block(*, victim: dict, guidance_type: str | None,
                       guideline: str | None,
                       web_ctx: Dict[str, Any] | None) -> str:
    meta = victim.get("meta") or "정보 없음"
    knowledge = victim.get("knowledge") or "정보 없음"
    traits = victim.get("traits") or "정보 없음"
    guide = f"\n[지침]\n유형: {guidance_type}\n내용: {guideline}\n" if guideline else ""
    web = ("\n" + _render_web_context(web_ctx)) if web_ctx else ""
    return f"""[역할] 피해자
[캐릭터 시트]
메타정보: {meta}
지식정보: {knowledge}
성격정보: {traits}{guide}{web}""".strip()


def build_payload_for_simulator(*, attacker_prompt: str, victim_prompt: str,
                                attacker_model: str, victim_model: str,
                                max_turns: int) -> dict:
    # MCP 서버가 바로 받도록 "명확한 키"로 정규화
    return {
        "attacker_prompt": attacker_prompt,
        "victim_prompt": victim_prompt,
        "attacker_model": attacker_model,
        "victim_model": victim_model,
        "max_turns": max_turns
    }


def build_payload_internal(*,
                           offender_id: int,
                           victim_id: int,
                           case_id: UUID | None,
                           run_no: int,
                           scenario: dict,
                           guidance_type: str | None,
                           guideline: str | None,
                           attacker_model: str,
                           victim_model: str,
                           attacker_provider: str | None = None,
                           victim_provider: str | None = None,
                           max_rounds: int = 30) -> dict:
    return {
        "mode": "internal",
        "offender_id": offender_id,
        "victim_id": victim_id,
        "case_id_override": str(case_id) if case_id else None,
        "run_no": run_no,
        "max_rounds": max_rounds,
        "scenario": scenario,
        "guidance_type": guidance_type,
        "guideline": guideline,
        "models": {
            "attacker_model": attacker_model,
            "victim_model": victim_model,
            "attacker_provider": attacker_provider,
            "victim_provider": victim_provider,
        }
    }
