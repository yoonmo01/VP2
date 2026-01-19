from __future__ import annotations
from typing import Optional, List, Dict, Any, Annotated
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict

# ─────────────────────────────────────────────────────────
# 더미/빈 값 판별 유틸
# ─────────────────────────────────────────────────────────
def _is_dummy_string(x: Any) -> bool:
    return isinstance(x, str) and x.strip().lower() == "string"

def _strip_schema_dummy(d: Any) -> Any:
    # FastAPI Docs 자동 스키마 잔여물 제거: {"additionalProp1": {}}
    if isinstance(d, dict) and list(d.keys()) == ["additionalProp1"]:
        return {}
    return d

def _is_effectively_empty(d: Any) -> bool:
    """딕셔너리가 와도 의미있는 값이 하나도 없으면 True"""
    if d is None:
        return True
    if not isinstance(d, dict):
        return False
    for _, v in d.items():
        if v in (None, "", {}, [], {"additionalProp1": {}}):
            continue
        if _is_dummy_string(v):
            continue
        return False
    return True

# ─────────────────────────────────────────────────────────
# 서브 모델
# ─────────────────────────────────────────────────────────
class CustomVictim(BaseModel):
    meta: Dict[str, Any] = Field(default_factory=dict)
    knowledge: Dict[str, Any] = Field(default_factory=dict)
    traits: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("meta", "knowledge", "traits", mode="before")
    @classmethod
    def _clean_sections(cls, v):
        v = v or {}
        v = _strip_schema_dummy(v)
        return v

class CustomScenarioSeed(BaseModel):
    # 커스텀 시나리오 시드(프론트에서 넘어오는 최소 정보)
    type: Optional[str] = None          # 예: "기관사칭"
    purpose: Optional[str] = None       # 예: "현금 편취"
    text: Optional[str] = None          # 자유 서술
    objectives: Optional[List[str]] = None  # 임시 단계/목표
    steps: Optional[List[str]] = None       # (옵션) steps가 올 수도 있음

    @field_validator("type", "purpose", "text", mode="before")
    @classmethod
    def _wipe_dummy_text(cls, v):
        return None if _is_dummy_string(v) else v

    @field_validator("objectives", "steps", mode="before")
    @classmethod
    def _list_or_none(cls, v):
        if not v:
            return None
        if isinstance(v, list):
            return [s for s in v if isinstance(s, str) and not _is_dummy_string(s)]
        return None

# 양수만 허용 (None 허용 시 None은 통과, 값이 있으면 >0)
PositiveInt = Annotated[int, Field(gt=0)]

# ─────────────────────────────────────────────────────────
# 메인 요청 스키마
# ─────────────────────────────────────────────────────────
class SimulationStartRequest(BaseModel):
    # ─ 피해자 선택 ─
    custom_victim: Optional[CustomVictim] = None
    victim_id: Optional[PositiveInt] = None     # custom_victim 없으면 필수

    # ─ 시나리오 선택 ─
    custom_scenario: Optional[CustomScenarioSeed] = None
    offender_id: Optional[PositiveInt] = None   # custom_scenario 없으면 필수

    # 공통 옵션
    use_tavily: bool = False                    # 커스텀 시나리오일 때만 사용 권장
    max_turns: int = Field(default=15, ge=1, le=30)

    # 🔧 라운드/케이스 제어
    round_limit: Optional[int] = 3              # 오케스트레이터가 2~3로 클램프
    case_id_override: Optional[str] = None      # 같은 케이스로 이어갈 때 사용(2라운드~)
    round_no: Optional[int] = 1                 # 현재 라운드(로그/디버깅 목적)

    # 레거시 호환(프론트가 이미 보내는 값 케어용)
    scenario: Optional[Dict[str, Any]] = None
    objectives: Optional[List[str]] = None

    # ---------------------------
    # 빈/더미 입력 자동 정규화
    # ---------------------------
    @field_validator("custom_victim", mode="before")
    @classmethod
    def _normalize_custom_victim(cls, v):
        if v is None: return None
        if hasattr(v, "model_dump"):
            v = v.model_dump()
        v = _strip_schema_dummy(v)
        return None if _is_effectively_empty(v) else v

    @field_validator("custom_scenario", mode="before")
    @classmethod
    def _normalize_custom_scenario(cls, v):
        if v is None: return None
        if hasattr(v, "model_dump"):
            v = v.model_dump()
        v = _strip_schema_dummy(v)
        return None if _is_effectively_empty(v) else v

    @field_validator("scenario", mode="before")
    @classmethod
    def _normalize_legacy_scenario(cls, v):
        if v is None: return None
        v = _strip_schema_dummy(v)
        return None if _is_effectively_empty(v) else v

    @field_validator("objectives", mode="before")
    @classmethod
    def _normalize_objectives(cls, v):
        if not v:
            return None
        if isinstance(v, list):
            return [s for s in v if isinstance(s, str) and not _is_dummy_string(s)]
        return None

    # ---------------------------
    # 상호배타/필수 및 범위 보정
    # ---------------------------
    @model_validator(mode="after")
    def _validate_choice(self):
        # 피해자: custom_victim 또는 victim_id 중 하나 필수
        if self.custom_victim is None and self.victim_id is None:
            raise ValueError("victim_id 또는 custom_victim 중 하나는 필수입니다.")

        # 시나리오: custom_scenario 또는 offender_id (또는 표준 scenario) 중 하나 필수
        if self.custom_scenario is None and self.scenario is None and self.offender_id is None:
            raise ValueError("offender_id 또는 custom_scenario(또는 scenario) 중 하나는 필수입니다.")

        # 라운드 범위 클램프 (2~5)
        if self.round_limit is not None:
            self.round_limit = max(2, min(int(self.round_limit), 3))

        if self.round_no is not None:
            self.round_no = max(1, int(self.round_no))

        return self

    # ✅ Swagger / FastAPI Docs 예시를 안전하게 교체
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "victim_id": 1,
                "offender_id": 1,
                "use_tavily": False,
                "max_turns": 15,
                "round_limit": 3,
                "round_no": 1
            }
        }
    )
