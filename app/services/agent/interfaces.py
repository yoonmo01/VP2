# app/services/agent/interfaces.py
from typing import Protocol, Tuple, Dict, Any
from uuid import UUID


class IGuidelineRepo(Protocol):

    def pick_preventive(self) -> Tuple[str, str]:
        ...

    def pick_attack(self) -> Tuple[str, str]:
        ...


class IAgent(Protocol):

    def decide_kind(self, case_id: UUID) -> str:
        ...  # 'P' or 'A'

    def personalize(self, case_id: UUID, offender_id: int, victim_id: int,
                    run_no: int) -> Dict[str, Any]:
        ...


# --- 추가: (권장) 에이전트 설정/상태 모델 얇게 정의 ---
class SimulationConfig(dict):
    """
    에이전트가 참조하는 얇은 설정 객체.
    - attacker_model / victim_model
    - max_rounds: 티키타카 수(공격자1 + 피해자1 = 1)
    - is_custom_scenario: 커스텀 시나리오(Tavily 등) 여부
    """
    pass

class SimulationState(dict):
    """
    에이전트 상태:
    - cycle_idx: 현재 사이클 번호
    - rounds_count: 이번 사이클에서 완료된 티키타카 수
    - guidance / judgement: 판정 및 지침 정보
    """
    pass