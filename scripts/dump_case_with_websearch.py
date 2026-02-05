# VP/scripts/dump_case_with_websearch.py
"""
시뮬레이션 실행 + 판정 + VP-Web-Search 시스템 호출까지 통합 스크립트

1. 시뮬레이션 실행 (orchestrator_react)
2. 판정 생성 (make_judgement)
3. VP-Web-Search 시스템에 대화+판정 전송
4. 결과를 JSON으로 저장
"""
from __future__ import annotations

import asyncio
import os
import sys
from dotenv import load_dotenv
import uuid
import json
import time
import traceback
import httpx
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# .env 로드
_ROOT = Path(__file__).resolve().parents[1]
env1 = _ROOT / ".env"
env2 = _ROOT / "app" / ".env"

print(f"[ENV] Loading .env files...")
load_dotenv(env1, override=False)
load_dotenv(env2, override=False)

# VP-Web-Search 설정
WEBSEARCH_BASE_URL = os.getenv("EXTERNAL_API_BASE_URL", "http://127.0.0.1:8001")
WEBSEARCH_TIMEOUT = float(os.getenv("EXTERNAL_API_TIMEOUT", "120"))

from app.db.session import SessionLocal
from app.services.agent.orchestrator_react import run_orchestrated, _ensure_stream
from app.services.agent.external_api import (
    _strip_emotion_labels_from_turns,
    get_external_client,
)

# =========================
# 설정
# =========================
OFFENDER_ID = 4          # 피싱범 id
VICTIM_ID = 1            # 피해자 id

MAX_TURNS = 20           # 한 라운드 최대 턴 수
ROUND_LIMIT = 5          # 최대 라운드 수
USE_TAVILY = False       # Tavily 웹 검색 사용 여부

# JSON 저장 폴더
DUMP_DIR = str(_ROOT / "scripts" / "case_json_websearch")

# 목표: 성공 JSON 몇 개 모을지
TARGET_JSON = 1

# 안전장치: 최대 시도 횟수
MAX_ATTEMPTS = 3

# 시도 간 쉬기(레이트/서버 부하 완화)
SLEEP_SEC = 1.0

# VP-Web-Search 자동 분석 트리거 여부
AUTO_ANALYZE = False
# =========================


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def check_websearch_health() -> bool:
    """VP-Web-Search 시스템 연결 확인"""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{WEBSEARCH_BASE_URL}/health")
            if response.status_code == 200:
                print(f"[WebSearch] 연결 OK: {WEBSEARCH_BASE_URL}")
                return True
            else:
                print(f"[WebSearch] 연결 실패: status={response.status_code}")
                return False
    except Exception as e:
        print(f"[WebSearch] 연결 실패: {e}")
        return False


