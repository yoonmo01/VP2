#VP/app/services/agent/tools_emotion.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
import json
import os
import ast
import copy

from pydantic import BaseModel, Field, model_validator
from langchain_core.tools import tool
from app.services.emotion.label_turns import label_emotions_on_turns


PairMode = Literal["none", "prev_offender", "prev_victim", "thoughts", "prev_offender+thoughts", "prev_victim+thoughts"]
HmmAttachMode = Literal["per_victim_turn", "last_victim_turn_only"]

_PAIR_MODE_ALLOWED = {"none", "prev_offender", "prev_victim", "thoughts", "prev_offender+thoughts", "prev_victim+thoughts"}

def _loads_maybe_obj(s: str) -> Optional[Any]:
    """
    문자열이 JSON 또는 Python literal(dict/list) 형태일 수 있어 파싱을 시도한다.
    실패하면 None.
    """
    ss = (s or "").strip()
    if not ss:
        return None
    try:
        return json.loads(ss)
    except Exception:
        try:
            return ast.literal_eval(ss)
        except Exception:
            return None

def _normalize_turn_text(t: Dict[str, Any]) -> Dict[str, Any]:
    """
    turns 원소의 text 형태를 안정적으로 정규화한다.
    - text가 JSON 문자열이면 dict로 변환
    - text가 일반 문자열이면 role에 따라 {"utterance":...} / {"dialogue":...} 로 감싼다
    - turn 최상위에 있는 proc_code/ppse_labels/is_convinced/thoughts 등을 text dict로 복사해 일관성 유지
    """
    role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()

    # 0) text가 아예 없고 최상위에 utterance/dialogue가 있으면 text dict 생성
    if "text" not in t or t.get("text") is None:
        if "utterance" in t:
            t["text"] = {"utterance": t.get("utterance")}
        elif "dialogue" in t:
            t["text"] = {"dialogue": t.get("dialogue")}

    text = t.get("text")

    # 1) text가 문자열인 경우: JSON 문자열인지 먼저 파싱 시도
    if isinstance(text, str):
        parsed = _loads_maybe_obj(text)
        if isinstance(parsed, dict):
            t["text"] = parsed
        else:
            s = text.strip()
            if role == "offender":
                t["text"] = {"utterance": s}
            elif role == "victim":
                t["text"] = {"dialogue": s}
            else:
                t["text"] = {"raw": s}

    # 2) text가 dict가 아니면 raw로 감싸기
    elif not isinstance(text, dict):
        if role == "offender":
            t["text"] = {"utterance": str(text)}
        elif role == "victim":
            t["text"] = {"dialogue": str(text)}
        else:
            t["text"] = {"raw": str(text)}

    # 3) 일관성: 최상위 메타를 text(dict)에도 복사 (label_turns 쪽이 어디서 읽든 안전)
    if isinstance(t.get("text"), dict):
        td: Dict[str, Any] = t["text"]

        if role == "offender":
            for k in ("proc_code", "ppse_labels", "utterance"):
                if k in t and k not in td:
                    td[k] = t[k]
        elif role == "victim":
            for k in ("is_convinced", "thoughts", "dialogue"):
                if k in t and k not in td:
                    td[k] = t[k]

        # role도 보존(혹시 downstream이 text 내부 role을 참고하는 경우 방어)
        if "role" not in td and role:
            td["role"] = role

    return t

def _env_bool(name: str, default: bool) -> bool:
    """
    환경변수 bool 파서:
        - true/1/yes/y/on => True
        - false/0/no/n/off => False
    """
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default

def _default_emotion_enabled() -> bool:
    # EMOTION_ENABLED=0 이면 tool이 no-op로 동작
    return _env_bool("EMOTION_ENABLED", True)

def _default_emotion_compact() -> bool:
    """
    감정 출력(token)을 줄이기 위한 compact 모드.
    - True: emotion = {"final": "<N|F|A|E|S>"} 형태로만 남김
    - False: 기존처럼 pred/probs/override 등 전체를 유지
    env: EMOTION_COMPACT (default: True)
    """
    return _env_bool("EMOTION_COMPACT", True)

