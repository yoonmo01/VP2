# app/services/conversation_cache.py
from __future__ import annotations
from typing import Dict, Tuple, Any, Optional
import time
from threading import RLock

# 최대 보관 개수 / TTL은 상황 봐서 조정
_MAX_ITEMS = 100
_TTL_SECONDS = 60 * 60  # 1시간

_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
_lock = RLock()


def set_conversation(case_id: str, run_no: int, data: Dict[str, Any]) -> None:
    """
    시뮬레이션 결과(log)를 캐시에 저장.
    data 안에는 최소한 "turns"가 들어있도록 맞춰주면 됨.
    """
    key = (case_id, run_no)
    with _lock:
        _cache[key] = {"data": data, "ts": time.time()}
        # 너무 많이 쌓이면 가장 오래된 것부터 삭제
        if len(_cache) > _MAX_ITEMS:
            oldest_key = min(_cache.items(), key=lambda kv: kv[1]["ts"])[0]
            del _cache[oldest_key]


def get_conversation(case_id: str, run_no: int) -> Optional[Dict[str, Any]]:
    """
    캐시에서 시뮬레이션 log를 가져옴.
    TTL이 지난 건 자동으로 버림.
    """
    key = (case_id, run_no)
    with _lock:
        item = _cache.get(key)
        if not item:
            return None

        if time.time() - item["ts"] > _TTL_SECONDS:
            # 만료된 캐시는 삭제
            del _cache[key]
            return None

        return item["data"]
