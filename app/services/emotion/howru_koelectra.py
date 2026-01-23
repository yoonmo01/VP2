#VP/app/services/emotion/howru_koelectra.py
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# (선택) Windows 경고 줄이기
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

# =========================
# 모델 설정
# =========================
MODEL_ID = os.getenv("EMOTION_MODEL_ID", "LimYeri/HowRU-KoELECTRA-Emotion-Classifier")
TOKENIZER_ID = os.getenv("EMOTION_TOKENIZER_ID", MODEL_ID)

DEFAULT_MAX_LENGTH = int(os.getenv("EMOTION_MAX_LENGTH", "512"))
DEFAULT_BATCH_SIZE = int(os.getenv("EMOTION_BATCH_SIZE", "16"))

# =========================
# 8 -> 4 매핑/후처리 로직
# =========================
MAP_8_TO_4_BASE = {
    "기쁨": "E",      # ✅ 긍정(positive)은 E로 유지 권장
    "설렘": "E",      # ✅ 긍정(positive)은 E로 유지 권장
    "평범함": "N",
    "슬픔": "N",
    "불쾌함": "A",
    "분노": "A",
    "두려움": "F",
    "놀라움": None,  # 후처리 규칙에서 결정
}

HANDLE_SURPRISE = True

THREAT_CUES = [
    "검찰", "검사", "수사", "경찰", "금감원", "금융감독원", "지검", "지청",
    "연루", "범죄", "혐의", "피의자", "고소", "고발", "영장", "체포", "구속",
    "압수", "몰수", "송치", "기소", "재판", "벌금", "처벌",
    "동결", "정지", "차단", "거래정지", "계좌정지", "대포통장",
    "위험", "긴급", "즉시", "오늘 안에", "지금 당장", "큰일", "문제",
]

ANGER_CUES = [
    "사기", "보이스피싱", "거짓", "가짜", "수상", "이상하", "말이 안", "말도 안",
    "믿을 수", "의심", "확인할게", "직접 확인", "직접 연락", "방문해서",
    "못 드리", "안 드리", "절대", "거절", "불가능", "그만", "중단", "더 이상",
    "끊겠", "끊습니다", "전화 끊", "통화 종료",
    "왜", "짜증", "화가", "화났", "불쾌", "기분 나쁘", "협박", "강요",
    "신고", "경찰에 신고", "녹음", "증거",
    "개인정보", "주민등록번호", "계좌번호", "비밀번호", "위험", "부담스럽",
]

STRONG_REACTANCE_CUES = [
    "사기", "보이스피싱", "가짜", "거짓",
    "못 드리", "안 드리", "절대", "거절", "불가능",
    "끊겠", "끊습니다", "전화 끊", "통화 종료",
    "직접 확인", "직접 연락", "방문해서", "방문하", "찾아가",
    "신고", "경찰에 신고", "녹음", "증거",
]

SURPRISE_THREAT_MIN_SCORE = 3
SURPRISE_ANGER_MIN_SCORE = 1
SURPRISE_MIN_PROB = 0.20

# ✅ 정책: pred8이 "놀라움"으로 확정되면(=argmax) 임계값과 무관하게 항상 N/F/A로 치환할지
# - 기본 True(1): 사용자가 원하는 "놀라움이면 반드시 치환"을 보장
# - 끄고 싶으면 .env에서 EMOTION_SURPRISE_FORCE_IF_PRED8=0
SURPRISE_FORCE_IF_PRED8 = (os.getenv("EMOTION_SURPRISE_FORCE_IF_PRED8", "1") or "").strip().lower() in (
    "1", "true", "yes", "y", "on")

def _contains_any(text: str, cues: List[str]) -> int:
    t = (text or "").lower()
    score = 0
    for w in cues:
        if w.lower() in t:
            score += 1
    return score


def _has_any(text: str, cues: List[str]) -> bool:
    t = (text or "").lower()
    for w in cues:
        if w.lower() in t:
            return True
    return False


def decide_surprise_to_4(text: str, text_pair: Optional[str]) -> Tuple[str, Dict[str, int]]:
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
    pred8: Optional[str] = None,
) -> Dict[str, Any]:
    pN = pF = pA = pE = 0.0
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
            pN += p

    surprise_to = None
    cue_scores = {"threat_score": 0, "anger_score": 0}

    if surprise_idx is not None:
        # ✅ 정책:
        # 1) pred8이 "놀라움"이면(=확정 놀라움) 임계값과 무관하게 항상 N/F/A로 치환(기본 ON)
        # 2) 그 외에는 기존대로 p_surprise >= SURPRISE_MIN_PROB 일 때만 단서 기반 치환
        force_route = bool(SURPRISE_FORCE_IF_PRED8 and (pred8 == "놀라움"))
        should_route = force_route or (HANDLE_SURPRISE and (p_surprise >= SURPRISE_MIN_PROB))

        if not should_route:
            surprise_to = "N"
            cue_scores = {"threat_score": 0, "anger_score": 0}
        else:
            surprise_to, cue_scores = decide_surprise_to_4(text, text_pair)
            # 방어: surprise_to는 N/F/A만 허용 (4클래스에 놀라움/E로 보내는 정책 없음)
            if surprise_to not in ("N", "F", "A"):
                surprise_to = "N"

        if surprise_to == "N":
            pN += p_surprise
        elif surprise_to == "F":
            pF += p_surprise
        elif surprise_to == "A":
            pA += p_surprise
        else:
            pN += p_surprise

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
        "p_surprise": p_surprise,
    }