def _compact_hmm_summary_payload(hs: Dict[str, Any]) -> Dict[str, Any]:
    """
    hmm_summary를 요구사항에 맞게 축약:
    - state_names 제거
    - meta.meta에서 obs_norm, state_counts, v3_ratio만 유지
    - viterbi_logp/loglik 등 제거
    """
    out: Dict[str, Any] = {}

    # admin_summary에서 p_v3/v3_ratio를 뽑아 쓰므로 final_state/final_probs는 유지
    if isinstance(hs.get("final_state"), str) and hs.get("final_state"):
        out["final_state"] = hs.get("final_state")
    fp = hs.get("final_probs")
    if isinstance(fp, (list, tuple)) and len(fp) == 3:
        out["final_probs"] = list(fp)

    meta = hs.get("meta")
    if isinstance(meta, dict):
        inner = meta.get("meta") if isinstance(meta.get("meta"), dict) else meta
        if isinstance(inner, dict):
            mm: Dict[str, Any] = {}
            if isinstance(inner.get("obs_norm"), list):
                mm["obs_norm"] = inner.get("obs_norm")
            if isinstance(inner.get("state_counts"), dict):
                mm["state_counts"] = inner.get("state_counts")
            if "v3_ratio" in inner:
                try:
                    mm["v3_ratio"] = float(inner.get("v3_ratio"))
                except Exception:
                    pass
            if mm:
                out["meta"] = {"meta": mm}

    return out

def _apply_compact_hmm_in_place(turns: List[Dict[str, Any]]) -> None:
    """
    compact 모드에서 HMM 출력까지 축약:
    - victim turn의 per-turn "hmm" 제거 (posterior/viterbi/state_names 등 제거 목적)
    - hmm_summary는 마지막 victim turn에만 1개 유지 + 축약(state_names 제거, meta 필드 최소화)
    """
    if not turns:
        return

    last_hmm_summary: Optional[Dict[str, Any]] = None
    last_victim_idx: Optional[int] = None

    # 1) 후보 수집 + per-turn hmm 제거
    for i, t in enumerate(turns):
        if not isinstance(t, dict):
            continue
        role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()
        if role == "victim":
            last_victim_idx = i
            # ✅ 요구사항: victim turn의 hmm는 전부 제거
            t.pop("hmm", None)

        hs = t.get("hmm_summary")
        if isinstance(hs, dict) and hs:
            last_hmm_summary = hs

    # 2) 전체에서 hmm_summary 제거 후, 마지막 victim에만 축약본 재부착
    for t in turns:
        if isinstance(t, dict):
            t.pop("hmm_summary", None)

    if last_hmm_summary and last_victim_idx is not None:
        turns[last_victim_idx]["hmm_summary"] = _compact_hmm_summary_payload(last_hmm_summary)

_PRED8_TO_FINAL = {
    # pred8이 한글/영문으로 들어오는 케이스 방어
    "중립": "N", "neutral": "N", "N": "N",
    "두려움": "F", "fear": "F", "F": "F",
    "분노": "A", "anger": "A", "A": "A",
    "기쁨": "E", "excite": "E", "excitement": "E", "E": "E",
    "놀라움": "S", "surprise": "S", "S": "S",
}

def _compact_emotion_payload_in_place(turn: Dict[str, Any]) -> None:
    """
    turn["emotion"]을 최종 감정만 남기도록 축약.
    최종 감정은 우선순위:
      1) emotion["final"]
      2) emotion["pred4"]
      3) emotion["pred8"] (한글/영문 매핑)
    결과:
      turn["emotion"] = {"final": "<code>"}
    """
    emo = turn.get("emotion")
    if not isinstance(emo, dict):
        return

    final = emo.get("final")
    if isinstance(final, str) and final.strip():
        code = final.strip()
    else:
        pred4 = emo.get("pred4")
        if isinstance(pred4, str) and pred4.strip():
            code = pred4.strip()
        else:
            pred8 = emo.get("pred8")
            if isinstance(pred8, str) and pred8.strip():
                key = pred8.strip()
                code = _PRED8_TO_FINAL.get(key, _PRED8_TO_FINAL.get(key.lower(), "N"))
            else:
                code = "N"

    # ✅ 요구사항: 최종 감정만 남김 (final: "F" 같은 형태)
    turn["emotion"] = {"final": code}

def _sanitize_pair_mode(v: Any) -> PairMode:
    s = (str(v).strip() if v is not None else "")
    if s in _PAIR_MODE_ALLOWED:
        return s  # type: ignore[return-value]
    return _default_pair_mode()

def _default_pair_mode() -> PairMode:
    """
    오케스트레이터를 안 건드리고도 pair 전략을 바꾸기 위한 기본값.
    실행 환경변수 EMOTION_PAIR_MODE로 제어:
      - none
      - prev_offender
      - prev_victim
      - thoughts
      - prev_offender+thoughts
      - prev_victim+thoughts
    """
    v = (os.getenv("EMOTION_PAIR_MODE", "prev_offender") or "").strip()
    if v in ("none", "prev_offender", "prev_victim", "thoughts", "prev_offender+thoughts", "prev_victim+thoughts"):
        return v  # type: ignore[return-value]
    return "prev_offender"

