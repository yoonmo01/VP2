# scripts/generate_504_cases.py
"""
504개 케이스 생성 스크립트

요구사항:
- 총 504개 케이스 생성 (6명 피해자 × 84개 케이스 = 504개)
- 각 케이스 JSON 포함 내용(최종 저장 파일 기준, 가능한 한 "통째로"):
  - 피해자 정보 (victim_profile)
  - 모든 라운드 대화 (turns/rounds[*].turns)
  - 각 대화의 감정 라벨링 (emotion labels, hmm_summary 등)
  - 각 라운드 판정 (judgements/round_judgements 등)
  - 각 라운드 지침 (guidances)
  - 지침마다 웹서치 사용 여부 (is_websearch)
  - search-agent가 만든 결과/메타데이터(가능한 한 통째로: meta, used_tools, traces 등)
- dump_case_json=True로 orchestrator가 dump_dir에 저장하는 파일이 있어도,
  리턴(sim_result)과 dump 파일의 포맷/필드가 다를 수 있으므로,
  최종 저장 파일은 dump + sim_result를 병합하여 "최대한 전체"를 보존한다.
"""
from __future__ import annotations

import asyncio
import json
import traceback
import uuid
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
VICTIM_IDS = [9, 10, 11, 12, 13, 14]
#VICTIM_IDS = [8, 9, 10, 11, 12, 13]
OFFENDER_IDS = [4]

CASES_PER_VICTIM = 84
TOTAL_CASES = len(VICTIM_IDS) * CASES_PER_VICTIM  # 6 * 84 = 504

MAX_TURNS = 20
ROUND_LIMIT = 5

DUMP_DIR = str(_ROOT / "scripts" / "case_json_504")

SLEEP_SEC = 0.5
MAX_RETRIES_PER_CASE = 1
RETRY_BACKOFF_SEC = 2.0
# =========================


@dataclass
class CaseResult:
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


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: Any, override: Any) -> Any:
    """
    base에 override를 "깊게" 병합.
    - dict: key 단위로 재귀 병합 (override 우선)
    - list: 기본적으로 override를 우선 채택 (원본 보존이 목적이면 리스트 병합이 위험)
    - 그 외: override 우선
    """
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    if isinstance(override, list):
        return override
    if override is not None:
        return override
    return base


def _find_latest_dumped_case_json(ok_dir: Path, case_id: str, stream_id: str) -> Optional[Path]:
    """
    orchestrator가 dump_dir(ok_dir)에 저장한 원본 JSON 파일을 최대한 정확히 찾는다.
    우선순위:
    1) 파일명에 case_id 포함
    2) 파일명에 stream_id 포함
    3) ok_dir 내 가장 최근 수정 json (fallback, 순차 실행 전제)
    """
    candidates: List[Path] = []

    if case_id:
        candidates.extend([p for p in ok_dir.glob(f"*{case_id}*.json") if p.is_file()])

    if not candidates and stream_id:
        candidates.extend([p for p in ok_dir.glob(f"*{stream_id}*.json") if p.is_file()])

    if not candidates:
        all_json = [p for p in ok_dir.glob("*.json") if p.is_file()]
        if not all_json:
            return None
        all_json.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return all_json[0]

    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]


def _calc_stats(case_obj: Dict[str, Any]) -> Dict[str, Any]:
    # rounds 수
    rounds_done = 0
    if isinstance(case_obj.get("rounds"), list):
        rounds_done = len(case_obj["rounds"])
    else:
        rounds_done = int(case_obj.get("rounds_done") or case_obj.get("rounds") or 1)

    # turns 수
    turns_count = 0
    if isinstance(case_obj.get("rounds"), list):
        for r in case_obj["rounds"]:
            if isinstance(r, dict) and isinstance(r.get("turns"), list):
                turns_count += len(r["turns"])
    elif isinstance(case_obj.get("turns"), list):
        turns_count = len(case_obj["turns"])

    # websearch_used
    websearch_used = False
    guidances = case_obj.get("guidances", [])
    if isinstance(guidances, list):
        websearch_used = any(isinstance(g, dict) and g.get("is_websearch", False) for g in guidances)

    return {"rounds": rounds_done, "turns_count": turns_count, "websearch_used": websearch_used}


