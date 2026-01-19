#app/schemas/victim.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List, Dict

class VictimCreate(BaseModel):
    name: str
    meta: dict[str, Any] = Field(default_factory=dict)       
    knowledge: dict[str, Any] = Field(default_factory=dict)  
    traits: dict[str, Any] = Field(default_factory=dict)     
    is_active: bool = True                         # ✅ 기본 True
    photo_path: Optional[str] = None               # ✅ 이미지 경로 (선택)


class VictimFlexibleIn(BaseModel):
    # 프론트가 보내는 모든 케이스를 포괄
    name: str

    # ① 간소 입력 케이스 (체크리스트/오션 순서)
    checklist_lines: Optional[List[str]] = None
    ocean_levels: Optional[List[str]] = None  # ["높음","낮음","..."] 개방성→성실성→외향성→친화성→신경성

    # ② 이미 구조화된 케이스
    meta: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None   # {comparative_notes, competencies, digital_finance_literacy, ...}
    traits: Optional[Dict[str, Any]] = None      # {ocean:{...}, vulnerability_notes:[...]}
    note: Optional[str] = None

    # 공통
    photo_path: Optional[str] = None
    is_active: Optional[bool] = True


class VictimIntakeSimple(BaseModel):
    # 프론트 입력: 체크리스트 줄글 배열 + OCEAN 순서 결과
    name: str = Field(..., max_length=100)
    age: Optional[str] = None
    education: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None

    # 체크리스트 한 줄씩: "…했는가? 예" 또는 "…하는가? 아니오" 등
    # (줄글 통으로 받아도 되지만, 줄 단위 배열이 안전합니다)
    checklist_lines: List[str]

    # OCEAN 결과(순서 고정): [개방성, 성실성, 외향성, 친화성, 신경성]
    # 각 요소는 "높다" 또는 "낮다"
    ocean_levels: List[str]  # 길이 5 가정

    photo_path: Optional[str] = None
    is_active: bool = True
class VictimOut(BaseModel):
    id: int
    name: str
    meta: dict
    knowledge: dict
    traits: dict
    is_active: bool                               # ✅ 출력에도 포함
    photo_path: Optional[str] = None              # ✅ 출력에도 포함

    model_config = ConfigDict(from_attributes=True)





