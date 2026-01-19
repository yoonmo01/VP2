# app/services/agent/graph.py
from __future__ import annotations
from typing import Dict, Any
from copy import deepcopy

MIN_ROUNDS = 2
MAX_ROUNDS = 5
MAX_TURNS_PER_ROUND = 15  # (공1+피1을 1턴으로 본 정의에 맞춰 시뮬 엔진이 동일 의미로 해석)

def should_continue_rounds(last_judgement: Dict[str, Any], round_index: int) -> bool:
    # 최소 2회는 돌고, 피해자가 충분히 방어할 수 있다고 판단되면 조기 중단
    if round_index + 1 < MIN_ROUNDS:
        return True
    if round_index + 1 >= MAX_ROUNDS:
        return False
    # 판정 결과 해석(예: {"phishing": True/False, "reason": "..."} )
    was_phished = bool(last_judgement.get("phishing"))
    # 피싱 당했다면 최소 한 번 더 훈련
    if was_phished:
        return True
    # 실패(=방어 성공)했으면 종료
    return False
