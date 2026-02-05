# # seed.py
# import json
# from pathlib import Path
# from typing import Any

# from app.db.base import Base
# from app.db.session import engine, SessionLocal
# from app.db import models as m

# from sqlalchemy import text
# print("ENGINE_URL =", engine.url)

# with engine.connect() as conn:
#     row = conn.execute(text("select current_database(), current_user")).fetchone()
#     print("DB CHECK:", row)

# BASE_DIR = Path(__file__).parent
# SEEDS_DIR = BASE_DIR / "seeds"

# OFFENDERS_JSON = SEEDS_DIR / "offenders_v2.json"
# VICTIMS_JSON   = SEEDS_DIR / "victims_v2.json"
# SCENARIO_JSON  = SEEDS_DIR / "scenario.json"  # 옵션: 출력용

# def load_json(path: Path) -> Any:
#     with path.open("r", encoding="utf-8") as f:
#         return json.load(f)

# def main() -> None:
#     # 1) 테이블 생성 (없으면 생성)
#     Base.metadata.create_all(bind=engine)

#     db = SessionLocal()
#     try:
#         offenders = load_json(OFFENDERS_JSON) if OFFENDERS_JSON.exists() else []
#         victims   = load_json(VICTIMS_JSON) if VICTIMS_JSON.exists() else []
#         scenario  = load_json(SCENARIO_JSON) if SCENARIO_JSON.exists() else None

#         # 2) 피싱범 upsert (이름 중복 방지: name 기준 존재 시 업데이트)
#         offender_ids = []
#         for o in offenders:
#             name = (o.get("name") or "").strip()
#             if not name:
#                 continue

#             existing = db.query(m.PhishingOffender).filter(m.PhishingOffender.name == name).first()
#             if existing:
#                 # 존재하면 업데이트
#                 existing.type      = o.get("type")
#                 existing.profile   = o.get("profile", {}) or {}
#                 existing.is_active = bool(o.get("is_active", True))
#                 existing.source    = o.get("source") or {}     # ✅ 출처 저장
#                 db.add(existing)
#                 db.flush()
#                 offender_ids.append(existing.id)
#             else:
#                 # 없으면 생성
#                 obj = m.PhishingOffender(
#                     name=name,
#                     type=o.get("type"),
#                     profile=o.get("profile", {}) or {},
#                     is_active=bool(o.get("is_active", True)),
#                     source=o.get("source") or {},              # ✅ 출처 저장
#                 )
#                 db.add(obj)
#                 db.flush()  # id 확보
#                 offender_ids.append(obj.id)

#         # 3) 피해자 upsert (이름 중복 방지: name 기준)
#         victim_ids = []
#         for v in victims:
#             name = (v.get("name") or "").strip()
#             if not name:
#                 continue

#             existing = db.query(m.Victim).filter(m.Victim.name == name).first()
#             if existing:
#                 existing.meta       = v.get("meta", {}) or {}
#                 existing.knowledge  = v.get("knowledge", {}) or {}
#                 existing.traits     = v.get("traits", {}) or {}
#                 existing.is_active  = bool(v.get("is_active", True))
#                 existing.photo_path = v.get("photo_path")   # ✅ 추가
#                 db.add(existing)
#                 db.flush()
#                 victim_ids.append(existing.id)
#             else:
#                 obj = m.Victim(
#                     name=name,
#                     meta=v.get("meta", {}) or {},
#                     knowledge=v.get("knowledge", {}) or {},
#                     traits=v.get("traits", {}) or {},
#                     is_active=bool(v.get("is_active", True)),
#                     photo_path=v.get("photo_path"),         # ✅ 추가
#                 )
#                 db.add(obj)
#                 db.flush()
#                 victim_ids.append(obj.id)

#         db.commit()

#         print({
#             "offender_ids": offender_ids,
#             "victim_ids": victim_ids,
#             "scenario": scenario  # 시뮬 호출 때 그대로 사용 가능
#         })

