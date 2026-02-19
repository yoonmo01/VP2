# app/services/agent/guideline_repo_db.py
from typing import Tuple
from sqlalchemy.orm import Session
from app.db import models as m


class GuidelineRepoDB:

    def __init__(self, db: Session):
        self.db = db

    def pick_preventive(self) -> Tuple[str, str]:
        row = (self.db.query(
            m.Preventive).filter(m.Preventive.is_active == True).order_by(
                m.Preventive.id.asc()).first())
        if not row:
            raise RuntimeError("No preventive guideline found")
        body = row.body or {}
        text = body.get("summary") or body.get("steps") or row.title
        if isinstance(text, list): text = "\n".join(map(str, text))
        return str(text), row.title

    def pick_attack(self) -> Tuple[str, str]:
        row = (self.db.query(m.Attack).filter(
            m.Attack.is_active == True).order_by(m.Attack.id.asc()).first())
        if not row:
            raise RuntimeError("No attack guideline found")
        body = row.body or {}
        text = body.get("opening") or body.get("summary") or body.get(
            "script") or row.title
        if isinstance(text, list): text = "\n".join(map(str, text))
        return str(text), row.title