def send_to_websearch(
    case_id: str,
    round_no: int,
    turns: List[Dict[str, Any]],
    judgement: Dict[str, Any],
    scenario: Optional[Dict[str, Any]] = None,
    victim_profile: Optional[Dict[str, Any]] = None,
    auto_analyze: bool = False,
) -> Dict[str, Any]:
    """
    VP-Web-Search에 판정+대화 전송

    Args:
        case_id: 케이스 ID
        round_no: 라운드 번호
        turns: 대화 turns (감정 라벨 포함 가능 - 함수 내에서 제거)
        judgement: 판정 결과
        scenario: 시나리오 정보
        victim_profile: 피해자 프로필
        auto_analyze: 자동 분석 트리거 여부

    Returns:
        VP-Web-Search 응답
    """
    # 감정 라벨 제거
    clean_turns = _strip_emotion_labels_from_turns(turns)

    print(f"[WebSearch] 전송 준비: case_id={case_id}, round={round_no}, turns={len(clean_turns)}")

    payload = {
        "case_id": str(case_id),
        "round_no": round_no,
        "turns": clean_turns,
        "judgement": judgement,
        "scenario": scenario or {},
        "victim_profile": victim_profile or {},
        "timestamp": datetime.now().isoformat(),
        "source": "dump_script",
    }

    url = f"{WEBSEARCH_BASE_URL}/api/v1/judgements"
    params = {"auto_analyze": "true" if auto_analyze else "false"}

    try:
        with httpx.Client(timeout=WEBSEARCH_TIMEOUT) as client:
            response = client.post(
                url,
                json=payload,
                params=params,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code == 200:
            result = response.json()
            print(f"[WebSearch] 전송 성공: received_id={result.get('received_id')}")
            return {
                "ok": True,
                "response": result,
                "turns_sent": len(clean_turns),
            }
        else:
            print(f"[WebSearch] 전송 실패: status={response.status_code}, body={response.text[:500]}")
            return {
                "ok": False,
                "status_code": response.status_code,
                "error": response.text[:500],
            }

    except Exception as e:
        print(f"[WebSearch] 전송 예외: {e}")
        return {
            "ok": False,
            "error": str(e),
        }


def extract_simulation_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    orchestrator_react 결과에서 필요한 데이터 추출

    Returns:
        {
            "case_id": str,
            "rounds": int,
            "turns": List[Dict],
            "judgements": List[Dict],
            "scenario": Dict,
            "victim_profile": Dict,
        }
    """
    case_id = result.get("case_id", "")
    rounds = result.get("rounds", 1)

    # turns 추출 (다양한 구조 지원)
    turns = []
    if "all_turns" in result:
        turns = result["all_turns"]
    elif "turns" in result:
        turns = result["turns"]
    elif "artifact" in result and isinstance(result["artifact"], dict):
        turns = result["artifact"].get("turns", [])

    # judgements 추출
    judgements = []
    if "judgements" in result:
        judgements = result["judgements"]
    elif "all_judgements" in result:
        judgements = result["all_judgements"]
    elif "artifact" in result and isinstance(result["artifact"], dict):
        judgements = result["artifact"].get("judgements", [])

    # 마지막 판정 추출
    last_judgement = {}
    if judgements:
        last_judgement = judgements[-1] if isinstance(judgements[-1], dict) else {}
    elif "phishing" in result:
        last_judgement = {
            "phishing": result.get("phishing"),
            "risk": result.get("risk", {}),
            "evidence": result.get("evidence", ""),
            "victim_vulnerabilities": result.get("victim_vulnerabilities", []),
        }

    # 시나리오/피해자 프로필
    scenario = result.get("scenario", {})
    victim_profile = result.get("victim_profile", {})

    return {
        "case_id": str(case_id),
        "rounds": rounds,
        "turns": turns,
        "judgements": judgements,
        "last_judgement": last_judgement,
        "scenario": scenario,
        "victim_profile": victim_profile,
    }


async def run_single_case(
    ok_dir: Path,
    fail_dir: Path,
    attempt: int,
) -> Dict[str, Any]:
    """
    단일 케이스 실행

    Returns:
        {
            "success": bool,
            "case_id": str,
            "simulation_result": Dict,
            "websearch_result": Dict,
            "artifact_path": str,
        }
    """
    stream_id = str(uuid.uuid4())
    _ensure_stream(stream_id)

    payload = {
        "offender_id": OFFENDER_ID,
        "victim_id": VICTIM_ID,
        "max_turns": MAX_TURNS,
        "round_limit": ROUND_LIMIT,
        "use_tavily": USE_TAVILY,
        "dump_case_json": True,
        "dump_dir": str(ok_dir),
        "stream_id": stream_id,
        # SSE 비활성화 (CLI 모드)
        "disable_sse": True,
    }

    print(f"\n[Attempt {attempt}] 시뮬레이션 시작...")

    def _work():
        with SessionLocal() as db:
            return run_orchestrated(db, payload)

    try:
        # 1. 시뮬레이션 실행
        sim_result = await asyncio.to_thread(_work)

        if not isinstance(sim_result, dict):
            raise ValueError(f"시뮬레이션 결과가 dict가 아님: {type(sim_result)}")

        case_id = sim_result.get("case_id", stream_id)
        print(f"[Attempt {attempt}] 시뮬레이션 완료: case_id={case_id}")

        # 2. 데이터 추출
        extracted = extract_simulation_data(sim_result)
        print(f"[Attempt {attempt}] 데이터 추출: rounds={extracted['rounds']}, turns={len(extracted['turns'])}")

        # 3. VP-Web-Search에 전송
        websearch_result = send_to_websearch(
            case_id=extracted["case_id"],
            round_no=extracted["rounds"],
            turns=extracted["turns"],
            judgement=extracted["last_judgement"],
            scenario=extracted["scenario"],
            victim_profile=extracted["victim_profile"],
            auto_analyze=AUTO_ANALYZE,
        )

        # 4. 통합 결과 저장
        combined_result = {
            "case_id": extracted["case_id"],
            "timestamp": datetime.now().isoformat(),
            "simulation": {
                "rounds": extracted["rounds"],
                "turns_count": len(extracted["turns"]),
                "turns": extracted["turns"],
                "judgements": extracted["judgements"],
                "last_judgement": extracted["last_judgement"],
                "scenario": extracted["scenario"],
                "victim_profile": extracted["victim_profile"],
            },
            "websearch": websearch_result,
            "config": {
                "offender_id": OFFENDER_ID,
                "victim_id": VICTIM_ID,
                "max_turns": MAX_TURNS,
                "round_limit": ROUND_LIMIT,
            },
        }

        artifact_path = ok_dir / f"case_{_ts()}_{case_id[:8]}.json"
        _write_json(artifact_path, combined_result)

        print(f"[Attempt {attempt}] 저장 완료: {artifact_path}")

        return {
            "success": True,
            "case_id": case_id,
            "simulation_result": sim_result,
            "websearch_result": websearch_result,
            "artifact_path": str(artifact_path),
        }

    except Exception as e:
        # 실패 기록
        err_path = fail_dir / f"error_{_ts()}_{stream_id[:8]}.json"
        _write_json(err_path, {
            "ok": False,
            "error": str(e),
            "payload": payload,
            "traceback": traceback.format_exc(),
        })
        print(f"[Attempt {attempt}] 실패: {e}")
        print(f"[Attempt {attempt}] 에러 저장: {err_path}")

        return {
            "success": False,
            "error": str(e),
            "error_path": str(err_path),
        }


async def main():
    print("=" * 60)
    print("VP2 시뮬레이션 + VP-Web-Search 통합 스크립트")
    print("=" * 60)

    # 디렉토리 설정
    dump_dir = os.getenv("VP_CASE_DUMP_DIR", DUMP_DIR)
    root = Path(dump_dir)
    ok_dir = root / "ok"
    fail_dir = root / "failed"
    ok_dir.mkdir(parents=True, exist_ok=True)
    fail_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[Config]")
    print(f"  - OFFENDER_ID: {OFFENDER_ID}")
    print(f"  - VICTIM_ID: {VICTIM_ID}")
    print(f"  - MAX_TURNS: {MAX_TURNS}")
    print(f"  - ROUND_LIMIT: {ROUND_LIMIT}")
    print(f"  - TARGET_JSON: {TARGET_JSON}")
    print(f"  - MAX_ATTEMPTS: {MAX_ATTEMPTS}")
    print(f"  - WEBSEARCH_URL: {WEBSEARCH_BASE_URL}")
    print(f"  - DUMP_DIR: {dump_dir}")

    # VP-Web-Search 연결 확인
    print(f"\n[WebSearch] 연결 확인 중...")
    if not check_websearch_health():
        print("[ERROR] VP-Web-Search 시스템에 연결할 수 없습니다!")
        print(f"        URL: {WEBSEARCH_BASE_URL}")
        print("        VP-Web-Search 서버를 먼저 실행해주세요.")
        sys.exit(1)

    # 실행
    success = 0
    attempts = 0
    results = []

    print(f"\n[Start] 시뮬레이션 시작...")

    while success < TARGET_JSON and attempts < MAX_ATTEMPTS:
        attempts += 1

        result = await run_single_case(ok_dir, fail_dir, attempts)
        results.append(result)

        if result["success"]:
            success += 1
            print(f"[Progress] {success}/{TARGET_JSON} 완료")

        if SLEEP_SEC and attempts < MAX_ATTEMPTS:
            print(f"[Wait] {SLEEP_SEC}초 대기...")
            time.sleep(SLEEP_SEC)

    # 최종 결과
    print("\n" + "=" * 60)
    print("=== 완료 ===")
    print("=" * 60)
    print(f"성공: {success}/{TARGET_JSON}")
    print(f"시도: {attempts}/{MAX_ATTEMPTS}")
    print(f"성공 폴더: {ok_dir}")
    print(f"실패 폴더: {fail_dir}")

    # 요약 저장
    summary_path = root / f"summary_{_ts()}.json"
    _write_json(summary_path, {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "offender_id": OFFENDER_ID,
            "victim_id": VICTIM_ID,
            "max_turns": MAX_TURNS,
            "round_limit": ROUND_LIMIT,
            "websearch_url": WEBSEARCH_BASE_URL,
        },
        "stats": {
            "success": success,
            "attempts": attempts,
            "target": TARGET_JSON,
        },
        "results": results,
    })
    print(f"요약 저장: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
