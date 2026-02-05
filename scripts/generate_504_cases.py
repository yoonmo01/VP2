# scripts/generate_504_cases.py
"""
504개 케이스 생성 스크립트

요구사항:
- 총 504개 케이스 생성 (6명 피해자 × 84개 케이스 = 504개)
- 각 케이스 JSON 포함 내용:
  - 피해자 정보 (victim_profile)
  - 모든 라운드 대화 (turns)
  - 각 대화의 감정 라벨링 (emotion labels)
  - 각 라운드 판정 (judgements)
  - 각 라운드 지침 (guidances)
  - 지침마다 웹서치 시스템 사용 유무 (is_websearch)
- 피해자별로 84개 케이스씩 별도 폴더에 저장
- 모든 케이스 완료될 때까지 반복

피해자 ID (seed): 8, 9, 10, 11, 12, 13
시나리오(offender) ID (seed): 1~8
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# .env 로드
_ROOT = Path(__file__).resolve().parents[1]
env1 = _ROOT / ".env"
env2 = _ROOT / "app" / ".env"

load_dotenv(env1, override=False)
load_dotenv(env2, override=False)

from app.db.session import SessionLocal
from app.services.agent.orchestrator_react import run_orchestrated, _ensure_stream

# =========================
# 설정
# =========================
# 피해자 ID 목록 (seed에서 확인된 값)
VICTIM_IDS = [9, 10, 11, 12, 13, 14]

# 시나리오(offender) ID 목록 (seed에서 확인된 값)
OFFENDER_IDS = [4]

# 피해자당 케이스 수
CASES_PER_VICTIM = 84

# 총 케이스 수
TOTAL_CASES = len(VICTIM_IDS) * CASES_PER_VICTIM  # 6 * 84 = 504

# 시뮬레이션 설정
MAX_TURNS = 20           # 한 라운드 최대 턴 수
ROUND_LIMIT = 5          # 최대 라운드 수

# JSON 저장 폴더
DUMP_DIR = str(_ROOT / "scripts" / "case_json_504")

# 시도 간 쉬기(레이트/서버 부하 완화)
SLEEP_SEC = 0.5

# 케이스당 최대 재시도 횟수 (0 = 무한 반복)
MAX_RETRIES_PER_CASE = 1  # 성공할 때까지 무한 반복

# 연속 실패 시 대기 시간 증가
RETRY_BACKOFF_SEC = 2.0
# =========================


@dataclass
class CaseResult:
    """케이스 실행 결과"""
    victim_id: int
    offender_id: int
    case_index: int
    success: bool
    case_id: Optional[str] = None
    artifact_path: Optional[str] = None
    error: Optional[str] = None
    rounds: int = 0
    turns_count: int = 0
    websearch_used: bool = False


@dataclass
class VictimProgress:
    """피해자별 진행 상황"""
    victim_id: int
    total: int = CASES_PER_VICTIM
    completed: int = 0
    failed: int = 0
    case_results: List[CaseResult] = field(default_factory=list)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_case_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    orchestrator_react 결과에서 필요한 데이터 추출
    """
    case_id = result.get("case_id", "")
    rounds = result.get("rounds", 1)

    # turns 추출
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

    # guidances 추출
    guidances = []
    if "guidances" in result:
        guidances = result["guidances"]
    elif "all_guidances" in result:
        guidances = result["all_guidances"]
    elif "artifact" in result and isinstance(result["artifact"], dict):
        guidances = result["artifact"].get("guidances", [])

    # 웹서치 사용 여부 확인
    websearch_used = any(
        g.get("is_websearch", False) for g in guidances if isinstance(g, dict)
    )

    # 시나리오/피해자 프로필
    scenario = result.get("scenario", {})
    victim_profile = result.get("victim_profile", {})

    return {
        "case_id": str(case_id),
        "rounds": rounds,
        "turns": turns,
        "judgements": judgements,
        "guidances": guidances,
        "scenario": scenario,
        "victim_profile": victim_profile,
        "websearch_used": websearch_used,
    }


