# app/routers/victim.py
import re
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.utils.deps import get_db
from app.db import models as m

router = APIRouter(tags=["victims"])


# ------------------------------------------------------------------
# 설정: OCEAN 순서/처리 규칙 (프론트와 계약)
# - 프론트가 보낼 ocean dict 키는 자유지만, 일반적으로 아래 키를 사용합니다.
# - 또는 프론트가 순서 배열을 보내도 처리하도록 map_ocean_by_order 지원.
# ------------------------------------------------------------------
OCEAN_ORDER = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]


def map_ocean_by_order(levels: List[str]) -> Dict[str, str]:
    """프론트가 순서 배열로 보냈을 때 매핑 (예: ['높음','낮음',...])"""
    out: Dict[str, str] = {}
    for i, trait in enumerate(OCEAN_ORDER):
        if i < len(levels):
            out[trait] = levels[i]
    return out


# 취약성 요약: 한 문장 생성
SAFE_CONDITIONS = {
    "neuroticism": "낮음",
    "openness": "높음",
    "agreeableness": "높음",
    "conscientiousness": "높음",
}
KR_LABEL = {
    "openness": "개방성",
    "conscientiousness": "성실성",
    "extraversion": "외향성",
    "agreeableness": "친화성",
    "neuroticism": "신경성",
}


def _level_stem(level_text: str) -> str:
    """'높음' -> '높', '낮음' -> '낮' (문장 어간 생성)"""
    if not level_text:
        return ""
    t = level_text.strip()
    if t.startswith("높"):
        return "높"
    if t.startswith("낮"):
        return "낮"
    return t[0]


def make_vulnerability_note_one_line(ocean: Dict[str, str]) -> str:
    """
    ocean: {'openness':'높음', ...}
    반환: 한 줄 요약 문장 (요청 포맷)
    """
    safe_pairs: List[tuple[str, str]] = []
    risk_pairs: List[tuple[str, str]] = []

    for k, v in ocean.items():
        label = KR_LABEL.get(k, k)
        if SAFE_CONDITIONS.get(k) == v:
            safe_pairs.append((label, v))
        else:
            risk_pairs.append((label, v))

    def join_pairs(pairs: List[tuple[str, str]]) -> str:
        if not pairs:
            return ""
        bits: List[str] = []
        for idx, (lab, lv) in enumerate(pairs):
            stem = _level_stem(lv)
            ending = "아" if idx == len(pairs) - 1 else "고"
            bits.append(f"{lab}이 {stem}{ending}")
        return " ".join(bits)

    safe_text = join_pairs(safe_pairs)
    risk_text = join_pairs(risk_pairs)

    if safe_text and risk_text:
        return f"{safe_text} 보이스피싱에 안전한 면이 있지만 {risk_text} 보이스피싱에 취약한 면도 있다"
    if safe_text:
        return f"{safe_text} 보이스피싱에 안전한 면이 있다"
    if risk_text:
        return f"{risk_text} 보이스피싱에 취약한 면이 있다"
    return ""


