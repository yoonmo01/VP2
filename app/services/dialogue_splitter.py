# app/services/dialogue_splitter.py
from __future__ import annotations
from typing import List, Dict, Any, Literal
import json
from app.core.logging import get_logger

logger = get_logger(__name__)

Turn = Dict[str, Any]
Speaker = Literal["offender", "victim", "both"]


def _clean_offender_text(text: str) -> str:
    """
    피싱범(offender) 텍스트에서 'INTENT: ...' 같은 메타정보 제거.
    """
    if not isinstance(text, str):
        return ""
    # 예: " ...  \nINTENT: 압박"
    idx = text.find("INTENT:")
    if idx != -1:
        text = text[:idx]
    return text.strip()


def _extract_victim_dialogue(text: str) -> str:
    """
    피해자(victim) 텍스트는 JSON 문자열인 경우가 많으므로
    {"dialogue": "..."}만 뽑아서 사용.
    """
    if not isinstance(text, str):
        return ""

    stripped = text.strip()
    if not stripped.startswith("{"):
        # 이미 순수 텍스트인 경우
        return stripped

    try:
        obj = json.loads(stripped)
        # {"dialogue": "..."} 구조라고 가정
        dlg = obj.get("dialogue") or ""
        return str(dlg).strip()
    except Exception:
        # 파싱 실패 시 원문 그대로 사용
        logger.warning("[DialogueSplitter] victim JSON parse 실패, 원문 사용")
        return stripped


def split_turns_by_role(turns: List[Turn]) -> Dict[str, List[str]]:
    """
    turns 리스트를 offender / victim 텍스트 리스트로 분리.
    """
    offender_lines: List[str] = []
    victim_lines: List[str] = []

    for t in turns or []:
        role = t.get("role")
        raw_text = t.get("text") or ""
        if role == "offender":
            cleaned = _clean_offender_text(raw_text)
            if cleaned:
                offender_lines.append(cleaned)
        elif role == "victim":
            dlg = _extract_victim_dialogue(raw_text)
            if dlg:
                victim_lines.append(dlg)

    return {
        "offender": offender_lines,
        "victim": victim_lines,
    }


def build_tts_text(turns: List[Turn], speaker: Speaker = "offender") -> str:
    """
    TTS에 넣을 최종 텍스트를 생성.
    - speaker="offender"  : 피싱범 대사만 이어붙임
    - speaker="victim"    : 피해자 대사만 이어붙임
    - speaker="both"      : [피싱범] / [피해자] 라벨을 붙여 교대로 구성
    """
    split = split_turns_by_role(turns)
    off_lines = split.get("offender") or []
    vic_lines = split.get("victim") or []

    if speaker == "offender":
        return "\n".join(off_lines)

    if speaker == "victim":
        return "\n".join(vic_lines)

    # speaker == "both"
    # 최대한 실제 대화 순서에 가깝게 라벨 붙여서 출력
    lines: List[str] = []
    # 원래 turns 순서를 기준으로 라벨링
    for t in turns or []:
        role = t.get("role")
        raw = t.get("text") or ""
        if role == "offender":
            cleaned = _clean_offender_text(raw)
            if cleaned:
                lines.append(f"[피싱범] {cleaned}")
        elif role == "victim":
            dlg = _extract_victim_dialogue(raw)
            if dlg:
                lines.append(f"[피해자] {dlg}")

    return "\n".join(lines)
