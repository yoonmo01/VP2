# models.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Text
from .base import Base
import uuid, json

class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    ended_by: Mapped[str] = mapped_column(String(64), default="")

    @classmethod
    def create(cls, db, meta: dict) -> "Conversation":
        row = cls(meta_json=json.dumps(meta, ensure_ascii=False))
        db.add(row); db.commit(); db.refresh(row)
        return row

class TurnLog(Base):
    __tablename__ = "turn_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    idx: Mapped[int] = mapped_column(Integer)         # 반쪽 턴 index
    role: Mapped[str] = mapped_column(String(8))      # "offender"|"victim"
    text: Mapped[str] = mapped_column(Text)