async def run_single_case(
    victim_id: int,
    offender_id: int,
    case_index: int,
    ok_dir: Path,
    fail_dir: Path,
) -> CaseResult:
    """
    단일 케이스 실행
    """
    stream_id = str(uuid.uuid4())
    _ensure_stream(stream_id)

    payload = {
        "offender_id": offender_id,
        "victim_id": victim_id,
        "max_turns": MAX_TURNS,
        "round_limit": ROUND_LIMIT,
        "dump_case_json": True,
        "dump_dir": str(ok_dir),
        "stream_id": stream_id,
        "disable_sse": True,
    }

    def _work():
        with SessionLocal() as db:
            return run_orchestrated(db, payload)

    try:
        # 시뮬레이션 실행
        sim_result = await asyncio.to_thread(_work)

        if not isinstance(sim_result, dict):
            raise ValueError(f"시뮬레이션 결과가 dict가 아님: {type(sim_result)}")

        case_id = sim_result.get("case_id", stream_id)

        # 데이터 추출
        extracted = extract_case_data(sim_result)

        # 케이스 JSON 구성
        case_data = {
            "case_id": extracted["case_id"],
            "timestamp": datetime.now().isoformat(),
            "config": {
                "victim_id": victim_id,
                "offender_id": offender_id,
                "case_index": case_index,
                "max_turns": MAX_TURNS,
                "round_limit": ROUND_LIMIT,
            },
            "victim_profile": extracted["victim_profile"],
            "scenario": extracted["scenario"],
            "rounds": extracted["rounds"],
            "turns": extracted["turns"],
            "judgements": extracted["judgements"],
            "guidances": extracted["guidances"],
            "websearch_used": extracted["websearch_used"],
            "summary": {
                "total_turns": len(extracted["turns"]),
                "total_rounds": extracted["rounds"],
                "total_judgements": len(extracted["judgements"]),
                "total_guidances": len(extracted["guidances"]),
                "websearch_rounds": sum(
                    1 for g in extracted["guidances"]
                    if isinstance(g, dict) and g.get("is_websearch", False)
                ),
            },
        }

        # 저장
        filename = f"victim{victim_id}_case{case_index:03d}_{case_id[:8]}.json"
        artifact_path = ok_dir / filename
        _write_json(artifact_path, case_data)

        return CaseResult(
            victim_id=victim_id,
            offender_id=offender_id,
            case_index=case_index,
            success=True,
            case_id=case_id,
            artifact_path=str(artifact_path),
            rounds=extracted["rounds"],
            turns_count=len(extracted["turns"]),
            websearch_used=extracted["websearch_used"],
        )

    except Exception as e:
        # 실패 기록
        err_path = fail_dir / f"error_victim{victim_id}_case{case_index}_{_ts()}.json"
        _write_json(err_path, {
            "ok": False,
            "victim_id": victim_id,
            "offender_id": offender_id,
            "case_index": case_index,
            "error": str(e),
            "payload": payload,
            "traceback": traceback.format_exc(),
        })

        return CaseResult(
            victim_id=victim_id,
            offender_id=offender_id,
            case_index=case_index,
            success=False,
            error=str(e),
        )


def get_completed_cases(victim_dir: Path) -> set:
    """이미 완료된 케이스 인덱스 조회"""
    completed = set()
    if victim_dir.exists():
        for f in victim_dir.glob("victim*_case*.json"):
            # victim8_case001_abc12345.json 형식에서 case 번호 추출
            name = f.stem
            parts = name.split("_")
            for p in parts:
                if p.startswith("case"):
                    try:
                        idx = int(p[4:7])  # case001 -> 1
                        completed.add(idx)
                    except ValueError:
                        pass
    return completed


async def run_victim_cases(victim_id: int, root_dir: Path, progress_callback=None) -> VictimProgress:
    victim_dir = root_dir / f"victim_{victim_id}"
    ok_dir = victim_dir / "ok"
    fail_dir = victim_dir / "failed"
    ok_dir.mkdir(parents=True, exist_ok=True)
    fail_dir.mkdir(parents=True, exist_ok=True)

    progress = VictimProgress(victim_id=victim_id)

    # 이미 성공 저장된 케이스 번호(성공 케이스만 카운트)
    completed_indices = get_completed_cases(ok_dir)
    progress.completed = len(completed_indices)

    print(f"\n[Victim {victim_id}] 시작 - 성공: {progress.completed}/{CASES_PER_VICTIM}")

    offender_cycle = 0

    # ✅ “성공 개수”가 84개가 될 때까지 계속 생성
    attempt_no = 0
    while progress.completed < CASES_PER_VICTIM:
        attempt_no += 1

        # 다음 성공 케이스 번호를 채워넣기 (1..84 중 비어있는 번호)
        # ex) 중간이 비었으면 그 번호부터 채우고 싶으면 이렇게:
        for target_case_idx in range(1, CASES_PER_VICTIM + 1):
            if target_case_idx not in completed_indices:
                case_idx = target_case_idx
                break

        offender_id = OFFENDER_IDS[offender_cycle % len(OFFENDER_IDS)]
        offender_cycle += 1

        print(f"  [Make Success Case {case_idx:03d}] offender={offender_id}, attempt={attempt_no}")

        # ✅ “한 번만 시도” 규칙: retry 루프 제거
        result = await run_single_case(
            victim_id=victim_id,
            offender_id=offender_id,
            case_index=case_idx,
            ok_dir=ok_dir,
            fail_dir=fail_dir,
        )

        progress.case_results.append(result)

        if result.success:
            progress.completed += 1
            completed_indices.add(case_idx)
            print(f"  [Case {case_idx:03d}] 성공! rounds={result.rounds}, turns={result.turns_count}, websearch={result.websearch_used}")
        else:
            progress.failed += 1
            print(f"  [Case {case_idx:03d}] 실패(1회 시도 후 스킵): {result.error}")

        if progress_callback:
            progress_callback(victim_id, progress)

        if SLEEP_SEC:
            await asyncio.sleep(SLEEP_SEC)

    return progress


