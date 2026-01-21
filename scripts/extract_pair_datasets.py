# extract_pair_datasets.py
# ✅ 실행: python extract_pair_datasets.py
#
# 입력:
# - INPUT_PATH가 파일이면: 해당 파일 1개 처리
# - INPUT_PATH가 폴더면: 하위 *.json 전부 처리
#
# 출력(각 입력 파일 1개당 1:1 생성):
#   victim_offender_pair_[caseId].jsonl
#   victim_thoughts_pair_[caseId].jsonl
#
# caseId 규칙:
# - 기본: 파일명(stem) 사용
#   예) 574e343e-3d22-46df-b740-17ae96c9d695.json -> caseId = 574e343e-3d22-46df-b740-17ae96c9d695
# - 만약 파일명이 비어있거나 이상하면 JSON 내부 case_id로 fallback

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# =========================
# 🔧 여기만 수정하면 됨
# =========================
INPUT_PATH = r"C:\LIT_VP2\VP\scripts\case_json\ok"   # 파일 또는 폴더
OUTPUT_DIR = r"C:\LIT_VP2\VP\scripts\datasets"       # 출력 폴더

REQUIRE_PREV_OFFENDER = True        # True면 직전 offender 없으면 victim+offender 샘플 스킵
REQUIRE_THOUGHTS = True             # True면 thoughts 없으면 victim+thoughts 샘플 스킵
THOUGHTS_FALLBACK_TO_TEXT = False   # thoughts 없으면 victim text로 대체(권장X)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_case_files(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        yield input_path
        return
    for p in input_path.rglob("*.json"):
        if p.is_file():
            yield p


def normalize_thoughts(th: Optional[str]) -> Optional[str]:
    if not th:
        return None
    s = str(th).strip()
    if not s:
        return None
    return s


def get_case_id_for_filename(case: Dict[str, Any], case_file: Path) -> str:
    """
    출력 파일명에 붙일 caseId 결정
    1) 파일명 stem 사용 (UUID.json 같은 경우 여기서 끝)
    2) fallback: JSON 내부 case_id
    """
    stem = case_file.stem.strip()
    if stem:
        return stem
    cid = case.get("case_id")
    return str(cid) if cid else "unknown_case"


def extract_two_versions(
    case: Dict[str, Any],
    source_file: str,
    require_prev_offender: bool = True,
    require_thoughts: bool = True,
    thoughts_fallback_to_text: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns:
      - rows_pair: victim(text) + prev offender(text_pair)
      - rows_thoughts: victim(text) + victim thoughts(text_pair)
    """
    case_id = case.get("case_id")
    timestamp = case.get("timestamp")

    rows_pair: List[Dict[str, Any]] = []
    rows_thoughts: List[Dict[str, Any]] = []

    rounds = case.get("rounds", [])
    for r in rounds:
        run_no = r.get("run_no")
        turns = r.get("turns", [])

        prev_offender_text: Optional[str] = None

        for i, t in enumerate(turns):
            role = t.get("role")
            text = (t.get("text") or "").strip()

            if role == "offender":
                if text:
                    prev_offender_text = text
                continue

            if role != "victim":
                continue

            # ---------- (1) victim + prev offender ----------
            if prev_offender_text and text:
                rows_pair.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_pair",
                    "case_id": case_id,
                    "timestamp": timestamp,
                    "source_file": source_file,
                    "run_no": run_no,
                    "turn_index": i,
                    "mode": "victim+prev_offender",
                    "text": text,                    # victim
                    "text_pair": prev_offender_text,  # offender (prev)
                    "is_convinced": t.get("is_convinced"),
                    "victim_gender": t.get("gender"),
                    "victim_age_group": t.get("age_group"),
                })
            elif (not require_prev_offender) and text:
                rows_pair.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_pair",
                    "case_id": case_id,
                    "timestamp": timestamp,
                    "source_file": source_file,
                    "run_no": run_no,
                    "turn_index": i,
                    "mode": "victim+prev_offender",
                    "text": text,
                    "text_pair": None,
                    "is_convinced": t.get("is_convinced"),
                    "victim_gender": t.get("gender"),
                    "victim_age_group": t.get("age_group"),
                })

            # ---------- (2) victim + thoughts ----------
            thoughts = normalize_thoughts(t.get("thoughts"))
            if thoughts is None and thoughts_fallback_to_text:
                thoughts = text if text else None

            if thoughts and text:
                rows_thoughts.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_thoughts",
                    "case_id": case_id,
                    "timestamp": timestamp,
                    "source_file": source_file,
                    "run_no": run_no,
                    "turn_index": i,
                    "mode": "victim+thoughts",
                    "text": text,          # victim
                    "text_pair": thoughts, # victim thoughts
                    "is_convinced": t.get("is_convinced"),
                    "victim_gender": t.get("gender"),
                    "victim_age_group": t.get("age_group"),
                })
            elif (not require_thoughts) and text:
                rows_thoughts.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_thoughts",
                    "case_id": case_id,
                    "timestamp": timestamp,
                    "source_file": source_file,
                    "run_no": run_no,
                    "turn_index": i,
                    "mode": "victim+thoughts",
                    "text": text,
                    "text_pair": None,
                    "is_convinced": t.get("is_convinced"),
                    "victim_gender": t.get("gender"),
                    "victim_age_group": t.get("age_group"),
                })

    return rows_pair, rows_thoughts


def write_jsonl(rows: List[Dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    input_path = Path(INPUT_PATH)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_count = 0
    total_pair_rows = 0
    total_thought_rows = 0

    for case_file in iter_case_files(input_path):
        file_count += 1

        try:
            case = load_json(case_file)
        except Exception as e:
            print(f"[SKIP] failed to read {case_file}: {e}")
            continue

        case_id_for_name = get_case_id_for_filename(case, case_file)

        # ✅ 요청한 파일명 포맷
        out_pair = out_dir / f"victim_offender_pair_{case_id_for_name}.jsonl"
        out_thoughts = out_dir / f"victim_thoughts_pair_{case_id_for_name}.jsonl"

        rows_pair, rows_thoughts = extract_two_versions(
            case,
            source_file=str(case_file),
            require_prev_offender=REQUIRE_PREV_OFFENDER,
            require_thoughts=REQUIRE_THOUGHTS,
            thoughts_fallback_to_text=THOUGHTS_FALLBACK_TO_TEXT,
        )

        write_jsonl(rows_pair, out_pair)
        write_jsonl(rows_thoughts, out_thoughts)

        total_pair_rows += len(rows_pair)
        total_thought_rows += len(rows_thoughts)

        print(f"[OK] {case_file.name}")
        print(f"     -> {out_pair.name} ({len(rows_pair)} rows)")
        print(f"     -> {out_thoughts.name} ({len(rows_thoughts)} rows)")

    print("\n=== done ===")
    print(f"  input_files: {file_count}")
    print(f"  total victim+prev_offender rows: {total_pair_rows}")
    print(f"  total victim+thoughts rows:      {total_thought_rows}")
    print(f"  out_dir: {out_dir}")


if __name__ == "__main__":
    main()
