from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Dict, List, Optional


# Webhook 수신 리포트 메모리 저장소
_received_reports: Dict[str, Dict[str, Any]] = {}


def save_received_report(analysis_id: str, report: Dict[str, Any]) -> None:
    """analysis_id 기준으로 수신 리포트를 저장/갱신한다."""
    _received_reports[analysis_id] = report


def get_received_report(analysis_id: str) -> Optional[Dict[str, Any]]:
    """analysis_id 기준 리포트를 조회한다."""
    return _received_reports.get(analysis_id)


def list_received_reports(limit: int = 50) -> List[Dict[str, Any]]:
    """최근 수신 리포트 목록을 조회한다."""
    return list(_received_reports.values())[-max(1, int(limit)) :]


def get_reports_by_case(case_id: str) -> List[Dict[str, Any]]:
    """case_id 기준 리포트 목록을 조회한다."""
    return [v for v in _received_reports.values() if v.get("case_id") == case_id]


def get_latest_report_by_case(case_id: str) -> Optional[Dict[str, Any]]:
    """case_id 기준 최신 리포트 1건을 조회한다."""
    results = get_reports_by_case(case_id)
    if not results:
        return None

    def _sort_key(item: Dict[str, Any]) -> str:
        # ISO timestamp 문자열 가정, 없으면 최소값 취급
        analyzed_at = item.get("analyzed_at")
        if not analyzed_at:
            return datetime.min.isoformat()
        return str(analyzed_at)

    results.sort(key=_sort_key, reverse=True)
    return results[0]


def get_techniques_by_case(case_id: str) -> List[Dict[str, Any]]:
    """case_id 기준 최신 리포트의 techniques 목록을 조회한다."""
    report = get_latest_report_by_case(case_id)
    if not report:
        return []
    return report.get("techniques", [])



def wait_for_new_report_by_case(
    case_id: str,
    *,
    previous_analysis_id: Optional[str] = None,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.25,
) -> Optional[Dict[str, Any]]:
    """
    case_id 기준으로 새로운 리포트가 수신될 때까지 짧게 대기한다.

    - previous_analysis_id가 주어지면, 해당 ID와 다른 최신 리포트를 새 리포트로 판단
    - timeout 내 미수신 시 None 반환
    """
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    prev_id = str(previous_analysis_id) if previous_analysis_id else None

    while time.monotonic() < deadline:
        latest = get_latest_report_by_case(case_id)
        if latest:
            current_id = str(latest.get("analysis_id") or "")
            if (not prev_id) or (current_id and current_id != prev_id):
                return latest
        time.sleep(max(0.05, float(poll_interval_s)))

    return None
