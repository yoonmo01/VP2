# app/services/agent_orchestrator.py
from __future__ import annotations
from typing import Optional, Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID

from app.db import models as m
from app.services.admin_summary import summarize_case
from app.services.simulation import run_two_bot_simulation  # 기존 것 재사용
from types import SimpleNamespace

# --------------------------------------------
# 유틸: UUID 보정
# --------------------------------------------
def _to_uuid(v: Any) -> UUID:
    if isinstance(v, UUID):
        return v
    return UUID(str(v))

# 0) case 내 다음 run 번호
def next_run_no(db: Session, case_id: UUID) -> int:
    q = db.query(func.coalesce(func.max(m.ConversationLog.run), 0))\
          .filter(m.ConversationLog.case_id == case_id)
    return int(q.scalar() or 0) + 1

# --------------------------------------------
# B-1) AdminCase 없으면 만들어주기 (브릿지)
# --------------------------------------------
def _ensure_admin_case(db: Session, case_id: UUID, offender_id: Optional[int], victim_id: Optional[int]) -> None:
    """
    MCP에서 받은 conversation_id를 에이전트 쪽 AdminCase로 보정.
    이미 있으면 아무것도 안 함.
    """
    obj = db.get(m.AdminCase, case_id)
    if obj is not None:
        return
    # AdminCase 컬럼 정의에 따라 최소 필드만 안전하게 세팅
    obj = m.AdminCase(
        id=case_id,
        offender_id=offender_id,
        victim_id=victim_id,
    )
    db.add(obj)
    db.flush()  # id 확정

