# vp_mcp/mcp_server/services.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, asc

from .db import models as m  # ORM 모델 모듈 (프로젝트에 맞춰 존재한다고 가정)


def _normalize_turn(role: Any, text: Any, meta: Any = None) -> Dict[str, Any]:
    """role/text/meta를 표준 딕셔너리로 정규화"""
    r = str(role or "").strip() or "unknown"
    t = "" if text is None else str(text)
    return {"role": r, "text": t, "meta": (meta or {})}


def _try_fetch_from_conversation_turn(
    db: Session, case_id: UUID, run_no: Optional[int]
) -> Optional[List[Dict[str, Any]]]:
    """모델명이 ConversationTurn일 때 시도"""
    if not hasattr(m, "ConversationTurn"):
        return None
    Model = getattr(m, "ConversationTurn")

    q = db.query(Model).filter(Model.case_id == case_id)
    if run_no is not None and hasattr(Model, "run"):
        q = q.filter(Model.run == run_no)

    # 정렬 우선순위: order/turn_no/created_at
    if hasattr(Model, "order"):
        q = q.order_by(asc(Model.order))
    elif hasattr(Model, "turn_no"):
        q = q.order_by(asc(Model.turn_no))
    elif hasattr(Model, "created_at"):
        q = q.order_by(asc(Model.created_at))

    rows = q.all()
    if not rows:
        return []

    turns: List[Dict[str, Any]] = []
    for r in rows:
        role = getattr(r, "role", None) or getattr(r, "speaker", None)
        text = getattr(r, "text", None) or getattr(r, "content", None) or getattr(r, "message", None)
        meta = getattr(r, "meta", None) or getattr(r, "extra", None) or {}
        turns.append(_normalize_turn(role, text, meta))
    return turns


def _try_fetch_from_conversation_log(
    db: Session, case_id: UUID, run_no: Optional[int]
) -> Optional[List[Dict[str, Any]]]:
    """모델명이 ConversationLog일 때 시도"""
    if not hasattr(m, "ConversationLog"):
        return None
    Model = getattr(m, "ConversationLog")

    q = db.query(Model).filter(Model.case_id == case_id)
    if run_no is not None and hasattr(Model, "run"):
        q = q.filter(Model.run == run_no)

    if hasattr(Model, "turn_index"):
        q = q.order_by(asc(Model.turn_index))
    elif hasattr(Model, "created_at"):
        q = q.order_by(asc(Model.created_at))

    rows = q.all()
    if not rows:
        return []

    turns: List[Dict[str, Any]] = []
    for r in rows:
        role = getattr(r, "role", None) or getattr(r, "speaker", None)
        text = getattr(r, "text", None) or getattr(r, "content", None)
        meta = getattr(r, "meta", None) or {}
        turns.append(_normalize_turn(role, text, meta))
    return turns


def _try_fetch_from_conversation_messages_relation(
    db: Session, case_id: UUID, run_no: Optional[int]
) -> Optional[List[Dict[str, Any]]]:
    """
    모델이 Conversation(또는 Case)이고, messages라는 relation을 통해 메시지를 들고 있을 때 시도.
    예상 구조:
      m.Conversation(id, case_id, run, messages=[Message(role,text,meta,...)])
    """
    # 가장 흔한 이름 몇 개를 순회
    container_names = ["Conversation", "CaseConversation", "ChatConversation"]
    message_names = ["Message", "ConversationMessage", "ChatMessage"]

    Container = None
    for name in container_names:
        if hasattr(m, name):
            Container = getattr(m, name)
            break
    if Container is None:
        return None

    q = db.query(Container).filter(getattr(Container, "case_id", None) == case_id)
    if run_no is not None and hasattr(Container, "run"):
        q = q.filter(Container.run == run_no)

    conv = q.first()
    if not conv:
        return []

    # messages relation 찾기
    messages = None
    for attr in ["messages", "logs", "turns"]:
        if hasattr(conv, attr):
            messages = getattr(conv, attr)
            break
    if messages is None:
        return []

    # 메시지 모델에서 정렬 가능한 필드 확인
    if len(messages) > 0:
        msg0 = messages[0]
        order_key = None
        for k in ["order", "turn_no", "index", "created_at", "id"]:
            if hasattr(msg0, k):
                order_key = k
                break
        if order_key:
            messages = sorted(messages, key=lambda x: getattr(x, order_key))

    turns: List[Dict[str, Any]] = []
    for msg in messages:
        role = getattr(msg, "role", None) or getattr(msg, "speaker", None)
        text = getattr(msg, "text", None) or getattr(msg, "content", None)
        meta = getattr(msg, "meta", None) or {}
        turns.append(_normalize_turn(role, text, meta))
    return turns


def fetch_turns_json(db: Session, *, case_id: UUID, run_no: Optional[int]) -> Dict[str, Any]:
    """
    주어진 (case_id, run_no)에 대한 전체 대화 턴을 표준 JSON으로 반환.
    반환 형식:
      {
        "case_id": "...",
        "run": <int|None>,
        "turns": [ {role, text, meta}, ... ]
      }
    """
    # 1) 모델 패턴별 시도
    for getter in (
        _try_fetch_from_conversation_turn,
        _try_fetch_from_conversation_log,
        _try_fetch_from_conversation_messages_relation,
    ):
        try:
            turns = getter(db, case_id, run_no)
        except Exception:
            # 모델/스키마가 달라 실패 시 다음 시도
            continue
        if turns is not None:
            return {"case_id": str(case_id), "run": run_no, "turns": turns}

    # 다 실패하면 404
    raise HTTPException(status_code=404, detail="해당 case_id/run에 대한 대화 로그를 찾을 수 없습니다.")