#     finally:
#         db.close()

# if __name__ == "__main__":
#     main()

# app/db/seed.py  (경로는 현재 seed.py 위치 기준으로 조정)
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db import models as m

print("ENGINE_URL =", engine.url)

with engine.connect() as conn:
    row = conn.execute(
        text("select current_database(), current_user")).fetchone()
    print("DB CHECK:", row)

BASE_DIR = Path(__file__).parent
SEEDS_DIR = BASE_DIR / "seeds"

OFFENDERS_JSON = SEEDS_DIR / "offenders_v2.json"
VICTIMS_JSON = SEEDS_DIR / "victims_paper.json"
SCENARIO_JSON = SEEDS_DIR / "scenario.json"  # 옵션: 출력용

# ✅ 신규 시드 파일(있으면 upsert)
PREVENTIVE_JSON = SEEDS_DIR / "preventive_v1.json"
ATTACK_JSON = SEEDS_DIR / "attack_v1.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def patch_conversationlog_schema() -> None:
    """Alembic 없이 대화로그 테이블에 새 컬럼/인덱스를 안전 추가."""
    ddl = [
        # 1) 새 컬럼(없으면 추가) + 기본값/NOT NULL 정합성 확보
        "ALTER TABLE conversationlog ADD COLUMN IF NOT EXISTS use_agent boolean",
        "ALTER TABLE conversationlog ADD COLUMN IF NOT EXISTS run integer",
        "ALTER TABLE conversationlog ADD COLUMN IF NOT EXISTS guidance_type varchar(1)",
        "ALTER TABLE conversationlog ADD COLUMN IF NOT EXISTS guideline text",

        # 기존 컬럼이 있을 수도 있으니 기본값/NOT NULL을 별도로 강제
        "ALTER TABLE conversationlog ALTER COLUMN use_agent SET DEFAULT false",
        "UPDATE conversationlog SET use_agent = false WHERE use_agent IS NULL",
        "ALTER TABLE conversationlog ALTER COLUMN use_agent SET NOT NULL",
        "ALTER TABLE conversationlog ALTER COLUMN run SET DEFAULT 1",
        "UPDATE conversationlog SET run = 1 WHERE run IS NULL",
        "ALTER TABLE conversationlog ALTER COLUMN run SET NOT NULL",

        # 2) 인덱스
        "CREATE INDEX IF NOT EXISTS ix_conv_case_run_turn ON conversationlog (case_id, run, turn_index)",

        # (선택) 예전 인덱스도 만들어두고 싶다면
        "CREATE INDEX IF NOT EXISTS ix_conv_case_turn ON conversationlog (case_id, turn_index)",

        # 3) 유니크 제약: (case_id, turn_index) → (case_id, run, turn_index)
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_case_turn') THEN
            ALTER TABLE conversationlog DROP CONSTRAINT uq_case_turn;
          END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_case_run_turn') THEN
            ALTER TABLE conversationlog ADD CONSTRAINT uq_case_run_turn UNIQUE (case_id, run, turn_index);
          END IF;
        END $$;
        """,

        # (선택) guidance_type 값 검증
        # "ALTER TABLE conversationlog ADD CONSTRAINT ck_guidance_type CHECK (guidance_type IN ('P','A') OR guidance_type IS NULL)",
    ]
    with engine.begin() as conn:
        for sql in ddl:
            conn.execute(text(sql))


def main() -> None:
    # 1) 신규 테이블 생성 (없으면 생성)
    Base.metadata.create_all(bind=engine)

    # 1-1) 기존 테이블 스키마 패치(대화로그 새 컬럼/인덱스)
    patch_conversationlog_schema()

    db = SessionLocal()
    try:
        offenders = load_json(
            OFFENDERS_JSON) if OFFENDERS_JSON.exists() else []
        victims = load_json(VICTIMS_JSON) if VICTIMS_JSON.exists() else []
        scenario = load_json(SCENARIO_JSON) if SCENARIO_JSON.exists() else None

        preventives = load_json(
            PREVENTIVE_JSON) if PREVENTIVE_JSON.exists() else []
        attacks = load_json(ATTACK_JSON) if ATTACK_JSON.exists() else []

        # 2) 피싱범 upsert (name 고유)
        offender_ids = []
        for o in offenders:
            name = (o.get("name") or "").strip()
            if not name:
                continue

            existing = db.query(m.PhishingOffender).filter(
                m.PhishingOffender.name == name).first()
            if existing:
                existing.type = o.get("type")
                existing.profile = o.get("profile", {}) or {}
                existing.is_active = bool(o.get("is_active", True))
                existing.source = o.get("source") or {}
                db.add(existing)
                db.flush()
                offender_ids.append(existing.id)
            else:
                obj = m.PhishingOffender(
                    name=name,
                    type=o.get("type"),
                    profile=o.get("profile", {}) or {},
                    is_active=bool(o.get("is_active", True)),
                    source=o.get("source") or {},
                )
                db.add(obj)
                db.flush()
                offender_ids.append(obj.id)

        # 3) 피해자 upsert (name 고유)
        victim_ids = []
        for v in victims:
            name = (v.get("name") or "").strip()
            if not name:
                continue

            existing = db.query(m.Victim).filter(m.Victim.name == name).first()
            if existing:
                existing.meta = v.get("meta", {}) or {}
                existing.knowledge = v.get("knowledge", {}) or {}
                existing.traits = v.get("traits", {}) or {}
                existing.is_active = bool(v.get("is_active", True))
                existing.photo_path = v.get("photo_path")
                db.add(existing)
                db.flush()
                victim_ids.append(existing.id)
            else:
                obj = m.Victim(
                    name=name,
                    meta=v.get("meta", {}) or {},
                    knowledge=v.get("knowledge", {}) or {},
                    traits=v.get("traits", {}) or {},
                    is_active=bool(v.get("is_active", True)),
                    photo_path=v.get("photo_path"),
                )
                db.add(obj)
                db.flush()
                victim_ids.append(obj.id)

        # 4) 예방 대책 카탈로그 upsert (title 고유)
        preventive_ids = []
        for p in preventives:
            title = (p.get("title") or "").strip()
            if not title:
                continue
            existing = db.query(
                m.Preventive).filter(m.Preventive.title == title).first()
            if existing:
                existing.category = p.get("category")
                existing.body = p.get("body", {}) or {}
                existing.is_active = bool(p.get("is_active", True))
                db.add(existing)
                db.flush()
                preventive_ids.append(existing.id)
            else:
                obj = m.Preventive(
                    title=title,
                    category=p.get("category"),
                    body=p.get("body", {}) or {},
                    is_active=bool(p.get("is_active", True)),
                )
                db.add(obj)
                db.flush()
                preventive_ids.append(obj.id)

        # 5) 공격 시나리오 카탈로그 upsert (title 고유)
        attack_ids = []
        for a in attacks:
            title = (a.get("title") or "").strip()
            if not title:
                continue
            existing = db.query(
                m.Attack).filter(m.Attack.title == title).first()
            if existing:
                existing.category = a.get("category")
                existing.body = a.get("body", {}) or {}
                existing.is_active = bool(a.get("is_active", True))
                db.add(existing)
                db.flush()
                attack_ids.append(existing.id)
            else:
                obj = m.Attack(
                    title=title,
                    category=a.get("category"),
                    body=a.get("body", {}) or {},
                    is_active=bool(a.get("is_active", True)),
                )
                db.add(obj)
                db.flush()
                attack_ids.append(obj.id)

        db.commit()

        print({
            "offender_ids": offender_ids,
            "victim_ids": victim_ids,
            "preventive_ids": preventive_ids,
            "attack_ids": attack_ids,
            "scenario": scenario
        })

    finally:
        db.close()


if __name__ == "__main__":
    main()
