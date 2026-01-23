#VP/app/services/emotion/label_turns.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple
import json
import os
from app.services.emotion.howru_koelectra import EmotionItem, emotion_service


PairMode = Literal["none", "prev_offender", "prev_victim", "thoughts", "prev_offender+thoughts", "prev_victim+thoughts"]
HmmAttachMode = Literal["per_victim_turn", "last_victim_turn_only"]


def _norm_role(turn: Dict[str, Any]) -> str:
    return str(turn.get("role") or turn.get("speaker") or turn.get("actor") or "").strip().lower()


def _is_victim(turn: Dict[str, Any]) -> bool:
    role = _norm_role(turn)
    return role in ("victim", "피해자", "user", "사용자")


def _is_offender(turn: Dict[str, Any]) -> bool:
    role = _norm_role(turn)
    return role in ("offender", "scammer", "가해자", "사기범")

def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("```", 1)[-1]  # 앞부분 제거
        # 맨 끝 ``` 제거
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()

def _normalize_quotes(s: str) -> str:
    return (
        (s or "")
        .replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2018", "'").replace("\u2019", "'")
    )

def _try_parse_victim_json(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    victim turn의 text가 {"dialogue": "...", "thoughts":"..."} JSON 문자열로 들어오는 케이스 지원.
    반환: (dialogue, thoughts)
    """
    if not text:
        return None, None
    s = _normalize_quotes(_strip_code_fences(text)).strip()
    if not s.startswith("{"):
        return None, None
    try:
        obj = json.loads(s)
        if not isinstance(obj, dict):
            return None, None
        dlg = obj.get("dialogue")
        th  = obj.get("thoughts")
        dlg_s = dlg.strip() if isinstance(dlg, str) and dlg.strip() else None
        th_s  = th.strip()  if isinstance(th, str)  and th.strip()  else None
        return dlg_s, th_s
    except Exception:
        return None, None

def _try_parse_victim_payload(text: str) -> Optional[Dict[str, Any]]:
    """
    victim turn의 text가 {"dialogue": "...", "thoughts":"...", "is_convinced": ...} 형태인 케이스 지원.
    """
    if not text:
        return None
    s = _normalize_quotes(_strip_code_fences(text)).strip()
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def _get_text(turn: Dict[str, Any]) -> str:
    return str(turn.get("text") or turn.get("content") or "").strip()

def _get_dialogue_for_emotion(turn: Dict[str, Any]) -> str:
    """
    감정모델 입력은 '피해자 JSON이면 dialogue만', 아니면 text 전체.
    """
    raw = _get_text(turn)
    if _is_victim(turn):
        dlg, _ = _try_parse_victim_json(raw)
        return dlg or raw
    return raw

def _get_thoughts(turn: Dict[str, Any]) -> Optional[str]:
    # 프로젝트에 따라 thoughts 키 이름이 다를 수 있어 안전하게 커버
    v = turn.get("thoughts")
    if v is None:
        v = turn.get("text_pair")
    if v is None:
        v = turn.get("inner_thoughts")
    if v is None:
        # victim text가 JSON 문자열인 경우 thoughts를 거기서 추출
        raw = _get_text(turn)
        if _is_victim(turn):
            _, th = _try_parse_victim_json(raw)
            return th
        return None
    s = str(v).strip()
    return s or None

def _get_is_convinced(turn: Dict[str, Any]) -> Optional[int]:
    """
    is_convinced를 turn dict 또는 victim JSON(text)에서 추출.
    """
    v = turn.get("is_convinced")
    if isinstance(v, (int, float)):
        return int(v)
    # victim text(JSON 문자열)에서 파싱
    if _is_victim(turn):
        payload = _try_parse_victim_payload(_get_text(turn))
        if payload is not None:
            vv = payload.get("is_convinced")
            if isinstance(vv, (int, float)):
                return int(vv)
            # 문자열 숫자도 방어
            if isinstance(vv, str) and vv.strip().lstrip("-").isdigit():
                try:
                    return int(vv.strip())
                except Exception:
                    return None
    return None

def _contains_any(s: str, keywords: List[str]) -> bool:
    ss = (s or "").strip()
    if not ss:
        return False
    return any(k in ss for k in keywords)

def _override_pred4_if_needed(
    *,
    pred4: str,
    probs4: Optional[List[float]],
    victim_text: str,
    is_convinced: Optional[int],
) -> Tuple[str, Optional[List[float]], Optional[Dict[str, Any]]]:
    """
    ✅ F 과편향 완화용 후처리:
    - 거절/종료(단절) 표현이 강한데 pred4가 F로 나오는 경우
      -> A(단호/저항) 또는 N(종료)로 override
    - is_convinced가 낮을수록(<=1) override를 더 적극 적용
    """
    p4 = (pred4 or "").strip().upper()
    if p4 != "F":
        return pred4, probs4, None

    txt = (victim_text or "").strip()
    if not txt:
        return pred4, probs4, None

    # 🔥 종료/차단 신호(강함) → N
    termination_kw = [
        "대화를 종료", "통화를 종료", "전화 끊", "끊겠습니다", "끊을게요", "끊어요",
        "그만하겠습니다", "그만할게요", "더 이상 대화", "더 이상 통화", "연락하지 마",
        "신고하겠습니다", "신고할게요",
    ]
    # 🔥 거절/개인정보 차단(강함) → A
    refusal_kw = [
        "개인정보", "정보를 드릴", "드릴 수 없", "줄 수 없", "못 드", "못 줍",
        "거절", "정식 절차", "공식 절차", "절차를 밟", "수상", "보이스피싱", "사기",
        "증빙", "공문", "문서", "확인해", "확인 후",
    ]

    is_low = (is_convinced is None) or (is_convinced <= 1)
    if not is_low:
        # convinced가 높은데 fear면(순응 가능성) override하지 않음
        return pred4, probs4, None

    override_to: Optional[str] = None
    reason: Optional[str] = None
    if _contains_any(txt, termination_kw):
        override_to = "N"
        reason = "termination_or_block_signal"
    elif _contains_any(txt, refusal_kw):
        override_to = "A"
        reason = "strong_refusal_signal"

    if not override_to:
        return pred4, probs4, None

    # probs4는 [N, F, A, E] 순서를 가정
    new_probs = None
    if isinstance(probs4, list) and len(probs4) == 4:
        try:
            n, f, a, e = [float(x) for x in probs4]
            if override_to == "A":
                # fear mass를 anger로 이동(최소 a가 f 이상 되도록)
                moved = max(0.0, f - a)
                a = a + moved
                f = f - moved
            elif override_to == "N":
                # fear mass를 neutral로 이동(최소 n이 f 이상 되도록)
                moved = max(0.0, f - n)
                n = n + moved
                f = f - moved
            # 정규화
            s = n + f + a + e
            if s > 0:
                new_probs = [n / s, f / s, a / s, e / s]
            else:
                new_probs = probs4
        except Exception:
            new_probs = probs4

    override_meta = {
        "from": pred4,
        "to": override_to,
        "reason": reason,
        "is_convinced": is_convinced,
        "matched_text": txt[:120],
    }
    return override_to, (new_probs if new_probs is not None else probs4), override_meta

def _get_prev_offender_text(out_turns: List[Dict[str, Any]], i: int) -> Optional[str]:
    for j in range(i - 1, -1, -1):
        tj = out_turns[j]
        if _is_offender(tj):
            txt = _get_text(tj)
            return txt or None
    return None

def _get_prev_victim_text(out_turns: List[Dict[str, Any]], i: int) -> Optional[str]:
    """
    ✅ 직전 '피해자' 발화(감정모델 입력 기준)를 찾는다.
    - victim text가 JSON이면 dialogue만 추출해서 사용
    """
    for j in range(i - 1, -1, -1):
        tj = out_turns[j]
        if _is_victim(tj):
            txt = _get_dialogue_for_emotion(tj)
            return txt or None
    return None

def _try_run_hmm(emotion_seq: List[str]) -> Optional[Dict[str, Any]]:
    """
    ✅ HMM은 논문 기반으로 네가 만들 예정이니까,
    여기서는 '있으면 호출'하는 플러그인 방식으로 둔다.

    나중에 아래 모듈/함수를 만들면 자동 연결됨:
    - app.services.hmm.runner.run_hmm_on_emotions(emotion_seq: List[str]) -> Dict[str, Any]

    기대 반환 형식(권장):
    {
      "state_names": ["v1","v2","v3"],
      "gamma": [[p1,p2,p3], ...],   # T x 3 (턴별 posterior)  (선택)
      "path": ["v1","v1","v2",...], # Viterbi path           (선택)
      "final_state": "v2",          # 최종 상태              (선택)
      "final_probs": [p1,p2,p3],    # 마지막 posterior       (선택)
      ... (추가 메타 OK)
    }
    """
    try:
        from app.services.hmm.runner import run_hmm_on_emotions  # type: ignore
        return run_hmm_on_emotions(emotion_seq)
    except Exception:
        # HMM 구현 전/미존재/에러면 그냥 None으로
        return None


def label_emotions_on_turns(
    turns: List[Dict[str, Any]],
    *,
    pair_mode: PairMode = "none",
    batch_size: int = 16,
    max_length: int = 512,
    run_hmm: bool = True,
    hmm_attach: HmmAttachMode = "per_victim_turn",
) -> List[Dict[str, Any]]:
    """
    turns를 받아서:
    1) 피해자 발화에만 emotion 결과 주입
    2) (옵션) 피해자 pred4 시퀀스를 HMM에 넣고 v1/v2/v3 결과를 주입
    """
    out_turns = [dict(t) for t in turns]
    # ✅ 디버그 출력 토글: EMOTION_DEBUG_INPUT=1 일 때만 출력
    debug_input = (os.getenv("EMOTION_DEBUG_INPUT", "0") or "").strip().lower() in ("1","true","yes","y","on")
    def _dbg(msg: str) -> None:
        if debug_input:
            print(msg, flush=True)

    victim_indices: List[int] = []
    items: List[EmotionItem] = []

    # 1) 피해자 발화만 추출해서 모델 입력 구성
    for i, t in enumerate(out_turns):
        if not _is_victim(t):
            continue

        # ✅ 현재 victim의 모델 입력 text(=dialogue 우선)
        text = _get_dialogue_for_emotion(t)
        if not text:
            continue

        text_pair: Optional[str] = None
        if pair_mode == "prev_offender":
            text_pair = _get_prev_offender_text(out_turns, i)
        elif pair_mode == "prev_victim":
            text_pair = _get_prev_victim_text(out_turns, i)
        elif pair_mode == "thoughts":
            text_pair = _get_thoughts(t)
        elif pair_mode == "prev_offender+thoughts":
            a = _get_prev_offender_text(out_turns, i)
            b = _get_thoughts(t)
            if a and b:
                text_pair = f"{a}\n{b}"
            else:
                text_pair = a or b
        elif pair_mode == "prev_victim+thoughts":
            a = _get_prev_victim_text(out_turns, i)
            b = _get_thoughts(t)
            if a and b:
                text_pair = f"{a}\n{b}"
            else:
                text_pair = a or b
        # ✅ 모델 입력 확인 로그
        _dbg(
            "[EMOTION_INPUT]"
            f" pair_mode={pair_mode}"
            f" victim_turn_idx={i}"
            f" text={text!r}"
            f" text_pair={text_pair!r}"
        )
        victim_indices.append(i)
        items.append(EmotionItem(text=text, text_pair=text_pair))

    if not items:
        return out_turns

    # 2) 감정 예측
    preds = emotion_service.predict_batch(
        items,
        batch_size=batch_size,
        max_length=max_length,
        include_probs8=True,
    )

    # 3) 결과 주입 + 피해자 pred4 시퀀스 수집
    victim_emotion_seq: List[str] = []            # HMM 입력용 (피해자 pred4)
    labeled_victim_indices: List[int] = []        # _skip 제외한 실제 주입된 victim turn index
    for idx, pred in zip(victim_indices, preds):
        if pred.get("_skip"):
            continue

        # ✅ 후처리(override)용 정보
        victim_text_for_rule = _get_dialogue_for_emotion(out_turns[idx])
        victim_is_convinced = _get_is_convinced(out_turns[idx])

        # ✅ F 과편향 완화: 거절/종료 케이스면 pred4를 A/N으로 교정
        adj_pred4, adj_probs4, override_meta = _override_pred4_if_needed(
            pred4=pred.get("pred4"),
            probs4=pred.get("probs4"),
            victim_text=victim_text_for_rule,
            is_convinced=victim_is_convinced,
        )

        emotion_obj = {
            "pred4": adj_pred4,
            "probs4": adj_probs4 if adj_probs4 is not None else pred.get("probs4"),
            "pred8": pred["pred8"],
            "probs8": pred.get("probs8"),
            "surprise_to": pred.get("surprise_to"),
            "cue_scores": pred.get("cue_scores"),
            "p_surprise": pred.get("p_surprise"),
        }
        if override_meta:
            emotion_obj["override"] = override_meta
        out_turns[idx]["emotion"] = emotion_obj
        # ✅ HMM 입력도 교정된 pred4로 사용해야 v3 과대상승을 막을 수 있음
        victim_emotion_seq.append(adj_pred4)
        labeled_victim_indices.append(idx)

    # 4) (옵션) HMM 실행 후 결과 주입
    if run_hmm and victim_emotion_seq:
        hmm_result = _try_run_hmm(victim_emotion_seq)

        if hmm_result:
            gamma = hmm_result.get("gamma")  # T x 3 (optional)
            path = hmm_result.get("path")    # T (optional)

            # attach 모드에 따라
            if hmm_attach == "per_victim_turn" and isinstance(gamma, list):
                # 실제 주입된 victim_emotion_seq 길이와 gamma 길이가 같을 때만 per-turn 주입
                if len(gamma) == len(labeled_victim_indices):
                    for t_i, turn_idx in enumerate(labeled_victim_indices):
                        out_turns[turn_idx]["hmm"] = {
                            "state_names": hmm_result.get("state_names", ["v1", "v2", "v3"]),
                            "posterior": gamma[t_i],
                            "viterbi": path[t_i] if isinstance(path, list) and t_i < len(path) else None,
                        }

            # 요약 결과는 마지막 victim turn에 붙여두면 downstream에서 쓰기 쉬움
            last_victim_turn_idx = labeled_victim_indices[-1] if labeled_victim_indices else victim_indices[-1]
            out_turns[last_victim_turn_idx].setdefault("hmm_summary", {})
            out_turns[last_victim_turn_idx]["hmm_summary"] = {
                "state_names": hmm_result.get("state_names", ["v1", "v2", "v3"]),
                "final_state": hmm_result.get("final_state"),
                "final_probs": hmm_result.get("final_probs"),
                "path": hmm_result.get("path"),
                "meta": {k: v for k, v in hmm_result.items() if k not in ("gamma", "path", "final_state", "final_probs", "state_names")},
            }

    return out_turns