@dataclass
class EmotionItem:
    text: str
    text_pair: Optional[str] = None


class HowruKoelectraEmotionService:
    """
    - 프로세스 내 1회 로딩(singleton 권장)
    - 배치 추론 + (8->4) 후처리 포함
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = None
        self.model = None
        self.labels8: List[str] = []

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return

            tok = AutoTokenizer.from_pretrained(
                TOKENIZER_ID,
                use_fast=True,
                trust_remote_code=True,
            )
            mdl = AutoModelForSequenceClassification.from_pretrained(
                MODEL_ID,
                trust_remote_code=True,
            )
            mdl.to(self.device)
            mdl.eval()

            id2label = mdl.config.id2label
            # ✅ 모델마다 id2label 키가 int일 수도, str일 수도 있어서 안전하게 get 처리
            labels8: List[str] = []
            if isinstance(id2label, dict):
                for i in range(mdl.config.num_labels):
                    lab = id2label.get(i)
                    if lab is None:
                        lab = id2label.get(str(i))
                    labels8.append(str(lab) if lab is not None else str(i))
            else:
                # fallback: 라벨 정보를 못 얻는 경우
                labels8 = [str(i) for i in range(mdl.config.num_labels)]

            # ✅ 방어: 길이가 안 맞으면 강제로 맞춤
            if len(labels8) != mdl.config.num_labels:
                labels8 = (labels8 + [str(i) for i in range(mdl.config.num_labels)])[: mdl.config.num_labels]

            self.tokenizer = tok
            self.model = mdl
            self.labels8 = labels8
            self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    @torch.no_grad()
    def predict_batch(
        self,
        items: List[EmotionItem],
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_length: int = DEFAULT_MAX_LENGTH,
        include_probs8: bool = True,
    ) -> List[Dict[str, Any]]:
        self.load()
        assert self.model is not None
        assert self.tokenizer is not None

        results: List[Dict[str, Any]] = []

        bs = max(1, int(batch_size))
        for start in range(0, len(items), bs):
            chunk = items[start:start + bs]

            # pair 유무가 섞일 수 있어, 안전하게 item 단위 처리
            for it in chunk:
                text = (it.text or "").strip()
                if not text:
                    results.append({"_skip": True})
                    continue

                text_pair = (it.text_pair or None)
                if text_pair is not None:
                    text_pair = str(text_pair).strip() or None

                if text_pair is None:
                    enc = self.tokenizer(
                        text,
                        truncation=True,
                        max_length=max_length,
                        return_tensors="pt",
                    )
                else:
                    enc = self.tokenizer(
                        text,
                        text_pair=text_pair,
                        truncation=True,
                        max_length=max_length,
                        return_tensors="pt",
                    )

                enc = {k: v.to(self.device) for k, v in enc.items()}

                logits = self.model(**enc).logits[0]  # (8,)
                probs8 = torch.softmax(logits, dim=-1).detach().cpu().tolist()
                pred_id = int(torch.argmax(logits).item())
                pred8 = self.labels8[pred_id]

                pp = probs8_to_probs4_with_postprocess(
                    probs8=probs8,
                    labels8=self.labels8,
                    text=text,
                    text_pair=text_pair,
                    pred8=pred8,
                )

                out: Dict[str, Any] = {
                    "pred8": pred8,
                    "pred4": pp["pred4"],
                    "probs4": pp["probs4"],
                    "surprise_to": pp["surprise_to"],
                    "cue_scores": pp["cue_scores"],
                    "p_surprise": pp["p_surprise"],
                }
                if include_probs8:
                    out["probs8"] = probs8
                results.append(out)

        return results


# ✅ 싱글턴
emotion_service = HowruKoelectraEmotionService()


def preload_emotion_model() -> None:
    """
    ✅ 서버 시작 시(warmup) 호출용.
    app.main startup 이벤트에서 이 함수를 부르면
    '첫 요청에서 느려지는 문제'가 사라짐.
    """
    emotion_service.load()