# --------------------------------------------
# B-2) MCP 결과 → ConversationLog 퍼시스트
# --------------------------------------------
def bridge_persist_from_mcp(
    db: Session,
    mcp_payload: Dict[str, Any],
    run_no: Optional[int] = None,
) -> Tuple[UUID, int, int]:
    """
    MCP 서버의 시뮬 결과(JSON)를 받아 에이전트 DB(AdminCase/ConversationLog)에 저장.
    returns: (case_id, total_turns, run_no)
    mcp_payload 형태 예:
      {
        "ok": True,
        "case_id": "uuid-string",
        "total_turns": 15,
        "result": {
          "conversation_id": "uuid-string",
          "turns": [{"role": "offender", "text": "..."}, ...],
          "ended_by": "max_turns",
          "stats": {"half_turns": 30, "turns": 15},
          "meta": {"offender_id": 3, "victim_id": 2, ...}
        }
      }
    """
    # 1) 껍데기/내부 결과 정규화
    res: Dict[str, Any] = mcp_payload.get("result") or mcp_payload
    cid_str = res.get("conversation_id") or mcp_payload.get("case_id")
    if not cid_str:
        raise ValueError("MCP payload missing conversation_id/case_id")

    case_id = _to_uuid(cid_str)
    turns: List[Dict[str, Any]] = res.get("turns") or []
    stats = res.get("stats") or {}
    meta = res.get("meta") or {}

    offender_id = meta.get("offender_id")
    victim_id = meta.get("victim_id")

    # 2) AdminCase 보장
    _ensure_admin_case(db, case_id, offender_id, victim_id)

    # 3) run 할당 (없으면 next_run_no)
    use_run = run_no if run_no is not None else next_run_no(db, case_id)

    # 4) 중복 방지: 이미 동일 run/idx 가 있으면 스킵
    #    (간단히 존재여부만 확인)
    existing_idx = {
        r[0]
        for r in db.query(m.ConversationLog.idx)
                   .filter(m.ConversationLog.case_id == case_id,
                           m.ConversationLog.run == use_run)
                   .all()
    }

    # 5) 턴 적재
    for idx, t in enumerate(turns):
        if idx in existing_idx:
            continue
        role = t.get("role")
        text = t.get("text")

        row = m.ConversationLog(
            case_id=case_id,
            run=use_run,
            idx=idx,
            role=role,
            text=text,
        )
        db.add(row)

    db.commit()

    total_turns = stats.get("turns")
    if total_turns is None:
        # 안전망: half_turns/2 또는 리스트 길이로 추정
        ht = stats.get("half_turns")
        total_turns = int(ht // 2) if isinstance(ht, int) else (len(turns) // 2)

    return case_id, int(total_turns), int(use_run)

# 1) 공격/예방 어떤 지침을 쓸지 자동 판단
def decide_guidance_kind(db: Session, case_id: UUID) -> str:
    """
    summarize_case(db, case_id) -> {"phishing": bool, ...}
    기본 로직:
      - 이미 당했다(phishing=True): 예방(P)으로 방어 강화
      - 아직 아니다(False): 공격(A)로 도전 강도 상향(레드팀)
    """
    try:
        res = summarize_case(db, case_id) or {}
        phishing = res.get("phishing")
    except Exception:
        phishing = None

    if phishing is True:
        return "P"
    if phishing is False:
        return "A"
    # 판단 실패 시 기본은 예방(P)
    return "P"

# 2) 지침 하나 고르기 (카테고리 매칭 등은 필요시 보강)
def pick_guideline(db: Session, kind: str) -> Tuple[str, str]:
    """
    kind: 'P'|'A'
    return: (guideline_text, title)
    """
    if kind == "P":
        row = (db.query(m.Preventive)
                 .filter(m.Preventive.is_active == True)
                 .order_by(m.Preventive.id.asc())
                 .first())
        if not row:
            raise RuntimeError("no preventive guideline found")
        return (row.body or {}).get("summary") or row.title, row.title
    else:
        row = (db.query(m.Attack)
                 .filter(m.Attack.is_active == True)
                 .order_by(m.Attack.id.asc())
                 .first())
        if not row:
            raise RuntimeError("no attack guideline found")
        body = row.body or {}
        text = body.get("opening") or body.get("summary") or row.title
        return text, row.title

# 3) 같은 case로 재시뮬 돌리기 (지침 주입)
def rerun_with_guidance(
    db: Session,
    case_id: UUID,
    offender_id: int,
    victim_id: int,
    guidance_type: str,  # 'P' or 'A'
    guideline_text: str,
) -> Tuple[UUID, int, int]:
    """
    returns: (case_id, total_turns, run_no)
    내부적으로 run_no=next_run_no, use_agent=True로 표기.
    run_two_bot_simulation 에서 'guideline'을 프롬프트에 반영하도록 약속한다.
    """
    run_no = next_run_no(db, case_id)

    args = SimpleNamespace(
        offender_id=offender_id,
        victim_id=victim_id,
        include_judgement=True,
        max_turns=30,
        agent_mode="admin",
        case_scenario={
            "guidance_type": guidance_type,
            "guideline": guideline_text
        },
        case_id_override=case_id,
        run_no=run_no,
        use_agent=True,
        guidance_type=guidance_type,
        guideline=guideline_text,
    )

    case_id2, total_turns = run_two_bot_simulation(db, args)
    return case_id2, total_turns, run_no

# 4) 맞춤형 예방법 저장 (에이전트 "생각만으로")
def save_personalized_prevention(
    db: Session,
    case_id: UUID,
    offender_id: int,
    victim_id: int,
    run_no: int,
    source_log_id: Optional[UUID] = None,
) -> UUID:
    """
    실제 생성은 LLM으로 하겠지만, 여기서는 저장만 캡슐화.
    content 스키마는 프로젝트 합의에 맞춰 자유롭게 확장.
    """
    content = {
        "summary": "피해자 특성 기반 맞춤형 예방 가이드",
        "steps": [
            "송금·인증요청은 반드시 2차 채널로 재확인",
            "링크/QR 클릭 금지, 앱 설치 요구 차단",
            "의심 시 112 또는 1332 즉시 신고",
        ],
    }
    obj = m.PersonalizedPrevention(
        case_id=case_id,
        offender_id=offender_id,
        victim_id=victim_id,
        run=run_no,
        source_log_id=source_log_id,
        content=content,
        note="agent-generated",
        is_active=True,
    )
    db.add(obj)
    db.flush()
    return obj.id
