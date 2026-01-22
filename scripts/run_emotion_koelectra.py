# scripts/run_emotion_howru_koelectra_postprocess.py
# ✅ 실행: python scripts/run_emotion_howru_koelectra_postprocess.py
#
# 입력:
# - INPUT_PATH가 파일(.jsonl)이면: 그 파일 1개 처리
# - INPUT_PATH가 폴더면: (스위치에 따라) 4가지 유형 패턴을 선택 처리
#
# 출력(1:1):
# - out 파일명은 "pred_" + 원본 파일명
#
# 지원 4유형:
# (1) victim_only_*.jsonl
# (2) victim_offender_pair_*.jsonl
# (3) victim_thoughts_pair_*.jsonl
# (4) victim_offender_thoughts_*.jsonl
#
# 핵심:
# - HowRU KoELECTRA 감정모델(8감정)을 사용해서 probs8/pred8을 얻고
# - 후처리 규칙으로 4감정(N/F/A/E)로 변환
# - 특히 "놀라움(Surprise)"은 위협/반발(거부/의심) 단서로 F/A/N 중 하나로 분기
#
# ✅ 변경사항(요청 반영):
# - 기존에 E로 가던 것(기쁨/설렘)을 A로 보냄
# - Surprise 분기에서 reward(보상) 기반 분기는 제거하고, 반발(anger) 단서로 A 분기
# - ✅ 케이스 흐름 반영 룰 강화:
#   - "강한 반발(사기 확신/끊기/직접 확인/강한 거절)" 단서가 있으면 A 우선
#   - 그렇지 않으면 threat_score가 "충분히 강할 때"(>=3) + threat>anger일 때 F
#   - 나머지는 anger_score>=1이면 A, 아니면 N
# - ✅ SURPRISE_MIN_PROB를 올려서(0.20) 놀라움 확률이 충분할 때만 분기 적용(로그 혼란 감소)

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
INPUT_PATH = r"C:\LIT_VP2\VP\scripts\datasets_0122"                 # 파일(.jsonl) 또는 폴더
OUTPUT_DIR = r"C:\LIT_VP2\VP\scripts\emotion_result_koelectra"     # 출력 폴더

# ✅ 스위치: 원하는 것만 True로 켜기 (4가지 유형)
RUN_VICTIM_ONLY = False            # victim_only_*.jsonl
RUN_OFFENDER_PAIR = True           # victim_offender_pair_*.jsonl
RUN_THOUGHTS_PAIR = False          # victim_thoughts_pair_*.jsonl
RUN_OFFENDER_THOUGHTS = False      # victim_offender_thoughts_*.jsonl

BATCH_SIZE = 16
MAX_LENGTH = 512  # 모델 카드/예시가 512 사용. 비교 실험이면 여기 고정 추천.

# ✅ HowRU KoELECTRA 감정모델(8-class)
MODEL_ID = "LimYeri/HowRU-KoELECTRA-Emotion-Classifier"
TOKENIZER_ID = "LimYeri/HowRU-KoELECTRA-Emotion-Classifier"

# ✅ 출력에 labels8(라벨 순서)까지 넣을지(행마다 반복 저장되므로 용량 증가)
INCLUDE_LABELS8_IN_EACH_ROW = False

# =========================
# ✅ 8 -> 4 매핑 (요청 반영)
# =========================
# 기쁨(Joy), 설렘(Excitement) -> ✅ A(Anger)  (기존 E였음)
# 평범함(Neutral), 슬픔(Sadness) -> N(Neutral)
# 불쾌함(Disgust), 분노(Anger) -> A(Anger)
# 두려움(Fear) -> F(Fear)
# 놀라움(Surprise) -> 규칙으로 F/A/N 분기
MAP_8_TO_4_BASE = {
    "기쁨": "A",      # ✅ 변경: E -> A
    "설렘": "A",      # ✅ 변경: E -> A
    "평범함": "N",
    "슬픔": "N",
    "불쾌함": "A",
    "분노": "A",
    "두려움": "F",
    "놀라움": None,  # 후처리 규칙에서 결정
}

# =========================
# "놀라움" 분기 옵션
# =========================
HANDLE_SURPRISE = True

