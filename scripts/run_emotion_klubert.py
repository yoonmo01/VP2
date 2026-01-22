# scripts/run_emotion_kluebert_v2_postprocess.py
# ✅ 실행: python scripts/run_emotion_kluebert_v2_postprocess.py
#
# 입력:
# - INPUT_PATH가 파일(.jsonl)이면: 그 파일 1개 처리
# - INPUT_PATH가 폴더면: (스위치에 따라) victim_offender_pair_*.jsonl / victim_thoughts_pair_*.jsonl 처리
#
# 출력(1:1):
# - out 파일명은 "pred_" + 원본 파일명
#   예) victim_offender_pair_<caseId>.jsonl -> pred_victim_offender_pair_<caseId>.jsonl
#   예) victim_thoughts_pair_<caseId>.jsonl -> pred_victim_thoughts_pair_<caseId>.jsonl
#
# 핵심:
# - KLUE-BERT v2 모델(7감정)을 그대로 사용해서 probs7/pred7을 얻고
# - 후처리 규칙으로 4감정(N/F/A/E)로 변환
# - 특히 "놀람"은 위협/보상 단서로 F/E/N 중 하나로 분기

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Windows에서 경고 줄이기(선택)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

# =========================
# 🔧 여기만 수정하면 됨
# =========================
INPUT_PATH = r"C:\LIT_VP2\VP\scripts\datasets"          # 파일(.jsonl) 또는 폴더
OUTPUT_DIR = r"C:\LIT_VP2\VP\scripts\emotion_result_klubert"    # 출력 폴더

# ✅ 스위치: 원하는 것만 True로 켜기
RUN_OFFENDER_PAIR = False     # victim_offender_pair_*.jsonl 처리
RUN_THOUGHTS_PAIR = True    # victim_thoughts_pair_*.jsonl 처리

BATCH_SIZE = 16
MAX_LENGTH = 256

# ✅ KLUE BERT v2 감정모델(7-class)
MODEL_ID = "dlckdfuf141/korean-emotion-kluebert-v2"
TOKENIZER_ID = "dlckdfuf141/korean-emotion-kluebert-v2"

# =========================
# 7-class 라벨 정의
# (모델 카드 기준: 0공포,1놀람,2분노,3슬픔,4중립,5행복,6혐오)
# =========================
ID2LABEL_7 = {
    0: "FEAR",      # 공포
    1: "SURPRISE",  # 놀람
    2: "ANGER",     # 분노
    3: "SAD",       # 슬픔
    4: "NEUTRAL",   # 중립
    5: "HAPPY",     # 행복
    6: "DISGUST",   # 혐오
}

# =========================
# 7 -> 4 기본 매핑(놀람은 규칙으로 처리)
# =========================
# - 논문 Emoti-Shing 관점에서:
#   N(Neutral), F(Fear), A(Anger), E(Excitement)
# - 기본적으로:
#   FEAR->F, ANGER->A, NEUTRAL->N, HAPPY->E
#   DISGUST는 강한 거부/반감이라 A로 합치는 편이 실전에서 안정적
#   SAD는 저각성 부정이라 N으로 두는 기본(원하면 F로 바꿔도 됨)
MAP_7_TO_4_BASE = {
    "FEAR": "F",
    "ANGER": "A",
    "NEUTRAL": "N",
    "HAPPY": "E",
    "DISGUST": "A",
    "SAD": "N",         # 필요하면 "F"로 변경 가능
    "SURPRISE": None,   # 후처리 규칙에서 결정
}

# =========================
# "놀람" 분기용 키워드(후처리 규칙)
# - 위협 단서: 공포(F)로 보냄
# - 보상 단서: 흥분/기대(E)로 보냄
# - 둘 다 없으면: N으로 보냄
# =========================
THREAT_CUES = [
    "검찰", "검사", "수사", "경찰", "금감원", "금융감독원", "지검", "지청",
    "연루", "범죄", "혐의", "피의자", "고소", "고발", "영장", "체포", "구속",
    "압수", "몰수", "송치", "기소", "재판", "벌금", "처벌",
    "동결", "정지", "차단", "거래정지", "계좌정지", "대포통장",
    "위험", "긴급", "즉시", "오늘 안에", "지금 당장", "큰일", "문제",
]

REWARD_CUES = [
    "환급", "당첨", "이득", "혜택", "지원금", "보상", "리워드", "캐시백",
    "승인", "대출승인", "한도", "금리", "우대", "수수료 면제",
    "입금", "지급", "받으실", "나옵니다", "해결", "안심", "괜찮습니다",
    "좋은 소식", "기회", "가능합니다",
]