async def main():
    print("=" * 70)
    print("504개 케이스 생성 스크립트")
    print("=" * 70)

    root_dir = Path(DUMP_DIR)
    root_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[설정]")
    print(f"  - 피해자 ID: {VICTIM_IDS}")
    print(f"  - 시나리오 ID: {OFFENDER_IDS}")
    print(f"  - 피해자당 케이스: {CASES_PER_VICTIM}")
    print(f"  - 총 케이스: {TOTAL_CASES}")
    print(f"  - 저장 경로: {root_dir}")
    print(f"  - MAX_TURNS: {MAX_TURNS}")
    print(f"  - ROUND_LIMIT: {ROUND_LIMIT}")

    all_progress: Dict[int, VictimProgress] = {}

    def print_overall_progress(victim_id: int, progress: VictimProgress):
        all_progress[victim_id] = progress
        total_completed = sum(p.completed for p in all_progress.values())
        total_failed = sum(p.failed for p in all_progress.values())
        print(f"\n>>> 전체 진행: {total_completed}/{TOTAL_CASES} (실패: {total_failed})")

    # 모든 피해자에 대해 순차 실행
    for victim_id in VICTIM_IDS:
        print(f"\n{'='*50}")
        print(f"[Victim {victim_id}] 케이스 생성 시작")
        print(f"{'='*50}")

        progress = await run_victim_cases(
            victim_id=victim_id,
            root_dir=root_dir,
            progress_callback=print_overall_progress,
        )

        all_progress[victim_id] = progress

        # 피해자별 요약 저장
        victim_summary_path = root_dir / f"victim_{victim_id}" / f"summary_{_ts()}.json"
        _write_json(victim_summary_path, {
            "victim_id": victim_id,
            "timestamp": datetime.now().isoformat(),
            "total": progress.total,
            "completed": progress.completed,
            "failed": progress.failed,
            "success_rate": f"{progress.completed / progress.total * 100:.1f}%",
        })

    # 전체 요약
    print("\n" + "=" * 70)
    print("=== 전체 완료 ===")
    print("=" * 70)

    total_completed = sum(p.completed for p in all_progress.values())
    total_failed = sum(p.failed for p in all_progress.values())

    print(f"\n[결과]")
    for victim_id, progress in all_progress.items():
        print(f"  - Victim {victim_id}: {progress.completed}/{progress.total} (실패: {progress.failed})")

    print(f"\n[전체]")
    print(f"  - 완료: {total_completed}/{TOTAL_CASES}")
    print(f"  - 실패: {total_failed}")
    print(f"  - 저장 경로: {root_dir}")

    # 전체 요약 저장
    overall_summary_path = root_dir / f"overall_summary_{_ts()}.json"
    _write_json(overall_summary_path, {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "victim_ids": VICTIM_IDS,
            "offender_ids": OFFENDER_IDS,
            "cases_per_victim": CASES_PER_VICTIM,
            "total_cases": TOTAL_CASES,
            "max_turns": MAX_TURNS,
            "round_limit": ROUND_LIMIT,
        },
        "results": {
            "total_completed": total_completed,
            "total_failed": total_failed,
            "by_victim": {
                str(vid): {
                    "completed": p.completed,
                    "failed": p.failed,
                }
                for vid, p in all_progress.items()
            },
        },
    })
    print(f"\n요약 저장: {overall_summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
