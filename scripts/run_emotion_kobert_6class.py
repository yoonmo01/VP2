# scripts/run_emotion_kobert_6class.py
# ✅ 실행: python scripts/run_emotion_kobert_6class.py
#
# 입력:
# - INPUT_PATH가 파일(.jsonl)이면: 그 파일 1개 처리
# - INPUT_PATH가 폴더면: (스위치에 따라) victim_offender_pair_*.jsonl / victim_thoughts_pair_*.jsonl 처리
#
# 출력(1:1):
# - out 파일명은 "pred_" + 원본 파일명
#   예) victim_offender_pair_<caseId>.jsonl -> pred_victim_offender_pair_<caseId>.jsonl
#   예) victim_thoughts_pair_<caseId>.jsonl -> pred_victim_thoughts_pair_<caseId>.jsonl

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Windows에서 경고 줄이기(선택)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

# =========================
# 🔧 여기만 수정하면 됨
# =========================
INPUT_PATH = r"C:\LIT_VP2\VP\scripts\datasets"   # 파일(.jsonl) 또는 폴더
OUTPUT_DIR = r"C:\LIT_VP2\VP\scripts\emotion_result_kobert"   # 출력 폴더

# ✅ 스위치: 원하는 것만 True로 켜기
RUN_OFFENDER_PAIR = True     # victim_offender_pair_*.jsonl 처리
RUN_THOUGHTS_PAIR = False    # victim_thoughts_pair_*.jsonl 처리

BATCH_SIZE = 16
MAX_LENGTH = 256

MODEL_ID = "jeongyoonhuh/kobert-emotion-6class"
TOKENIZER_ID = "monologg/kobert"

ID2LABEL_6 = {
    0: "JOY",
    1: "SAD",
    2: "ANGER",
    3: "ANXIETY",
    4: "EMBARRASS",
    5: "HURT",
}

MAP_6_TO_4 = {
    "JOY": "E",
    "ANGER": "A",
    "ANXIETY": "F",
    "SAD": "N",
    "EMBARRASS": "N",
    "HURT": "N",
}


def load_lines(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def get_target_globs() -> List[str]:
    """
    스위치에 따라 폴더 입력 시 처리할 파일 패턴 결정
    """
    globs: List[str] = []
    if RUN_OFFENDER_PAIR:
        globs.append("victim_offender_pair_*.jsonl")
    if RUN_THOUGHTS_PAIR:
        globs.append("victim_thoughts_pair_*.jsonl")
    return globs


def iter_input_files(input_path: Path) -> Iterable[Path]:
    """
    - 파일이면 그 파일 1개
    - 폴더면 스위치에 따라 타겟 패턴 파일들을 재귀적으로 전부 반환
    """
    if input_path.is_file():
        yield input_path
        return

    if not input_path.exists():
        return

    for pat in get_target_globs():
        for p in input_path.rglob(pat):
            if p.is_file():
                yield p


def output_path_for_input(in_file: Path, out_dir: Path) -> Path:
    """
    출력 파일명: pred_ + 원본 파일명
    """
    return out_dir / f"pred_{in_file.name}"


def predict_one(
    model,
    tokenizer,
    device,
    text: str,
    text_pair: Optional[str],
    max_length: int,
) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"_skip": True}

    if text_pair is not None:
        text_pair = str(text_pair).strip()
        if not text_pair:
            text_pair = None

    if text_pair is None:
        enc = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
    else:
        enc = tokenizer(
            text,
            text_pair=text_pair,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )

    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**enc).logits[0]
        probs = torch.softmax(logits, dim=-1).detach().cpu().tolist()
        pred_id = int(torch.argmax(logits).item())

    pred6 = ID2LABEL_6[pred_id]
    pred4 = MAP_6_TO_4[pred6]

    return {"pred6": pred6, "probs6": probs, "pred4_tmp": pred4}


def run_one_file(
    model,
    tokenizer,
    device,
    in_path: Path,
    out_path: Path,
    batch_size: int,
    max_length: int,
) -> tuple[int, int]:
    rows = load_lines(in_path)
    out_rows: List[Dict[str, Any]] = []

    bs = max(1, int(batch_size))
    for start in range(0, len(rows), bs):
        batch = rows[start:start + bs]
        for b in batch:
            result = predict_one(
                model=model,
                tokenizer=tokenizer,
                device=device,
                text=b.get("text", ""),
                text_pair=b.get("text_pair"),
                max_length=max_length,
            )
            if result.get("_skip"):
                continue
            out = dict(b)
            out.update(result)
            out_rows.append(out)

    write_jsonl(out_rows, out_path)
    return len(rows), len(out_rows)


def main() -> None:
    # ✅ 스위치 체크
    if not RUN_OFFENDER_PAIR and not RUN_THOUGHTS_PAIR:
        print("[error] RUN_OFFENDER_PAIR / RUN_THOUGHTS_PAIR 둘 중 하나는 True여야 합니다.")
        return

    input_path = Path(INPUT_PATH)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[info] device={device}")

    tokenizer = AutoTokenizer.from_pretrained(
        TOKENIZER_ID,
        use_fast=False,
        trust_remote_code=True,
    )

    model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
    model.to(device)
    model.eval()

    files = list(iter_input_files(input_path))
    if not files:
        print(f"[warn] no input files found: {input_path}")
        print(f"       patterns: {get_target_globs()}")
        return

    total_in = 0
    total_out = 0

    print(f"[info] patterns: {get_target_globs()}")
    for in_file in files:
        out_file = output_path_for_input(in_file, out_dir)

        in_n, out_n = run_one_file(
            model=model,
            tokenizer=tokenizer,
            device=device,
            in_path=in_file,
            out_path=out_file,
            batch_size=BATCH_SIZE,
            max_length=MAX_LENGTH,
        )

        total_in += in_n
        total_out += out_n

        print(f"[done] {in_file.name}")
        print(f"       in={in_n} out={out_n}")
        print(f"       -> {out_file.name}")

    print("\n=== all done ===")
    print(f"  files: {len(files)}")
    print(f"  total_in_rows:  {total_in}")
    print(f"  total_out_rows: {total_out}")
    print(f"  output_dir: {out_dir}")


if __name__ == "__main__":
    main()
