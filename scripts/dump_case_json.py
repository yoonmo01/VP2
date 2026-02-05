# VP/scripts/dump_case_json.py
from __future__ import annotations

import asyncio
import os
from dotenv import load_dotenv
import uuid
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values

#
# ✅ .env를 "이 스크립트 실행 프로세스"에 확실히 로드
#   - VP/.env, VP/app/.env 둘 다 로드 (필요한 쪽만 남겨도 됨)
#
_ROOT = Path(__file__).resolve().parents[1]      # .../VP
env1 = _ROOT / ".env"
env2 = _ROOT / "app" / ".env"

print(f"[ENV-DEBUG] cwd={os.getcwd()}")
print(f"[ENV-DEBUG] env1={env1} exists={env1.exists()}")
print(f"[ENV-DEBUG] env2={env2} exists={env2.exists()}")
print(f"[ENV-DEBUG] BEFORE load_dotenv: EMOTION_ENABLED={os.getenv('EMOTION_ENABLED')!r}")

r1 = load_dotenv(env1, override=False)
r2 = load_dotenv(env2, override=False)
print(f"[ENV-DEBUG] load_dotenv(env1)={r1}, load_dotenv(env2)={r2} (True=파일 로드 시도 성공)")
print(f"[ENV-DEBUG] AFTER load_dotenv:  EMOTION_ENABLED={os.getenv('EMOTION_ENABLED')!r}")

# 파일 내부 값도 직접 확인(덮어쓰기와 무관하게 '파일에 뭐가 적혀있나' 확인)
if env1.exists():
    print(f"[ENV-DEBUG] env1 values: EMOTION_ENABLED={dotenv_values(env1).get('EMOTION_ENABLED')!r}")
if env2.exists():
    print(f"[ENV-DEBUG] env2 values: EMOTION_ENABLED={dotenv_values(env2).get('EMOTION_ENABLED')!r}")

from app.db.session import SessionLocal
from app.services.agent.orchestrator_react import run_orchestrated, _ensure_stream


# =========================
# ✅ 여기만 수정하면 됨
# =========================
OFFENDER_ID = 4          # 피싱범 id
VICTIM_ID = 1            # 피해자 id

MAX_TURNS = 20           # 한 라운드 최대 턴 수 (피싱범+피해자 교환 포함 구조면 orchestrator 기준에 맞춰 유지)
ROUND_LIMIT = 5          # UI 제한(max 3) 걸려있으면 3 이하로
USE_TAVILY = False       # 필요하면 True

# JSON 저장 폴더 (상대경로 가능)
DUMP_DIR = "C:/LIT_VP2/VP/scripts/case_json_0123"
# ✅ 목표: 성공 JSON 몇 개 모을지
TARGET_JSON = 1
# ✅ 안전장치: 최대 시도 횟수(너무 많이 실패하면 종료)
MAX_ATTEMPTS = 1
# ✅ 시도 간 쉬기(레이트/서버 부하 완화)
SLEEP_SEC = 0.2
# =========================

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

async def main():
    dump_dir = os.getenv("VP_CASE_DUMP_DIR", DUMP_DIR)
    root = Path(dump_dir)
    ok_dir = root / "ok"
    fail_dir = root / "failed"
    ok_dir.mkdir(parents=True, exist_ok=True)
    fail_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    attempts = 0

    while success < TARGET_JSON and attempts < MAX_ATTEMPTS:
        attempts += 1

        # ✅ 매 시도마다 stream_id 새로 발급 + asyncio loop에서 stream 먼저 생성
        stream_id = str(uuid.uuid4())
        _ensure_stream(stream_id)

        payload = {
            "offender_id": OFFENDER_ID,
            "victim_id": VICTIM_ID,

            "max_turns": MAX_TURNS,
            "round_limit": ROUND_LIMIT,
            "use_tavily": USE_TAVILY,

            # ✅ orchestrator_react.py에 추가한 덤프 옵션
            "dump_case_json": True,
            "dump_dir": str(ok_dir),
            # ✅ orchestrator_react 내부 SSE/loop 의존성 때문에 필요
            "stream_id": stream_id,
        }

        def _work():
            with SessionLocal() as db:
                return run_orchestrated(db, payload)

        try:
            result = await asyncio.to_thread(_work)

            artifact_path = result.get("artifact_path") if isinstance(result, dict) else None
            case_id = result.get("case_id") if isinstance(result, dict) else None

            if artifact_path:
                success += 1
                print(f"[OK {success}/{TARGET_JSON}] case_id={case_id} artifact={artifact_path}")
            else:
                # ✅ 보험: artifact_path가 없으면 result 자체라도 저장
                success += 1
                fallback = ok_dir / f"fallback_{_ts()}_{stream_id}.json"
                _write_json(fallback, {
                    "note": "artifact_path missing; saved fallback result",
                    "payload": payload,
                    "result": result,
                })
                print(f"[OK* {success}/{TARGET_JSON}] saved fallback={fallback}")

        except Exception as e:
            # ✅ 실패해도 종료하지 않고 기록만 남기고 다음 케이스로 진행
            err_path = fail_dir / f"error_{_ts()}_{stream_id}.json"
            _write_json(err_path, {
                "ok": False,
                "error": str(e),
                "payload": payload,
                "traceback": traceback.format_exc(),
            })
            print(f"[FAIL attempt={attempts}] saved error={err_path}")

        if SLEEP_SEC:
            time.sleep(SLEEP_SEC)

    print("\n=== DONE ===")
    print(f"success={success}, attempts={attempts}, ok_dir={ok_dir}, failed_dir={fail_dir}")


if __name__ == "__main__":
    asyncio.run(main())
