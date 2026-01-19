# vp_mcp/mcp_server/utils/end_rules.py
from __future__ import annotations
import json
import re

# ── 공통 정규화 ─────────────────────────────────────────────
_ZW = r"[\u200B-\u200D\uFEFF]"
_WS = re.compile(r"\s+")
_ZW_RE = re.compile(_ZW)

def _normalize(s: str) -> str:
    s = (s or "").strip()
    s = _ZW_RE.sub("", s)          # zero-width 제거
    s = _WS.sub(" ", s)            # 연속 공백 축소
    return s

def _strip_quotes_punct(s: str) -> str:
    return s.strip(" .\"'“”’‘")

# ── 상수 ────────────────────────────────────────────────────
ATTACKER_TRIGGER_PHRASE = "여기서 마무리하겠습니다."  # 가해자(공격자) 종료 고정 문구
VICTIM_FINAL_JSON = (
    '{"is_convinced": 0, "thoughts": "(대화를 종료합니다.)", "dialogue": "대화를 종료합니다."}'
)

# 가해자 종료 트리거(관대한 매칭: 말미 구두점/따옴표 허용)
END_TRIGGERS = [
    r"여기서\s*마무리하겠습니다",      # 핵심
    r"마무리하겠습니다",               # 축약(백업)
]

# 피해자 종료 신호(실제 발화에 포함되면 가해자 종료 문구 유도)
VICTIM_END_PATTERNS = [
    r"대화를\s*종료합니다",
    r"(전화를\s*)?끊겠습니다",
    r"끊을게요",
    r"더\s*이상\s*(대화|통화)\s*원치\s*않습니다",
    r"하고\s*싶지\s*않습니다",
    r"(필요|관심)\s*없습니다",
]

# ── JSON 대사에서 dialogue만 추출 ──────────────────────────
def extract_victim_dialogue(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict):
                return str(obj.get("dialogue", "")).strip()
        except Exception:
            pass
    return t

# ── 공격자 종료 선언 감지 ───────────────────────────────────
def attacker_declared_end(text: str) -> bool:
    t = _strip_quotes_punct(_normalize(text))
    if t == ATTACKER_TRIGGER_PHRASE:
        return True
    return any(re.search(pat, t) for pat in END_TRIGGERS)

# ── 피해자 종료 의사 감지(피해자 dialogue 기준) ─────────────
def victim_declared_end(victim_text: str) -> bool:
    dlg = _strip_quotes_punct(_normalize(extract_victim_dialogue(victim_text)))
    return any(re.search(pat, dlg) for pat in VICTIM_END_PATTERNS)