async def run_single_case(
    victim_id: int,
    offender_id: int,
    case_index: int,
    ok_dir: Path,
    fail_dir: Path,
) -> CaseResult:
    """
    단일 케이스 실행 (핵심: 최종 저장 파일은 dump + sim_result를 "통째로" 병합)

    목표:
    - 감정 라벨링 붙은 대화로그(rounds/turns 내 emotion/hmm_summary 등)
    - judgement 전체(admin.make_judgement 결과, round_judgements 등)
    - guidance 전체(is_websearch 포함)
    - search-agent 결과/메타(가능한 한 통째로: meta/used_tools/trace 등)
    를 최종 victim*_case*.json에 모두 포함시키기
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
        sim_result = await asyncio.to_thread(_work)

        if not isinstance(sim_result, dict):
            raise ValueError(f"시뮬레이션 결과가 dict가 아님: {type(sim_result)}")

        case_id = str(sim_result.get("case_id") or stream_id)

        # 1) orchestrator가 dump_dir에 저장한 "원본" 파일 찾기
        dumped_path = _find_latest_dumped_case_json(ok_dir=ok_dir, case_id=case_id, stream_id=stream_id)
        dumped_obj: Dict[str, Any] = {}
        if dumped_path and dumped_path.exists():
            try:
                dumped_obj = _read_json(dumped_path)
            except Exception:
                dumped_obj = {}

        # 2) dump + sim_result를 통째로 병합 (override=sim_result 우선)
        #    => dump에만 있던 값도 살리고, sim_result에만 있던 감정/판정/지침/메타도 살림
        merged = _deep_merge(dumped_obj, sim_result)

        # 3) 최종 파일명으로 저장
        filename = f"victim{victim_id}_case{case_index:03d}_{case_id[:8]}.json"
        artifact_path = ok_dir / filename

        # 혹시 같은 이름 있으면 덮어쓰기
        if artifact_path.exists():
            artifact_path.unlink()

        _write_json(artifact_path, merged)

        # 4) dump 원본 파일이 따로 남아있으면 정리(원하면 유지 가능)
        #    단, dumped_path가 artifact_path와 다를 때만 삭제
        if dumped_path and dumped_path.exists() and dumped_path.resolve() != artifact_path.resolve():
            try:
                dumped_path.unlink()
            except Exception:
                pass

        stats = _calc_stats(merged)

        return CaseResult(
            victim_id=victim_id,
            offender_id=offender_id,
            case_index=case_index,
            success=True,
            case_id=case_id,
            artifact_path=str(artifact_path),
            rounds=stats["rounds"],
            turns_count=stats["turns_count"],
            websearch_used=stats["websearch_used"],
        )

    except Exception as e:
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
    completed = set()
    if victim_dir.exists():
        for f in victim_dir.glob("victim*_case*.json"):
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

    completed_indices = get_completed_cases(ok_dir)
    progress.completed = len(completed_indices)

    print(f"\n[Victim {victim_id}] 시작 - 성공: {progress.completed}/{CASES_PER_VICTIM}")

    offender_cycle = 0
    attempt_no = 0

    while progress.completed < CASES_PER_VICTIM:
        attempt_no += 1

        case_idx = None
        for target_case_idx in range(1, CASES_PER_VICTIM + 1):
            if target_case_idx not in completed_indices:
                case_idx = target_case_idx
                break
        if case_idx is None:
            break

        offender_id = OFFENDER_IDS[offender_cycle % len(OFFENDER_IDS)]
        offender_cycle += 1

        print(f"  [Make Success Case {case_idx:03d}] offender={offender_id}, attempt={attempt_no}")

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

        victim_summary_path = root_dir / f"victim_{victim_id}" / f"summary_{_ts()}.json"
        _write_json(victim_summary_path, {
            "victim_id": victim_id,
            "timestamp": datetime.now().isoformat(),
            "total": progress.total,
            "completed": progress.completed,
            "failed": progress.failed,
            "success_rate": f"{progress.completed / progress.total * 100:.1f}%",
        })

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
                str(vid): {"completed": p.completed, "failed": p.failed}
                for vid, p in all_progress.items()
            },
        },
    })
    print(f"\n요약 저장: {overall_summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