class LabelVictimEmotionsInput(BaseModel):
    """
    LangChain tool 입력이 문자열(JSON)로 들어오는 케이스까지 흡수하기 위한 args_schema.
    - 정상: {"turns":[...], ...}
    - 비정상(흔함): '{"turns":[...], ...}'  (전체가 문자열)
    - 비정상: {"turns":"{...json...}"} 또는 {"turns":"[...]"}
    - 비정상: turns 자체가 list로만 들어옴: [...]
    """
    turns: List[Dict[str, Any]] = Field(..., description="full turns list")
    enabled: bool = Field(default_factory=_default_emotion_enabled, description="감정 주입 ON/OFF (env: EMOTION_ENABLED)")
    compact: bool = Field(default_factory=_default_emotion_compact, description="감정 출력 축약 (env: EMOTION_COMPACT)")
    pair_mode: PairMode = Field(default_factory=_default_pair_mode)
    batch_size: int = 16
    max_length: int = 512
    run_hmm: bool = True
    hmm_attach: HmmAttachMode = "per_victim_turn"

    @model_validator(mode="before")
    @classmethod
    def _coerce_input(cls, data: Any) -> Any:

        # 1) 입력 전체가 문자열인 경우: '{"turns":[...]}'
        if isinstance(data, str):
            parsed = _loads_maybe_obj(data)
            if parsed is None:
                # 파싱 실패 시 최소한의 형태로 반환(여기서 에러 내기 싫으면 빈 turns)
                return {"turns": []}
            data = parsed

        # 2) 입력이 list로 바로 온 경우: [...]
        if isinstance(data, list):
            return {"turns": data}

        # 2.5) 일부 환경에서 tool_input이 {"turns": {...payload...}}로 감싸져 들어오는 경우 방어
        #      turns 자리에 payload(dict)가 통째로 들어오면 실제 turns/run_hmm/hmm_attach를 끄집어냄
        if isinstance(data, dict) and isinstance(data.get("turns"), dict) and "turns" in data["turns"]:
            inner_payload = data["turns"]
            # 외부 필드가 비어있다면 내부 payload의 값을 승격
            for k in ("pair_mode", "batch_size", "max_length", "run_hmm", "hmm_attach"):
                if k not in data and k in inner_payload:
                    data[k] = inner_payload[k]
            data["turns"] = inner_payload.get("turns", [])

        # 3) dict인데 turns가 문자열인 경우:
        #    {"turns":"{...}"} 또는 {"turns":"[...]"}
        if isinstance(data, dict) and isinstance(data.get("turns"), str):
            raw = data["turns"]
            parsed = _loads_maybe_obj(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("turns"), list):
                data["turns"] = parsed["turns"]
            elif isinstance(parsed, list):
                data["turns"] = parsed
            else:
                data["turns"] = []

        # 4) dict인데 turns가 한 번 더 감싸진 경우:
        #    {"turns": {"turns":[...]}}
        if isinstance(data, dict) and isinstance(data.get("turns"), dict):
            inner = data["turns"]
            if isinstance(inner.get("turns"), list):
                data["turns"] = inner["turns"]

        return data