# - 위협/위기 단서: Fear(F)로 보냄
THREAT_CUES = [
    "검찰", "검사", "수사", "경찰", "금감원", "금융감독원", "지검", "지청",
    "연루", "범죄", "혐의", "피의자", "고소", "고발", "영장", "체포", "구속",
    "압수", "몰수", "송치", "기소", "재판", "벌금", "처벌",
    "동결", "정지", "차단", "거래정지", "계좌정지", "대포통장",
    "위험", "긴급", "즉시", "오늘 안에", "지금 당장", "큰일", "문제",
]

# - 반발/거부/의심 단서: Anger(A)로 보냄
#   (기관사칭 데이터에서는 '보상/이득' 키워드가 오히려 노이즈라 제거)
ANGER_CUES = [
    # 의심/사기 인지
    "사기", "보이스피싱", "거짓", "가짜", "수상", "이상하", "말이 안", "말도 안",
    "믿을 수", "의심", "확인할게", "직접 확인", "직접 연락", "방문해서",
    # 거부/끊기/강한 거절
    "못 드리", "안 드리", "절대", "거절", "불가능", "그만", "중단", "더 이상",
    "끊겠", "끊습니다", "전화 끊", "통화 종료",
    # 공격/항의/신고
    "왜", "짜증", "화가", "화났", "불쾌", "기분 나쁘", "협박", "강요",
    "신고", "경찰에 신고", "녹음", "증거",
    # 개인정보/위험 경고(거부 뉘앙스일 때)
    "개인정보", "주민등록번호", "계좌번호", "비밀번호", "위험", "부담스럽",
]

# ✅ 강한 반발(Reactance) 단서: threat 키워드가 같이 떠도 A 우선
STRONG_REACTANCE_CUES = [
    "사기", "보이스피싱", "가짜", "거짓",
    "못 드리", "안 드리", "절대", "거절", "불가능",
    "끊겠", "끊습니다", "전화 끊", "통화 종료",
    "직접 확인", "직접 연락", "방문해서", "방문하", "찾아가",
    "신고", "경찰에 신고", "녹음", "증거",
]

# Surprise 분기 임계값(키워드 점수 기반)
# - threat_score가 이 값 이상이면 (조건부) F
SURPRISE_THREAT_MIN_SCORE = 3
# - anger_score가 이 값 이상이면 A로 분기(단, 아래 룰 우선순위 적용)
SURPRISE_ANGER_MIN_SCORE = 1

# ✅ 놀라움 확률이 충분할 때만 분기 적용(로그 혼란 감소)
SURPRISE_MIN_PROB = 0.20


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
    if RUN_VICTIM_ONLY:
        globs.append("victim_only_*.jsonl")
    if RUN_OFFENDER_PAIR:
        globs.append("victim_offender_pair_*.jsonl")
    if RUN_THOUGHTS_PAIR:
        globs.append("victim_thoughts_pair_*.jsonl")
    if RUN_OFFENDER_THOUGHTS:
        globs.append("victim_offender_thoughts_*.jsonl")
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


def _has_any(text: str, cues: List[str]) -> bool:
    """키워드 하나라도 포함 여부"""
    t = (text or "").lower()
    for w in cues:
        if w.lower() in t:
            return True
    return False


def decide_surprise_to_4(text: str, text_pair: Optional[str]) -> Tuple[str, Dict[str, int]]:
    """
    Surprise(놀라움)을 4감정(F/A/N) 중 어디로 보낼지 결정 (케이스 흐름 반영)
    우선순위:
    1) 강한 반발 단서가 있으면 A
    2) threat가 충분히 강하고(threat>=3) threat > anger이면 F
    3) anger_score가 1 이상이면 A
    4) 그 외 N
    """
    combined = (text or "")
    if text_pair:
        combined = combined + "\n" + str(text_pair)

    threat_score = _contains_any(combined, THREAT_CUES)
    anger_score = _contains_any(combined, ANGER_CUES)
    strong_reactance = _has_any(combined, STRONG_REACTANCE_CUES)

    if strong_reactance:
        return "A", {"threat_score": threat_score, "anger_score": anger_score}

    if threat_score >= SURPRISE_THREAT_MIN_SCORE and threat_score > anger_score:
        return "F", {"threat_score": threat_score, "anger_score": anger_score}

    if anger_score >= SURPRISE_ANGER_MIN_SCORE:
        return "A", {"threat_score": threat_score, "anger_score": anger_score}

    return "N", {"threat_score": threat_score, "anger_score": anger_score}


