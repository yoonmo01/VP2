# app/services/tts_service.py
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메모리 캐시: {case_id: {run_no: [turns]}}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DIALOG_CACHE: Dict[str, Dict[int, List[dict]]] = {}


def cache_run_dialog(
    case_id: str,
    run_no: int,
    turns: List[dict],
    victim_age: Optional[int] = None,
    victim_gender: Optional[str] = None,
) -> None:
    """
    라운드별 대화를 캐시에 저장.
    - 피해자 나이/성별을 받아서 victim 턴들에 age_group, gender 메타를 주입한다.
    """

    def _to_age_group(age: Optional[int]) -> Optional[str]:
        if age is None:
            return None
        try:
            a = int(age)
        except Exception:
            return None
        if a < 20:
            return "10s"
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
        return "70s"

    def _normalize_gender(g: Optional[str]) -> Optional[str]:
        if not g:
            return None
        s = str(g).strip().lower()
        if s in ("남", "남자", "m", "male"):
            return "male"
        if s in ("여", "여자", "f", "female"):
            return "female"
        return None

    age_group = _to_age_group(victim_age)
    norm_gender = _normalize_gender(victim_gender)

    enriched_turns: List[dict] = []
    for t in turns:
        t2 = dict(t)
        if t2.get("role") == "victim":
            # 이미 들어있으면 덮어쓰지 않음
            if age_group and "age_group" not in t2:
                t2["age_group"] = age_group
            if norm_gender and "gender" not in t2:
                t2["gender"] = norm_gender
        enriched_turns.append(t2)

    if case_id not in _DIALOG_CACHE:
        _DIALOG_CACHE[case_id] = {}
    _DIALOG_CACHE[case_id][run_no] = enriched_turns

    logger.info(
        "[TTS_CACHE] cached: case_id=%s, run_no=%s, turns=%d, age_group=%s, gender=%s",
        case_id,
        run_no,
        len(enriched_turns),
        age_group,
        norm_gender,
    )


def get_cached_dialog(case_id: str, run_no: int) -> Optional[List[dict]]:
    """캐시에서 특정 라운드 대화 조회"""
    return _DIALOG_CACHE.get(case_id, {}).get(run_no)


def clear_case_dialog_cache(case_id: str) -> None:
    """특정 케이스의 모든 대화 캐시 제거"""
    if case_id in _DIALOG_CACHE:
        del _DIALOG_CACHE[case_id]
        logger.info(f"[TTS_CACHE] cleared: case_id={case_id}")


def get_all_runs_for_case(case_id: str) -> List[int]:
    """특정 케이스의 모든 라운드 번호 반환"""
    if case_id not in _DIALOG_CACHE:
        return []
    return sorted(_DIALOG_CACHE[case_id].keys())