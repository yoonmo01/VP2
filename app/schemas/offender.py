#app/schemas/offender.py
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from typing import Any, Optional, Dict,List

class OffenderCreate(BaseModel):
    name: str = Field(..., max_length=100)
    type: str = Field(..., max_length=50)
    purpose: str
    steps: List[str]
class ProfileIn(BaseModel):
    purpose: str
    steps: List[str]

class SourceIn(BaseModel):
    title: str
    page: str
    url: HttpUrl | str  # 내부망/로컬도 허용하려면 str로 둬도 됨

class OffenderCreateIn(BaseModel):
    name: str
    type: str
    profile: ProfileIn
    source: Optional[SourceIn] = None  # 프론트가 보낼 수도 있으니 허용
    
class OffenderOut(BaseModel):
    id: int
    name: str
    type: Optional[str] = None
    profile: Dict[str, Any]
    source: Dict[str, Any]                                  # ✅ 응답에도 포함
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
