# vp_mcp/mcp_server/db/base.py
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy import create_engine
import os

class Base(DeclarativeBase):
    pass

# 환경변수에서 DB URL 읽기 (PostgreSQL)
DB_URL = os.getenv("MCP_DATABASE_URL", "postgresql+psycopg://mcp:0320@localhost:5432/mcpdb")

# PostgreSQL용 Engine
engine = create_engine(
    DB_URL,
    future=True,
    echo=False,          # True로 하면 SQL 로그 출력
    pool_pre_ping=True   # 연결 유휴 시 자동 체크
)

# 세션 팩토리
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

def init_db():
    # 모델을 임포트해서 메타데이터에 등록
    from .models import Conversation, TurnLog  # noqa: F401
    Base.metadata.create_all(bind=engine)