@tool(
    "label_victim_emotions",
    args_schema=LabelVictimEmotionsInput,
    description="피해자 발화(turns)에 감정(pred4/pred8/probs 등)을 주입하고, 옵션에 따라 HMM(v1/v2/v3) 결과를 부착해 반환합니다.",
)
def label_victim_emotions(
    turns: Any,
    # ✅ 직접 호출(테스트/스크립트)에서도 env 변경이 반영되게 런타임에 결정
    enabled: Optional[bool] = None,
    compact: Optional[bool] = None,
    pair_mode: Optional[PairMode] = None,
    batch_size: int = 16,
    max_length: int = 512,
    run_hmm: bool = True,
    hmm_attach: HmmAttachMode = "per_victim_turn",
) -> List[Dict[str, Any]]:
    """
    대화 turns를 입력받아:
    - 피해자 발화에 감정(pred4/pred8/probs 등)을 붙여 반환
    - (옵션) 피해자 pred4 시퀀스를 HMM에 넣어 v1/v2/v3 결과를 붙여 반환

    turns의 각 원소는 최소한 다음 키 중 하나를 가져야 합니다:
    - role/speaker/actor: 'victim' / 'offender' 구분
    - text: 발화 텍스트
    """
    # ✅ 최후 방어: tool_input 파싱이 어긋나서 turns가 문자열/딕트로 들어오는 케이스를 여기서도 흡수
    if enabled is None:
        enabled = _default_emotion_enabled()
    if compact is None:
        compact = _default_emotion_compact()
    if pair_mode is None:
        pair_mode = _default_pair_mode()
    if isinstance(turns, str):
        parsed = _loads_maybe_obj(turns)
        turns = parsed if parsed is not None else []

    # turns 자리에 payload(dict)가 통째로 들어온 경우( {"turns":[...], "run_hmm":true,...} )
    if isinstance(turns, dict) and "turns" in turns:
        # enabled도 payload로 들어오면 우선
        if "enabled" in turns:
            enabled = bool(turns.get("enabled"))
        if "compact" in turns:
            compact = bool(turns.get("compact"))
        run_hmm = turns.get("run_hmm", run_hmm)
        hmm_attach = turns.get("hmm_attach", hmm_attach)
        pair_mode = _sanitize_pair_mode(turns.get("pair_mode", pair_mode))
        batch_size = turns.get("batch_size", batch_size)
        max_length = turns.get("max_length", max_length)
        turns = turns.get("turns", [])
    else:
        pair_mode = _sanitize_pair_mode(pair_mode)

    # turns 리스트 원소가 문자열(JSON)로 들어온 경우까지 정리
    if isinstance(turns, list):
        cleaned: List[Dict[str, Any]] = []
        for t in turns:
            if isinstance(t, dict):
                cleaned.append(_normalize_turn_text(t))
                continue
            if isinstance(t, str):
                pt = _loads_maybe_obj(t)
                if isinstance(pt, dict):
                    cleaned.append(_normalize_turn_text(pt))
                else:
                    cleaned.append(_normalize_turn_text({"role": "unknown", "text": t}))
                continue
            cleaned.append(_normalize_turn_text({"role": "unknown", "text": str(t)}))
        turns = cleaned
    else:
        turns = []

    # 원본 보존(길이/정렬 보장용)
    original_turns: List[Dict[str, Any]] = turns if isinstance(turns, list) else []
    original_turns = [
        _normalize_turn_text(t) if isinstance(t, dict) else _normalize_turn_text({"role": "unknown", "text": str(t)})
        for t in original_turns
    ]

    # ✅ OFF면 no-op: 감정/HMM 주입 없이 원본 그대로 반환
    if not enabled:
        return original_turns

    labeled = label_emotions_on_turns(
        turns,
        pair_mode=pair_mode,
        batch_size=batch_size,
        max_length=max_length,
        run_hmm=run_hmm,
        hmm_attach=hmm_attach,
    )

    # ✅ 반환 안정성: 항상 "전체 turns" 길이/순서 유지
    if not isinstance(labeled, list):
        return original_turns

    # ✅ 토큰 절약: EMOTION_COMPACT=1이면 감정+HMM 출력까지 같이 축약
    if compact:
        for t in labeled:
            if not isinstance(t, dict):
                continue
            role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()
            if role == "victim" and "emotion" in t:
                _compact_emotion_payload_in_place(t)
        # ✅ HMM도 함께 축약( per-turn hmm 제거 + hmm_summary 최소화 )
        if run_hmm:
            _apply_compact_hmm_in_place(labeled)


    # 1) 이상적 케이스: 길이가 같으면 그대로 사용
    if len(labeled) == len(original_turns):
        return labeled

    # 2) victim-only 반환으로 의심되는 케이스:
    #    - labeled 길이가 원본 victim 턴 수와 같으면, 그 순서대로 원본 victim 위치에 overlay
    victim_idxs = []
    for i, t in enumerate(original_turns):
        role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()
        if role == "victim":
            victim_idxs.append(i)

    if len(labeled) == len(victim_idxs):
        merged = copy.deepcopy(original_turns)
        for j, idx in enumerate(victim_idxs):
            lt = labeled[j] if isinstance(labeled[j], dict) else {}
            # victim 턴에만 덮어쓰기
            if isinstance(lt, dict):
                # ✅ 텍스트/메타 보호: 라벨 관련 필드만 overlay
                PROTECT_KEYS = {
                    "text", "dialogue", "victim_meta", "is_convinced", "thoughts",
                    "gender", "age_group",
                }
                for k, v in lt.items():
                    if k in PROTECT_KEYS:
                        continue
                    merged[idx][k] = v
        # merged에도 compact 적용(overlay 경로에서도 최종 감정만 남기도록 보장)
        if compact:
            for t in merged:
                if not isinstance(t, dict):
                    continue
                role = (t.get("role") or t.get("speaker") or t.get("actor") or "").strip().lower()
                if role == "victim" and "emotion" in t:
                    _compact_emotion_payload_in_place(t)
            # overlay 경로에서도 HMM 축약 보장
            if run_hmm:
                _apply_compact_hmm_in_place(merged)
        return merged

    # 3) 그 외: 안전하게 원본 유지(혹은 labeled가 더 길면 앞부분만 overlay 등도 가능하지만,
    #    여기선 데이터 망가뜨리지 않는 쪽 선택)
    return original_turns