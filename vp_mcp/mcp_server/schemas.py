from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class RolePrompt(BaseModel):
    system: str

class SimulationInput(BaseModel):
    # app의 prompt builder가 채워서 보냄
    attacker: RolePrompt
    victim: RolePrompt
    max_turns: int = Field(default=15, ge=1, le=30)

    # 이어달리기/지침
    case_id_override: Optional[str] = None
    round_no: Optional[int] = None
    guidance: Optional[Dict[str, str]] = None  # {"type": "P"|"A", "text": "..."}

    # 메타
    offender_id: int
    victim_id: int
    scenario: Dict[str, Any] = {}
    victim_profile: Dict[str, Any] = {}
    templates: Dict[str, Any] = {}
    models: Dict[str, str] = {"attacker": "gpt-4o-mini", "victim": "gemini-2.5-flash-lite"}
    temperature: float = 0.6

class Turn(BaseModel):
    role: str  # "offender" | "victim"
    text: str

class SimulationResult(BaseModel):
    conversation_id: str
    turns: List[Turn]
    ended_by: Optional[str] = None
    stats: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
