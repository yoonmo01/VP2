# app/services/tts_cache.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional
import threading


@dataclass
class TTSItem:
    case_id: str
    run_no: int
    turn_index: int
    speaker: str         # "offender" | "victim"
    text: str
    audio_b64: str
    content_type: str = "audio/wav"
    total_duration_sec: Optional[float] = None
    char_time_sec: Optional[float] = None


class TTSCache:
    """
    (case_id, run_no) → [TTSItem, ...] 를 메모리에 보관하는 단순 캐시.
    - 프로세스 단위로만 유효 (멀티 프로세스/멀티 서버면 Redis 등으로 교체 필요)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str, int], List[TTSItem]] = {}
        self._running: set[Tuple[str, int]] = set()
        self._last_case_id: Optional[str] = None

    def _key(self, case_id: str, run_no: int) -> Tuple[str, int]:
        return (str(case_id), int(run_no))

    # ─────────────────────────────
    # 상태 조회
    # ─────────────────────────────
    def get_items(self, case_id: str, run_no: int) -> Optional[List[TTSItem]]:
        key = self._key(case_id, run_no)
        with self._lock:
            items = self._data.get(key)
            # 깊은 복사까진 필요 없고, 리스트 자체가 바뀌면 안 되게 새 리스트만 반환
            return list(items) if items else None

    def get_all_case_items(self, case_id: str) -> List[TTSItem]:
        """해당 case_id의 모든 run_no 항목을 run_no, turn_index 순으로 반환"""
        out: List[TTSItem] = []
        with self._lock:
            for (cid, run_no), items in self._data.items():
                if cid == str(case_id):
                    out.extend(items)

        # 정렬: run_no → turn_index
        out.sort(key=lambda x: (x.run_no, x.turn_index))
        return out

    def is_running(self, case_id: str, run_no: int) -> bool:
        key = self._key(case_id, run_no)
        with self._lock:
            return key in self._running

    def get_last_case_id(self) -> Optional[str]:
        with self._lock:
            return self._last_case_id

    # ─────────────────────────────
    # 상태 변경
    # ─────────────────────────────
    def mark_running(self, case_id: str, run_no: int) -> None:
        key = self._key(case_id, run_no)
        with self._lock:
            self._running.add(key)

    def set_items(self, case_id: str, run_no: int, items: List[TTSItem]) -> None:
        key = self._key(case_id, run_no)
        with self._lock:
            self._data[key] = list(items)
            self._running.discard(key)
            # 마지막으로 처리된 case_id 기록
            self._last_case_id = str(case_id)

    # ─────────────────────────────
    # 직렬화 헬퍼
    # ─────────────────────────────
    def as_dict_list(self, case_id: str, run_no: int) -> Optional[List[dict]]:
        items = self.get_items(case_id, run_no)
        if not items:
            return None
        return [asdict(it) for it in items]

    def all_case_as_dict_list(self, case_id: str) -> List[dict]:
        return [asdict(it) for it in self.get_all_case_items(case_id)]


# 전역 싱글톤 캐시
TTS_CACHE = TTSCache()
