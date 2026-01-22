# extract_pair_datasets.py
# ✅ 실행: python extract_pair_datasets.py
#
# 입력:
# - INPUT_PATH가 파일이면: 해당 파일 1개 처리
# - INPUT_PATH가 폴더면: 하위 *.json 전부 처리
#
# 출력(각 입력 파일 1개당 1:1 생성):
#   (1) victim_only_[caseId].jsonl
#   (2) victim_offender_pair_[caseId].jsonl
#   (3) victim_thoughts_pair_[caseId].jsonl
#   (4) victim_offender_thoughts_[caseId].jsonl
#
# caseId 규칙:
# - 기본: 파일명(stem) 사용
# - fallback: JSON 내부 case_id

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# =========================
# 🔧 여기만 수정하면 됨
# =========================
INPUT_PATH = r"C:\LIT_VP2\VP\scripts\case_json_0122\ok"   # 파일 또는 폴더
OUTPUT_DIR = r"C:\LIT_VP2\VP\scripts\datasets_0122"       # 출력 폴더

REQUIRE_PREV_OFFENDER = True        # True면 직전 offender 없으면 (2)(4) 샘플 스킵
REQUIRE_THOUGHTS = True             # True면 thoughts 없으면 (3)(4) 샘플 스킵
THOUGHTS_FALLBACK_TO_TEXT = False   # thoughts 없으면 victim text로 대체(권장X)

# (4)에서 victim+prev_offender+thoughts를 한 문자열에 어떻게 합칠지
# - 모델 입력이 text/text_pair만 받는 구조라면, "text_pair"에 합쳐 넣는 식이 편함
# - 여기서는 text_pair에 "prev_offender + '\n' + thoughts"로 합침
COMBINE_SEPARATOR = "\n"            # offender와 thoughts 사이 구분자


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
    stem = case_file.stem.strip()
    if stem:
        return stem
    cid = case.get("case_id")
    return str(cid) if cid else "unknown_case"


