from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings



engine = create_engine(settings.sqlalchemy_url,
                       echo=settings.SYNC_ECHO,
                       pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def try_get_db():
    """DB 세션을 시도하되 실패하면 None을 반환한다."""
    try:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    except Exception:
        # DB 미설정/연결 실패 시 None
        yield None