# (선택) 놀람을 “분기”할지 여부를 좀 더 엄격히 하고 싶으면 threshold 사용 가능
# 예: 놀람 확률이 0.40 이상일 때만 분기하고, 아니면 기본매핑(또는 N)으로 처리
SURPRISE_MIN_PROB = 0.0  # 0.0이면 놀람이 top이든 아니든 규칙을 적용할 수 있음(아래 로직 참고)


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
    """스위치에 따라 폴더 입력 시 처리할 파일 패턴 결정"""
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
    """출력 파일명: pred_ + 원본 파일명"""
    return out_dir / f"pred_{in_file.name}"


def _contains_any(text: str, cues: List[str]) -> int:
    """단순 키워드 포함 개수(점수)"""
    t = (text or "").lower()
    score = 0
    for w in cues:
        if w.lower() in t:
            score += 1
    return score


def decide_surprise_to_4(text: str, text_pair: Optional[str]) -> Tuple[str, Dict[str, int]]:
    """
    놀람(SURPRISE)을 4감정(F/E/N) 중 어디로 보낼지 결정하는 후처리 규칙.
    - 위협 단서가 더 강하면 F
    - 보상 단서가 더 강하면 E
    - 둘 다 약하면 N
    """
    combined = (text or "")
    if text_pair:
        combined = combined + "\n" + str(text_pair)

    threat_score = _contains_any(combined, THREAT_CUES)
    reward_score = _contains_any(combined, REWARD_CUES)

    if threat_score > reward_score and threat_score > 0:
        return "F", {"threat_score": threat_score, "reward_score": reward_score}
    if reward_score > threat_score and reward_score > 0:
        return "E", {"threat_score": threat_score, "reward_score": reward_score}

    # 둘 다 애매하면 N
    return "N", {"threat_score": threat_score, "reward_score": reward_score}


def probs7_to_probs4_with_postprocess(
    probs7: List[float],
    text: str,
    text_pair: Optional[str],
) -> Dict[str, Any]:
    """
    핵심 후처리:
    1) 7개 확률(probs7)을 4개 확률(probs4)로 합산
    2) 다만 SURPRISE 확률은 규칙으로 F/E/N 중 하나에 "전부" 더한다.

    반환:
    - probs4: [P(N), P(F), P(A), P(E)] (합=1)
    - surprise_to: SURPRISE가 어디로 갔는지
    - cue_scores: 위협/보상 점수
    """
    # 4감정 확률 누적(순서 고정)
    pN = 0.0
    pF = 0.0
    pA = 0.0
    pE = 0.0

    # 먼저 SURPRISE 외를 기본 매핑으로 누적
    for idx, p in enumerate(probs7):
        lab7 = ID2LABEL_7[idx]
        if lab7 == "SURPRISE":
            continue
        lab4 = MAP_7_TO_4_BASE[lab7]
        if lab4 == "N":
            pN += p
        elif lab4 == "F":
            pF += p
        elif lab4 == "A":
            pA += p
        elif lab4 == "E":
            pE += p

    # SURPRISE 확률은 규칙으로 분배(여기선 한 곳에 몰아줌)
    p_surprise = probs7[1]  # SURPRISE index=1
    surprise_to, cue_scores = decide_surprise_to_4(text, text_pair)

    # SURPRISE_MIN_PROB 설정에 따라 "놀람 분기"를 제한할 수도 있음
    if p_surprise < SURPRISE_MIN_PROB:
        # 놀람이 약하면 그냥 N에 보내는 식(원하면 다른 정책 가능)
        surprise_to = "N"

    if surprise_to == "N":
        pN += p_surprise
    elif surprise_to == "F":
        pF += p_surprise
    elif surprise_to == "A":
        pA += p_surprise
    elif surprise_to == "E":
        pE += p_surprise

    # 정규화(합이 1이 되게)
    s = pN + pF + pA + pE
    if s > 0:
        pN, pF, pA, pE = pN / s, pF / s, pA / s, pE / s

    probs4 = [pN, pF, pA, pE]
    pred4 = ["N", "F", "A", "E"][int(torch.tensor(probs4).argmax().item())]

    return {
        "pred4": pred4,
        "probs4": probs4,
        "surprise_to": surprise_to,
        "cue_scores": cue_scores,
    }


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
        logits = model(**enc).logits[0]  # (7,)
        probs7 = torch.softmax(logits, dim=-1).detach().cpu().tolist()
        pred_id = int(torch.argmax(logits).item())

    pred7 = ID2LABEL_7[pred_id]  # FEAR/SURPRISE/...

    # ✅ 후처리로 7->4 변환(놀람 분기 포함)
    pp = probs7_to_probs4_with_postprocess(probs7, text, text_pair)

    return {
        "pred7": pred7,
        "probs7": probs7,
        "pred4": pp["pred4"],
        "probs4": pp["probs4"],
        "surprise_to": pp["surprise_to"],
        "cue_scores": pp["cue_scores"],
    }


def run_one_file(
    model,
    tokenizer,
    device,
    in_path: Path,
    out_path: Path,
    batch_size: int,
    max_length: int,
) -> Tuple[int, int]:
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
        use_fast=True,
        trust_remote_code=True,
    )

    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
    )
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