def probs8_to_probs4_with_postprocess(
    probs8: List[float],
    labels8: List[str],
    text: str,
    text_pair: Optional[str],
) -> Dict[str, Any]:
    """
    8개 확률(probs8) -> 4개 확률(probs4=[P(N),P(F),P(A),P(E)]) 변환
    - Surprise(놀라움) 확률은 규칙으로 F/A/N 중 하나에 "전부" 더함
    """
    pN = 0.0
    pF = 0.0
    pA = 0.0
    pE = 0.0

    p_surprise = 0.0
    surprise_idx = None

    for i, p in enumerate(probs8):
        lab8 = labels8[i]

        if lab8 == "놀라움":
            p_surprise = p
            surprise_idx = i
            continue

        lab4 = MAP_8_TO_4_BASE.get(lab8)
        if lab4 == "N":
            pN += p
        elif lab4 == "F":
            pF += p
        elif lab4 == "A":
            pA += p
        elif lab4 == "E":
            pE += p
        else:
            # 예상 밖 라벨이면 안전하게 N으로
            pN += p

    surprise_to = None
    cue_scores = {"threat_score": 0, "anger_score": 0}

    if surprise_idx is not None:
        # ✅ 놀라움 확률이 충분할 때만 분기(로그 혼란 감소)
        if (not HANDLE_SURPRISE) or (p_surprise < SURPRISE_MIN_PROB):
            surprise_to = "N"
            cue_scores = {"threat_score": 0, "anger_score": 0}
        else:
            surprise_to, cue_scores = decide_surprise_to_4(text, text_pair)

        if surprise_to == "N":
            pN += p_surprise
        elif surprise_to == "F":
            pF += p_surprise
        elif surprise_to == "A":
            pA += p_surprise
        elif surprise_to == "E":
            pE += p_surprise
        else:
            pN += p_surprise

    # 정규화
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
        "p_surprise": p_surprise,  # 디버깅용(원하면 유지, 싫으면 지워도 됨)
    }


def predict_one(
    model,
    tokenizer,
    device,
    labels8: List[str],
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
        logits = model(**enc).logits[0]  # (8,)
        probs8 = torch.softmax(logits, dim=-1).detach().cpu().tolist()
        pred_id = int(torch.argmax(logits).item())

    pred8 = labels8[pred_id]
    pp = probs8_to_probs4_with_postprocess(probs8, labels8, text, text_pair)

    out: Dict[str, Any] = {
        "pred8": pred8,
        "probs8": probs8,   # labels8 순서대로
        "pred4": pp["pred4"],
        "probs4": pp["probs4"],
        "surprise_to": pp["surprise_to"],
        "cue_scores": pp["cue_scores"],
        "p_surprise": pp["p_surprise"],
    }
    if INCLUDE_LABELS8_IN_EACH_ROW:
        out["labels8"] = labels8
    return out


def run_one_file(
    model,
    tokenizer,
    device,
    labels8: List[str],
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
                labels8=labels8,
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
    if not (RUN_VICTIM_ONLY or RUN_OFFENDER_PAIR or RUN_THOUGHTS_PAIR or RUN_OFFENDER_THOUGHTS):
        print("[error] RUN_* 스위치 중 최소 1개는 True여야 합니다.")
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

    # ✅ 라벨 순서(모델 config 기반) -> probs8 해석에 사용
    id2label = model.config.id2label
    labels8 = [id2label[i] if isinstance(id2label, dict) else None for i in range(model.config.num_labels)]
    if labels8[0] is None:
        labels8 = [id2label[str(i)] for i in range(model.config.num_labels)]

    print(f"[info] labels8_order={labels8}")

    patterns = get_target_globs()
    print(f"[info] patterns: {patterns}")

    files = list(iter_input_files(input_path))
    if not files:
        print(f"[warn] no input files found: {input_path}")
        print(f"       patterns: {patterns}")
        return

    total_in = 0
    total_out = 0

    for in_file in files:
        out_file = output_path_for_input(in_file, out_dir)

        in_n, out_n = run_one_file(
            model=model,
            tokenizer=tokenizer,
            device=device,
            labels8=labels8,
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