# ------------------------------------------------------------------
# 헬퍼: 프론트 페이로드(임의 구조)를 정규화하여 DB에 넣을 dict 형태로 반환
# 프론트가 보내는 예시 구조를 모두 지원하도록 우선순위 규칙을 둠.
# ------------------------------------------------------------------
def normalize_victim_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    입력(payload) 예측:
    - name (str)
    - meta (dict)  -- optional
    - knowledge (dict)  -- may include 'digital_finance_literacy' (list) or 'comparative_notes'
    - traits (dict)  -- may include 'ocean' dict with keys OR be absent
    - 또는: checklist_lines (list of str) and ocean_levels (list of '높음'/'낮음')
    - 기타: note, photo_path, is_active
    """
    out_meta = payload.get("meta", {}) or {}
    # --- comparative_notes (우선순위) ---
    comparative_notes: List[str] = []

    # 1) checklist_lines (프론트가 체크된 문장 리스트로 보낼 때)
    checklist = payload.get("checklist_lines")
    if isinstance(checklist, list) and checklist:
        comparative_notes = [str(x).strip() for x in checklist if x and str(x).strip()]
    else:
        # 2) knowledge.digital_finance_literacy
        knowledge = payload.get("knowledge") or {}
        if isinstance(knowledge, dict):
            dfl = knowledge.get("digital_finance_literacy")
            if isinstance(dfl, list) and dfl:
                comparative_notes = [str(x).strip() for x in dfl if x and str(x).strip()]
            else:
                # 3) knowledge.comparative_notes
                cn = knowledge.get("comparative_notes")
                if isinstance(cn, list) and cn:
                    comparative_notes = [str(x).strip() for x in cn if x and str(x).strip()]
                else:
                    comparative_notes = []

    # --- competencies (존재하면 그대로, 아니면 빈 리스트) ---
    competencies = []
    if isinstance(payload.get("knowledge"), dict):
        competencies = payload["knowledge"].get("competencies", []) or []
        if not isinstance(competencies, list):
            competencies = []

    knowledge_out = {
        "comparative_notes": comparative_notes,
        "competencies": competencies,
    }

    # --- traits.ocean: 우선순위: 1) payload.traits.ocean (dict) 2) payload.ocean_levels (list 배열) 3) fallback empty ---
    ocean: Dict[str, str] = {}
    traits_in = payload.get("traits") or {}
    if isinstance(traits_in, dict) and isinstance(traits_in.get("ocean"), dict) and traits_in.get("ocean"):
        # 프론트가 {'ocean': {'openness':'높음', ...}} 형태로 보냄
        # accept only known keys, keep original values
        for k in OCEAN_ORDER:
            if k in traits_in["ocean"]:
                ocean[k] = traits_in["ocean"][k]
    else:
        # 프론트가 순서 배열로 보냈다면 (예: ocean_levels)
        ol = payload.get("ocean_levels")
        if isinstance(ol, list) and ol:
            ocean = map_ocean_by_order([str(x) for x in ol])

    # If still empty, try to extract from traits->ocean-like keys in top-level (tolerant)
    if not ocean and isinstance(traits_in, dict):
        for k in OCEAN_ORDER:
            if k in traits_in:
                ocean[k] = traits_in[k]

    # 방어: 없으면 빈 dict
    if not ocean:
        ocean = {}

    # --- vulnerability note (한 줄) ---
    vulnerability_note = make_vulnerability_note_one_line(ocean) if ocean else ""
    vulnerability_notes_out = [vulnerability_note] if vulnerability_note else []

    traits_out = {
        "ocean": ocean,
        "vulnerability_notes": vulnerability_notes_out,
    }

    # --- meta normalization: keep fields if present, otherwise leave empty ---
    meta_out = {
        "age": out_meta.get("age"),
        "education": out_meta.get("education"),
        "gender": out_meta.get("gender"),
        "address": out_meta.get("address"),
    }

    # final normalized object to save
    normalized = {
        "name": payload.get("name"),
        "meta": meta_out,
        "knowledge": knowledge_out,
        "traits": traits_out,
        "photo_path": payload.get("photo_path"),
        "is_active": payload.get("is_active", True),
        "note": payload.get("note"),
    }
    return normalized


# ------------------------------------------------------------------
# 엔드포인트: 프론트가 보내는 "있는 그대로" JSON 받기 — 검증을 관대하게 함
# - URL은 예시에서 사용하신 "/api/make/offenders/" 형식과 달리 victims 엔드포인트입니다.
# - 프론트가 보내는 페이로드를 그대로 저장하고, DB에서 생성된 row를 반환합니다.
# ------------------------------------------------------------------
@router.post("/make/victims/")
async def create_victim_flexible(request: Request, db: Session = Depends(get_db)):
    """
    프론트가 보내는 JSON을 그대로 받아 정규화 후 저장합니다.
    (요청 바디 예시는 대화 중에 주신 샘플을 따릅니다.)
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 기본적인 필수 확인
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="Field 'name' is required")

    normalized = normalize_victim_payload(payload)

    # DB 저장: m.Victim 모델이 meta/knowledge/traits를 JSON(JSONB)으로 지원해야 함
    obj = m.Victim(
        name=normalized["name"],
        meta=normalized["meta"],
        knowledge=normalized["knowledge"],
        traits=normalized["traits"],
        photo_path=normalized.get("photo_path"),
        is_active=normalized.get("is_active", True),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    # 반환: DB 엔티티(ORM 객체)를 dict 형태로 반환 (FastAPI가 자동 JSON화)
    # 필요하면 반환 스키마를 맞춰 변경하세요.
    return {
        "id": getattr(obj, "id", None),
        "name": obj.name,
        "meta": obj.meta,
        "knowledge": obj.knowledge,
        "traits": obj.traits,
        "photo_path": obj.photo_path,
        "is_active": obj.is_active,
    }


# ------------------------------------------------------------------
# 간단 조회 엔드포인트들 (기존과 비슷하게 유지)
# ------------------------------------------------------------------
@router.get("/victims/")
def get_victims(db: Session = Depends(get_db)):
    rows = db.query(m.Victim).all()
    # 간단 직렬화
    return [
        {
            "id": r.id,
            "name": r.name,
            "meta": r.meta,
            "knowledge": r.knowledge,
            "traits": r.traits,
            "photo_path": r.photo_path,
            "is_active": r.is_active,
        }
        for r in rows
    ]


@router.get("/victims/{victim_id}")
def get_victim(victim_id: int, db: Session = Depends(get_db)):
    r = db.get(m.Victim, victim_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Victim not found")
    return {
        "id": r.id,
        "name": r.name,
        "meta": r.meta,
        "knowledge": r.knowledge,
        "traits": r.traits,
        "photo_path": r.photo_path,
        "is_active": r.is_active,
    }
