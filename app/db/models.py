# app/db/models.py
from __future__ import annotations
from sqlalchemy import (Column, Integer, String, Boolean, Text, ForeignKey,
                        TIMESTAMP, Index, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from uuid import uuid4
from datetime import datetime, timezone
from app.db.base import Base
import sqlalchemy as sa

# 1) 피싱범
class PhishingOffender(Base):
    __tablename__ = "phishingoffender"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))


# 2) 피해자
class Victim(Base):
    __tablename__ = "victim"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    knowledge: Mapped[dict] = mapped_column(JSONB, default=dict)
    traits: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))


# 3) 관리자 케이스
# AdminCase (추가 필드)
class AdminCase(Base):
    __tablename__ = "admincase"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    scenario: Mapped[dict] = mapped_column(JSONB, default=dict)

    # 기존
    phishing: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running")
    defense_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # ✅ 추가(최근 라운드 요약)
    last_run_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_risk_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_vulnerabilities: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # list -> JSONB
    last_recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)  # continue/stop
    last_recommendation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)



# 4) 대화 로그 (하이브리드: TEXT + JSONB)
class ConversationLog(Base):
    __tablename__ = "conversationlog"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True),
                                     primary_key=True,
                                     default=uuid4)
    case_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True),
                                          ForeignKey("admincase.id"),
                                          index=True)
    offender_id: Mapped[int] = mapped_column(ForeignKey("phishingoffender.id"))
    victim_id: Mapped[int] = mapped_column(ForeignKey("victim.id"))
    turn_index: Mapped[int] = mapped_column(Integer)  # 정렬 키 유지
    role: Mapped[str] = mapped_column(String(20))  # offender/victim
    content: Mapped[str] = mapped_column(Text)  # 기존 유지(점진 전환)
    label: Mapped[str | None] = mapped_column(String(20))
    payload: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # ✅ 새 컬럼 4개
    use_agent: Mapped[bool] = mapped_column(Boolean,
                                            default=False,
                                            nullable=False)  # ← 기본 False
    run: Mapped[int] = mapped_column(Integer, default=1,
                                     nullable=False)  # ← 기본 1
    guidance_type: Mapped[str | None] = mapped_column(
        String(1), nullable=True)  # 'P'|'A' or None
    guideline: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    case = relationship("AdminCase")

    __table_args__ = (
        Index("ix_conv_case_turn", "case_id", "turn_index"),
        Index("ix_conv_case_run_turn", "case_id", "run", "turn_index"),
        UniqueConstraint("case_id",
                         "run",
                         "turn_index",
                         name="uq_case_run_turn"),
    )

# 4-1) 라운드 별 대화로그 저장
class ConversationRound(Base):
    __tablename__ = "conversation_round"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # 라운드 식별
    case_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admincase.id"), index=True, nullable=False
    )
    run: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)

    # 편의(조회용)
    offender_id: Mapped[int] = mapped_column(
        ForeignKey("phishingoffender.id"), nullable=False
    )
    victim_id: Mapped[int] = mapped_column(
        ForeignKey("victim.id"), nullable=False
    )

    # MCP 반환 본문
    turns: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=list  # ← 리스트(턴 배열)
    )
    ended_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    case = relationship("AdminCase")

    __table_args__ = (
        UniqueConstraint("case_id", "run", name="uq_round_case_run"),
        Index("ix_round_case_run", "case_id", "run"),
    )



# 5) 예방 대책(카탈로그) — JSONB 본문 저장
class Preventive(Base):
    __tablename__ = "preventive"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150),
                                       nullable=False,
                                       unique=True)
    category: Mapped[str | None] = mapped_column(String(50))
    body: Mapped[dict] = mapped_column(JSONB, default=dict)  # 실제 대책 JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))


# 6) 공격 시나리오(카탈로그) — JSONB 본문 저장
class Attack(Base):
    __tablename__ = "attack"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150),
                                       nullable=False,
                                       unique=True)
    category: Mapped[str | None] = mapped_column(String(50))
    body: Mapped[dict] = mapped_column(JSONB, default=dict)  # 실제 시나리오 JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))


# 7) 맞춤형 예방법 — 에이전트 생성물
class PersonalizedPrevention(Base):
    __tablename__ = "personalized_prevention"
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True),
                                     primary_key=True,
                                     default=uuid4)
    case_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True),
                                                 ForeignKey("admincase.id"),
                                                 index=True)
    offender_id: Mapped[int | None] = mapped_column(
        ForeignKey("phishingoffender.id"))
    victim_id: Mapped[int | None] = mapped_column(ForeignKey("victim.id"))
    run: Mapped[int | None] = mapped_column(Integer,
                                            nullable=True)  # 어느 세션 결과인지
    source_log_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversationlog.id"))

    content: Mapped[dict] = mapped_column(
        JSONB,
        default=dict)  # 예: {"summary": "...", "steps":[...], "tips":[...]}
    note: Mapped[str | None] = mapped_column(Text)  # 간단한 메모/사유
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_pp_case_run_victim", "case_id", "run",
                            "victim_id"), )