def extract_four_versions(
    case: Dict[str, Any],
    source_file: str,
    require_prev_offender: bool = True,
    require_thoughts: bool = True,
    thoughts_fallback_to_text: bool = False,
) -> Tuple[
    List[Dict[str, Any]],  # rows_victim_only
    List[Dict[str, Any]],  # rows_pair (victim+prev_offender)
    List[Dict[str, Any]],  # rows_thoughts (victim+thoughts)
    List[Dict[str, Any]],  # rows_all (victim+prev_offender+thoughts)
]:
    """
    Returns:
      (1) victim only: victim(text)
      (2) victim + prev offender: victim(text) + prev offender(text_pair)
      (3) victim + thoughts: victim(text) + thoughts(text_pair)
      (4) victim + prev offender + thoughts:
          victim(text) + combined(text_pair = prev_offender + sep + thoughts)
          (원하면 구조를 바꿔서 별도 필드로 저장해도 됨)
    """
    case_id = case.get("case_id")
    timestamp = case.get("timestamp")

    rows_victim_only: List[Dict[str, Any]] = []
    rows_pair: List[Dict[str, Any]] = []
    rows_thoughts: List[Dict[str, Any]] = []
    rows_all: List[Dict[str, Any]] = []

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

            if not text:
                continue

            # 공통 메타
            base_meta = {
                "case_id": case_id,
                "timestamp": timestamp,
                "source_file": source_file,
                "run_no": run_no,
                "turn_index": i,
                "is_convinced": t.get("is_convinced"),
                "victim_gender": t.get("gender"),
                "victim_age_group": t.get("age_group"),
            }

            # ---------- (1) victim only ----------
            rows_victim_only.append({
                "id": f"{case_id}_run{run_no}_turn{i}_victim_only",
                "mode": "victim_only",
                "text": text,
                "text_pair": None,
                **base_meta,
            })

            # ---------- thoughts 준비 ----------
            thoughts = normalize_thoughts(t.get("thoughts"))
            if thoughts is None and thoughts_fallback_to_text:
                thoughts = text

            # ---------- (2) victim + prev offender ----------
            if prev_offender_text:
                rows_pair.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_pair",
                    "mode": "victim+prev_offender",
                    "text": text,
                    "text_pair": prev_offender_text,
                    **base_meta,
                })
            elif not require_prev_offender:
                rows_pair.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_pair",
                    "mode": "victim+prev_offender",
                    "text": text,
                    "text_pair": None,
                    **base_meta,
                })

            # ---------- (3) victim + thoughts ----------
            if thoughts:
                rows_thoughts.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_thoughts",
                    "mode": "victim+thoughts",
                    "text": text,
                    "text_pair": thoughts,
                    **base_meta,
                })
            elif not require_thoughts:
                rows_thoughts.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_thoughts",
                    "mode": "victim+thoughts",
                    "text": text,
                    "text_pair": None,
                    **base_meta,
                })

            # ---------- (4) victim + prev offender + thoughts ----------
            # 정책:
            # - prev_offender_text와 thoughts 둘 다 있으면 생성
            # - require_* 옵션에 따라 하나가 없어도 생성할지 결정
            has_prev = bool(prev_offender_text)
            has_th = bool(thoughts)

            if has_prev and has_th:
                combined_pair = f"{prev_offender_text}{COMBINE_SEPARATOR}{thoughts}"
                rows_all.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_all",
                    "mode": "victim+prev_offender+thoughts",
                    "text": text,
                    "text_pair": combined_pair,
                    "prev_offender_text": prev_offender_text,  # 분석용(선택)
                    "thoughts": thoughts,                      # 분석용(선택)
                    **base_meta,
                })
            else:
                # 둘 중 하나라도 없으면, 옵션(require_*)에 따라 스킵/생성 결정
                if require_prev_offender and not has_prev:
                    continue
                if require_thoughts and not has_th:
                    continue

                # 여기까지 왔다는 건 "부족해도 생성" 허용 케이스
                parts: List[str] = []
                if prev_offender_text:
                    parts.append(prev_offender_text)
                if thoughts:
                    parts.append(thoughts)
                combined_pair = COMBINE_SEPARATOR.join(parts) if parts else None

                rows_all.append({
                    "id": f"{case_id}_run{run_no}_turn{i}_all",
                    "mode": "victim+prev_offender+thoughts",
                    "text": text,
                    "text_pair": combined_pair,
                    "prev_offender_text": prev_offender_text,
                    "thoughts": thoughts,
                    **base_meta,
                })

    return rows_victim_only, rows_pair, rows_thoughts, rows_all


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
    total_victim_only = 0
    total_pair_rows = 0
    total_thought_rows = 0
    total_all_rows = 0

    for case_file in iter_case_files(input_path):
        file_count += 1

        try:
            case = load_json(case_file)
        except Exception as e:
            print(f"[SKIP] failed to read {case_file}: {e}")
            continue

        case_id_for_name = get_case_id_for_filename(case, case_file)

        out_victim_only = out_dir / f"victim_only_{case_id_for_name}.jsonl"
        out_pair = out_dir / f"victim_offender_pair_{case_id_for_name}.jsonl"
        out_thoughts = out_dir / f"victim_thoughts_pair_{case_id_for_name}.jsonl"
        out_all = out_dir / f"victim_offender_thoughts_{case_id_for_name}.jsonl"

        rows_victim_only, rows_pair, rows_thoughts, rows_all = extract_four_versions(
            case,
            source_file=str(case_file),
            require_prev_offender=REQUIRE_PREV_OFFENDER,
            require_thoughts=REQUIRE_THOUGHTS,
            thoughts_fallback_to_text=THOUGHTS_FALLBACK_TO_TEXT,
        )

        write_jsonl(rows_victim_only, out_victim_only)
        write_jsonl(rows_pair, out_pair)
        write_jsonl(rows_thoughts, out_thoughts)
        write_jsonl(rows_all, out_all)

        total_victim_only += len(rows_victim_only)
        total_pair_rows += len(rows_pair)
        total_thought_rows += len(rows_thoughts)
        total_all_rows += len(rows_all)

        print(f"[OK] {case_file.name}")
        print(f"     -> {out_victim_only.name} ({len(rows_victim_only)} rows)")
        print(f"     -> {out_pair.name} ({len(rows_pair)} rows)")
        print(f"     -> {out_thoughts.name} ({len(rows_thoughts)} rows)")
        print(f"     -> {out_all.name} ({len(rows_all)} rows)")

    print("\n=== done ===")
    print(f"  input_files: {file_count}")
    print(f"  total victim_only rows:             {total_victim_only}")
    print(f"  total victim+prev_offender rows:    {total_pair_rows}")
    print(f"  total victim+thoughts rows:         {total_thought_rows}")
    print(f"  total victim+offender+thoughts rows:{total_all_rows}")
    print(f"  out_dir: {out_dir}")


if __name__ == "__main__":
    main()
