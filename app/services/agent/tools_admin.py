# # app/services/agent/tools_admin.py

# from __future__ import annotations
# from typing import Dict, Any, Optional, List
# from uuid import UUID

# import os
# import json
# import ast
# import httpx
# import re

# from pydantic import BaseModel, Field
# from langchain_core.tools import tool
# from sqlalchemy.orm import Session
# from fastapi import HTTPException

# from app.db import models as m
# from app.core.logging import get_logger

# # (중요) 요약/판정기는 "턴 리스트(JSON)"만으로 판정하도록 설계
# # summarize_run_full(turns=List[Dict[str, Any]]) 시그니처를 권장
# # 만약 기존 summarize_run_full이 (db, case_id, run_no)만 받는다면,
# # 해당 파일도 turns 기반 시그니처로 업데이트하세요.
# from app.services.admin_summary import summarize_run_full  # turns 기반 사용 권장

# # ★ 추가: LLM 호출용
# from app.services.llm_providers import agent_chat

# logger = get_logger(__name__)

# # ─────────────────────────────────────────────────────────
# # 환경변수
# # ─────────────────────────────────────────────────────────
# MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://127.0.0.1:5177")  # 운영 시 외부 MCP 주소로 설정

# # ─────────────────────────────────────────────────────────
# # 공통: {"data": {...}} 입력 통일
# # ─────────────────────────────────────────────────────────
# class SingleData(BaseModel):
#     data: Any = Field(..., description="이 안에 실제 페이로드를 담는다")

# def _to_dict(obj: Any) -> Dict[str, Any]:
#     if hasattr(obj, "model_dump"):
#         obj = obj.model_dump()
#     if isinstance(obj, dict):
#         return obj
#     if isinstance(obj, str):
#         s = obj.strip()
#         try:
#             return json.loads(s)
#         except Exception:
#             try:
#                 return ast.literal_eval(s)
#             except Exception:
#                 raise HTTPException(status_code=422, detail="data는 JSON 객체여야 합니다.")
#     raise HTTPException(status_code=422, detail="data는 JSON 객체여야 합니다.")

# def _unwrap_data(obj: Any) -> Dict[str, Any]:
#     d = _to_dict(obj)
#     return _to_dict(d.get("data")) if "data" in d else d

# def _normalize_kind(val: Any) -> str:
#     if isinstance(val, str):
#         s = val.strip()
#         if s.startswith("{"):
#             try:
#                 parsed = json.loads(s)
#             except Exception:
#                 try:
#                     parsed = ast.literal_eval(s)
#                 except Exception:
#                     raise HTTPException(status_code=422, detail="kind 형식 오류")
#             k = parsed.get("kind") or parsed.get("type")
#             if isinstance(k, str):
#                 return k
#         return s
#     raise HTTPException(status_code=422, detail="kind는 문자열이어야 합니다.")

# # ─────────────────────────────────────────────────────────
# # 입력 스키마
# # ─────────────────────────────────────────────────────────
# class _JudgeReadInput(BaseModel):
#     case_id: UUID
#     run_no: int = Field(1, ge=1)

# class _JudgeMakeInput(BaseModel):
#     case_id: UUID
#     run_no: int = Field(1, ge=1)
#     # 오케스트레이터가 바로 턴을 넘겨줄 수 있게 허용
#     turns: Optional[List[Dict[str, Any]]] = None
#     log: Optional[Dict[str, Any]] = None

# class _GuidanceInput(BaseModel):
#     kind: str = Field(..., pattern="^(P|A)$", description="지침 종류: 'P'(피해자) | 'A'(공격자)")

# class _SavePreventionInput(BaseModel):
#     case_id: UUID
#     offender_id: int
#     victim_id: int
#     run_no: int = Field(1, ge=1)
#     summary: str
#     steps: List[str] = Field(default_factory=list)

# # ★ 추가: 최종예방책 생성 입력
# class _MakePreventionInput(BaseModel):
#     case_id: UUID
#     rounds: int = Field(..., ge=1)
#     turns: List[Dict[str, Any]] = Field(default_factory=list)
#     judgements: List[Dict[str, Any]] = Field(default_factory=list)
#     guidances: List[Dict[str, Any]] = Field(default_factory=list)
#     # 포맷은 고정적으로 personalized_prevention을 기대
#     format: str = Field("personalized_prevention")

# # ─────────────────────────────────────────────────────────
# # MCP에서 대화 턴(JSON) 가져오기
# # ─────────────────────────────────────────────────────────
# def _fetch_turns_from_mcp(case_id: UUID, run_no: int) -> List[Dict[str, Any]]:
#     """
#     MCP가 제공하는 대화로그(JSON) 엔드포인트에서 특정 라운드의 전체 턴을 받아온다.
#     기대 형식: [{"role": "attacker"|"victim"|"system", "text": "...", "meta": {...}}, ...]
#     기본 엔드포인트 가정: GET {MCP_BASE_URL}/api/cases/{case_id}/turns?run={run_no}
#     """
#     url = f"{MCP_BASE_URL}/api/cases/{case_id}/turns"
#     params = {"run": run_no}
#     try:
#         with httpx.Client(timeout=30) as client:
#             r = client.get(url, params=params)
#         r.raise_for_status()
#         data = r.json()
#     except Exception as e:
#         logger.error(f"[MCP] 대화 로그 조회 실패: {e}")
#         raise HTTPException(status_code=502, detail=f"MCP 대화로그 조회 실패: {e}")

#     # 서버 스키마에 맞게 정규화
#     turns: Any = None
#     if isinstance(data, dict):
#         # 흔한 케이스들 대응
#         if "turns" in data:
#             turns = data["turns"]
#         elif "result" in data and isinstance(data["result"], dict) and "turns" in data["result"]:
#             turns = data["result"]["turns"]
#         else:
#             # 루트에 라운드별 묶음이 있을 수도 있음: {"run":1,"turns":[...]} 등
#             if all(isinstance(v, list) for v in data.values()):
#                 # 첫 번째 리스트를 turns로 가정
#                 turns = next(iter(data.values()))
#     elif isinstance(data, list):
#         turns = data

#     if not isinstance(turns, list):
#         raise HTTPException(status_code=502, detail="MCP 응답에서 turns 배열을 찾을 수 없습니다.")
#     return turns  # type: ignore[return-value]

# # ─────────────────────────────────────────────────────────
# # 판정 결과 저장 / 조회 (DB는 결과 저장·조회에만 사용)
# # ─────────────────────────────────────────────────────────
# def _persist_verdict(
#     db: Session,
#     *,
#     case_id: UUID,
#     run_no: int,
#     verdict: Dict[str, Any],
# ) -> bool:
#     """
#     verdict 예:
#       {
#         "phishing": False,
#         "evidence": "...",
#         "risk": {"score": 10, "level": "low", "rationale": "..."},
#         "victim_vulnerabilities": [...],
#         "continue": {"recommendation": "continue", "reason": "..."}
#       }
#     """
#     success = False

#     # 1) AdminCaseSummary가 있으면 라운드별로 저장/업서트
#     try:
#         if hasattr(m, "AdminCaseSummary"):
#             Model = m.AdminCaseSummary
#             row = (
#                 db.query(Model)
#                   .filter(Model.case_id == case_id, Model.run == run_no)
#                   .first()
#             )
#             if not row:
#                 row = Model(case_id=case_id, run=run_no)
#                 db.add(row)

#             row.phishing = bool(verdict.get("phishing", False))

#             if hasattr(Model, "evidence"):
#                 setattr(row, "evidence", str(verdict.get("evidence", ""))[:4000])

#             risk = verdict.get("risk") or {}
#             if hasattr(Model, "risk_score"):
#                 setattr(row, "risk_score", int(risk.get("score", 0) or 0))
#             if hasattr(Model, "risk_level"):
#                 setattr(row, "risk_level", str(risk.get("level", "") or ""))
#             if hasattr(Model, "risk_rationale"):
#                 setattr(row, "risk_rationale", str(risk.get("rationale", "") or "")[:2000])

#             if hasattr(Model, "vulnerabilities"):
#                 setattr(row, "vulnerabilities", verdict.get("victim_vulnerabilities", []))
#             if hasattr(Model, "verdict_json"):
#                 setattr(row, "verdict_json", verdict)

#             success = True
#     except Exception as e:
#         logger.warning(f"[admin.make_judgement] AdminCaseSummary 저장/업데이트 실패: {e}")

#     # 2) 항상 AdminCase에 최신 요약 + 히스토리 라인 누적
#     try:
#         case = db.get(m.AdminCase, case_id)
#         if not case:
#             if success:
#                 db.commit()
#             return success

#         # 케이스 단위 phishing은 OR
#         case.phishing = bool(getattr(case, "phishing", False) or verdict.get("phishing", False))

#         # 최신 요약 컬럼이 존재할 경우에만 세팅(없어도 동작)
#         risk = verdict.get("risk") or {}
#         cont = verdict.get("continue") or {}

#         if hasattr(case, "last_run_no"):
#             case.last_run_no = run_no
#         if hasattr(case, "last_risk_score"):
#             case.last_risk_score = int(risk.get("score", 0) or 0)
#         if hasattr(case, "last_risk_level"):
#             case.last_risk_level = str(risk.get("level", "") or "")
#         if hasattr(case, "last_risk_rationale"):
#             case.last_risk_rationale = str(risk.get("rationale", "") or "")
#         if hasattr(case, "last_vulnerabilities"):
#             case.last_vulnerabilities = verdict.get("victim_vulnerabilities", [])
#         if hasattr(case, "last_recommendation"):
#             case.last_recommendation = str(cont.get("recommendation", "") or "")
#         if hasattr(case, "last_recommendation_reason"):
#             case.last_recommendation_reason = str(cont.get("reason", "") or "")

#         # 라운드 히스토리 라인 누적 (run 포함)
#         prev = (case.evidence or "").strip()
#         piece = json.dumps({"run": run_no, "verdict": verdict}, ensure_ascii=False)
#         case.evidence = (prev + ("\n" if prev else "") + piece)[:8000]

#         success = True
#         db.commit()
#         return success

#     except Exception as e:
#         logger.warning(f"[admin.make_judgement] AdminCase 저장 실패: {e}")
#         try:
#             db.commit()
#         except Exception:
#             pass
#         return success

# def _read_persisted_verdict(db: Session, *, case_id: UUID, run_no: int) -> Optional[Dict[str, Any]]:
#     # 1) AdminCaseSummary 우선
#     try:
#         if hasattr(m, "AdminCaseSummary"):
#             Model = m.AdminCaseSummary
#             row = (
#                 db.query(Model)
#                   .filter(Model.case_id == case_id, Model.run == run_no)
#                   .first()
#             )
#             if row:
#                 ev = ""
#                 if hasattr(row, "evidence") and getattr(row, "evidence", None):
#                     ev = row.evidence
#                 elif hasattr(row, "reason") and getattr(row, "reason", None):
#                     ev = row.reason
#                 risk = {}
#                 if hasattr(row, "risk_score"):
#                     risk["score"] = int(getattr(row, "risk_score", 0) or 0)
#                 if hasattr(row, "risk_level"):
#                     risk["level"] = getattr(row, "risk_level", None) or ""
#                 if hasattr(row, "risk_rationale"):
#                     risk["rationale"] = getattr(row, "risk_rationale", None) or ""
#                 vul = []
#                 if hasattr(row, "vulnerabilities") and getattr(row, "vulnerabilities", None):
#                     vul = list(row.vulnerabilities or [])
#                 # verdict_json이 있으면 우선
#                 if hasattr(row, "verdict_json") and getattr(row, "verdict_json", None):
#                     vj = dict(row.verdict_json or {})
#                     # 최소 필드 보장
#                     vj.setdefault("evidence", ev)
#                     vj.setdefault("risk", risk or {"score": 0, "level": "", "rationale": ""})
#                     vj.setdefault("victim_vulnerabilities", vul)
#                     vj.setdefault("phishing", bool(getattr(row, "phishing", False)))
#                     vj.setdefault("continue", {"recommendation":"continue","reason":""})
#                     return vj
#                 # 없으면 조립
#                 return {
#                     "phishing": bool(getattr(row, "phishing", False)),
#                     "evidence": ev,
#                     "risk": risk or {"score": 0, "level": "", "rationale": ""},
#                     "victim_vulnerabilities": vul,
#                     "continue": {"recommendation":"continue","reason":""},
#                 }
#     except Exception:
#         pass

#     # 2) Fallback: AdminCase.evidence에서 run별 JSON 찾기
#     try:
#         case = db.get(m.AdminCase, case_id)
#         raw = (getattr(case, "evidence", "") or "")
#         for line in raw.splitlines():
#             try:
#                 obj = json.loads(line)
#                 if int(obj.get("run", -1)) == run_no and isinstance(obj.get("verdict"), dict):
#                     return obj["verdict"]
#             except Exception:
#                 continue
#     except Exception:
#         pass
#     return None

# # ─────────────────────────────────────────────────────────
# # LLM 결과 파싱 보조
# # ─────────────────────────────────────────────────────────
# def _safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
#     """코드펜스/설명 섞여도 JSON만 뽑아 파싱 시도."""
#     text = text.strip()
#     # ```json ... ``` 제거
#     fence = re.compile(r"^```(?:json)?\s*(\{.*\})\s*```$", re.S)
#     m = fence.match(text)
#     if m:
#         text = m.group(1).strip()
#     # 최외곽 { ... } 추출
#     if not (text.startswith("{") and text.endswith("}")):
#         m2 = re.search(r"\{.*\}$", text, re.S)
#         if m2:
#             text = m2.group(0)
#     try:
#         return json.loads(text)
#     except Exception:
#         try:
#             obj = ast.literal_eval(text)
#             if isinstance(obj, dict):
#                 return obj
#         except Exception:
#             return None

# # ─────────────────────────────────────────────────────────
# # 툴 팩토리
# # ─────────────────────────────────────────────────────────
# def make_admin_tools(db: Session, guideline_repo):
#     @tool(
#         "admin.make_judgement",
#         args_schema=SingleData,
#         description="(case_id, run_no)의 전체 대화를 MCP JSON 또는 전달받은 turns로 판정한다. DB는 결과 저장에만 사용한다."
#     )
#     def make_judgement(data: Any) -> Dict[str, Any]:
#         payload = _unwrap_data(data)
#         try:
#             ji = _JudgeMakeInput(**payload)
#         except Exception as e:
#             raise HTTPException(status_code=422, detail=f"JudgeMakeInput 검증 실패: {e}")

#         # 1) Action Input으로 턴이 오면 그대로 사용
#         turns: Optional[List[Dict[str, Any]]] = ji.turns

#         # 2) 없으면 MCP에서 가져오기 (DB 접근 금지)
#         if turns is None and ji.log and isinstance(ji.log, dict):
#             maybe = ji.log.get("turns")
#             if isinstance(maybe, list):
#                 turns = maybe
#         if turns is None:
#             turns = _fetch_turns_from_mcp(ji.case_id, ji.run_no)

#         # 3) 턴 기반 요약/판정 (admin_summary.summarize_run_full은 turns를 받아야 함)
#         try:
#             verdict = summarize_run_full(turns=turns)  # <- turns-only
#         except TypeError as te:
#             # 만약 summarize_run_full이 아직 옛 시그니처라면, 에러를 명확히 알림
#             logger.error("[admin.make_judgement] summarize_run_full가 turns 기반 시그니처를 지원해야 합니다.")
#             raise HTTPException(
#                 status_code=500,
#                 detail="summarize_run_full이 'turns' 인자를 지원하도록 업데이트해 주세요."
#             ) from te

#         # ── 정책 오버라이드: critical일 때만 stop, 그 외는 continue ──
#         risk = verdict.get("risk") or {}
#         score = int(risk.get("score", 0) or 0)
#         score = 0 if score < 0 else (100 if score > 100 else score)
#         risk["score"] = score

#         level = str((risk.get("level") or "").lower())
#         if level not in {"low", "medium", "high", "critical"}:
#             level = ("critical" if score >= 75 else
#                      "high"     if score >= 50 else
#                      "medium"   if score >= 25 else
#                      "low")
#         risk["level"] = level
#         verdict["risk"] = risk

#         if level == "critical":
#             verdict["continue"] = {
#                 "recommendation": "stop",
#                 "reason": "위험도가 critical로 판정되어 시뮬레이션을 종료합니다."
#             }
#         else:
#             verdict["continue"] = {
#                 "recommendation": "continue",
#                 "reason": "위험도가 critical이 아니므로 다음 라운드를 진행합니다."
#             }
#         # ───────────────────────────────────────────────

#         persisted = _persist_verdict(db, case_id=ji.case_id, run_no=ji.run_no, verdict=verdict)

#         return {
#             "ok": True,
#             "persisted": persisted,
#             "case_id": str(ji.case_id),
#             "run_no": ji.run_no,
#             **verdict,
#         }

#     @tool(
#         "admin.judge",
#         args_schema=SingleData,
#         description="(case_id, run_no)의 **저장된 판정**을 조회한다. 저장된 결과가 없으면 '없음'을 알려준다."
#     )
#     def judge(data: Any) -> Dict[str, Any]:
#         payload = _unwrap_data(data)
#         try:
#             ji = _JudgeReadInput(**payload)
#         except Exception as e:
#             raise HTTPException(status_code=422, detail=f"JudgeInput 검증 실패: {e}")

#         saved = _read_persisted_verdict(db, case_id=ji.case_id, run_no=ji.run_no)
#         if saved is not None:
#             out = {
#                 "phishing": bool(saved.get("phishing", False)),
#                 "reason": str(saved.get("evidence", "")),  # 기존 호환
#                 "run_no": ji.run_no,
#                 # 신규 필드도 함께
#                 "evidence": saved.get("evidence", ""),
#                 "risk": saved.get("risk", {"score": 0, "level": "", "rationale": ""}),
#                 "victim_vulnerabilities": saved.get("victim_vulnerabilities", []),
#                 "continue": saved.get("continue", {"recommendation": "continue", "reason": ""}),
#             }
#             return out

#         # 레거시 폴백 제거: DB 로그 요약으로 판단하지 않음
#         return {
#             "ok": False,
#             "case_id": str(ji.case_id),
#             "run_no": ji.run_no,
#             "message": "저장된 라운드 판정이 없습니다. admin.make_judgement를 먼저 호출하세요."
#         }

#     @tool(
#         "admin.pick_guidance",
#         args_schema=SingleData,
#         description="상황에 맞는 지침을 선택한다. Action Input은 {'data': {'kind': 'P'|'A'}}"
#     )
#     def pick_guidance(data: Any) -> Dict[str, str]:
#         payload = _unwrap_data(data)
#         if "kind" not in payload:
#             raise HTTPException(status_code=422, detail="kind 누락")
#         kind = _normalize_kind(payload["kind"])
#         try:
#             gi = _GuidanceInput(kind=kind)
#         except Exception as e:
#             raise HTTPException(status_code=422, detail=f"GuidanceInput 검증 실패: {e}")

#         if gi.kind == "P":
#             text, title = guideline_repo.pick_preventive()
#         else:
#             text, title = guideline_repo.pick_attack()
#         return {"type": gi.kind, "title": title, "text": text}

#     # ★ 신규: 최종예방책 생성
#     @tool(
#         "admin.make_prevention",
#         args_schema=SingleData,
#         description=(
#             "대화(turns)+판단(judgements)+지침(guidances)로 최종 예방책(personalized_prevention) JSON을 생성한다. "
#             "Action Input 예: {'data': {'case_id':UUID,'rounds':int,'turns':[...],'judgements':[...],'guidances':[...],'format':'personalized_prevention'}}"
#         )
#     )
#     def make_prevention(data: Any) -> Dict[str, Any]:
#         payload = _unwrap_data(data)
#         try:
#             pi = _MakePreventionInput(**payload)
#         except Exception as e:
#             raise HTTPException(status_code=422, detail=f"MakePreventionInput 검증 실패: {e}")

#         llm = agent_chat(temperature=0.2)

#         # 스키마 힌트
#         schema_hint = {
#             "personalized_prevention": {
#                 "summary": "string (2~3문장)",
#                 "analysis": {
#                     "outcome": "success|fail",
#                     "reasons": ["string", "string", "string"],
#                     "risk_level": "low|medium|high"
#                 },
#                 "steps": ["명령형 한국어 단계 5~9개"],
#                 "tips": ["체크리스트형 팁 3~6개"]
#             }
#         }

#         system = (
#             "너는 보이스피싱 예방 전문가다. 입력된 대화/판단/지침을 바탕으로, "
#             "아래 스키마에 맞춘 JSON만 출력하라. 한국어로 간결하고 실용적으로 작성하라. "
#             "코드블럭/주석/설명 금지. 오직 JSON 한 개만 반환."
#         )
#         user = {
#             "case_id": str(pi.case_id),
#             "rounds": pi.rounds,
#             "guidances": pi.guidances,
#             "judgements": pi.judgements,
#             "turns": pi.turns,
#             "format": pi.format,
#             "schema": schema_hint
#         }

#         messages = [
#             ("system", system),
#             ("human",
#              "다음 입력을 바탕으로 'personalized_prevention' 키 하나만 있는 JSON을 출력하라.\n"
#              + json.dumps(user, ensure_ascii=False))
#         ]

#         try:
#             res = llm.invoke(messages)
#             text = getattr(res, "content", str(res))
#             parsed = _safe_json_parse(text) or {}
#             if "personalized_prevention" not in parsed:
#                 return {
#                     "ok": False,
#                     "error": "missing_key_personalized_prevention",
#                     "raw": text[:1200]
#                 }
#             return {
#                 "ok": True,
#                 "case_id": str(pi.case_id),
#                 "personalized_prevention": parsed["personalized_prevention"]
#             }
#         except Exception as e:
#             return {"ok": False, "error": f"llm_error: {e!s}"}

#     @tool(
#         "admin.save_prevention",
#         args_schema=SingleData,
#         description="개인화된 예방책을 DB에 저장한다. {'data': {'case_id':UUID,'offender_id':int,'victim_id':int,'run_no':int,'summary':str,'steps':[str,...]}}"
#     )
#     def save_prevention(data: Any) -> str:
#         payload = _unwrap_data(data)
#         try:
#             spi = _SavePreventionInput(**payload)
#         except Exception as e:
#             raise HTTPException(status_code=422, detail=f"SavePreventionInput 검증 실패: {e}")

#         obj = m.PersonalizedPrevention(
#             case_id=spi.case_id,
#             offender_id=spi.offender_id,
#             victim_id=spi.victim_id,
#             run=spi.run_no,
#             content={"summary": spi.summary, "steps": spi.steps},
#             note="agent-generated",
#             is_active=True,
#         )
#         db.add(obj)
#         db.commit()
#         return str(obj.id)

#     # 기존 + 신규 툴 모두 반환
#     return [make_judgement, judge, pick_guidance, make_prevention, save_prevention]


# app/services/agent/tools_admin.py

from __future__ import annotations
from typing import Dict, Any, Optional, List
from uuid import UUID

import os
import json
import ast
import httpx
import re

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.db import models as m
from app.core.logging import get_logger

# (중요) 요약/판정기는 "턴 리스트(JSON)"만으로 판정하도록 설계
# summarize_run_full(turns=List[Dict[str, Any]]) 시그니처를 권장
# 만약 기존 summarize_run_full이 (db, case_id, run_no)만 받는다면,
# 해당 파일도 turns 기반 시그니처로 업데이트하세요.
from app.services.admin_summary import summarize_run_full  # turns 기반 사용 권장

# ★ 추가: LLM 호출용
from app.services.llm_providers import agent_chat

# ★★ 추가: 동적 지침 생성기(2안)
from app.services.agent.guidance_generator import DynamicGuidanceGenerator

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────────────────────
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://127.0.0.1:5177")  # 운영 시 외부 MCP 주소로 설정

# ─────────────────────────────────────────────────────────
# 공통: {"data": {...}} 입력 통일
# ─────────────────────────────────────────────────────────
class SingleData(BaseModel):
    data: Any = Field(..., description="이 안에 실제 페이로드를 담는다")

def _to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        s = obj.strip()
        try:
            return json.loads(s)
        except Exception:
            try:
                return ast.literal_eval(s)
            except Exception:
                raise HTTPException(status_code=422, detail="data는 JSON 객체여야 합니다.")
    raise HTTPException(status_code=422, detail="data는 JSON 객체여야 합니다.")

def _unwrap_data(obj: Any) -> Dict[str, Any]:
    d = _to_dict(obj)
    return _to_dict(d.get("data")) if "data" in d else d

def _normalize_kind(val: Any) -> str:
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("{"):
            try:
                parsed = json.loads(s)
            except Exception:
                try:
                    parsed = ast.literal_eval(s)
                except Exception:
                    raise HTTPException(status_code=422, detail="kind 형식 오류")
            k = parsed.get("kind") or parsed.get("type")
            if isinstance(k, str):
                return k
        return s
    raise HTTPException(status_code=422, detail="kind는 문자열이어야 합니다.")

# ─────────────────────────────────────────────────────────
# 입력 스키마
# ─────────────────────────────────────────────────────────
class _JudgeReadInput(BaseModel):
    case_id: UUID
    run_no: int = Field(1, ge=1)

class _JudgeMakeInput(BaseModel):
    case_id: UUID
    run_no: int = Field(1, ge=1)
    # 오케스트레이터가 바로 턴을 넘겨줄 수 있게 허용
    turns: Optional[List[Dict[str, Any]]] = None
    log: Optional[Dict[str, Any]] = None

class _GuidanceInput(BaseModel):
    kind: str = Field(..., pattern="^(P|A)$", description="지침 종류: 'P'(피해자) | 'A'(공격자)")

class _SavePreventionInput(BaseModel):
    case_id: UUID
    offender_id: int
    victim_id: int
    run_no: int = Field(1, ge=1)
    summary: str
    steps: List[str] = Field(default_factory=list)

# ★ 추가: 최종예방책 생성 입력
class _MakePreventionInput(BaseModel):
    case_id: UUID
    rounds: int = Field(..., ge=1)
    turns: List[Dict[str, Any]] = Field(default_factory=list)
    judgements: List[Dict[str, Any]] = Field(default_factory=list)
    guidances: List[Dict[str, Any]] = Field(default_factory=list)
    # 포맷은 고정적으로 personalized_prevention을 기대
    format: str = Field("personalized_prevention")

# ─────────────────────────────────────────────────────────
# MCP에서 대화 턴(JSON) 가져오기
# ─────────────────────────────────────────────────────────
def _fetch_turns_from_mcp(case_id: UUID, run_no: int) -> List[Dict[str, Any]]:
    """
    MCP가 제공하는 대화로그(JSON) 엔드포인트에서 특정 라운드의 전체 턴을 받아온다.
    기대 형식: [{"role": "attacker"|"victim"|"system", "text": "...", "meta": {...}}, ...]
    기본 엔드포인트 가정: GET {MCP_BASE_URL}/api/cases/{case_id}/turns?run={run_no}
    """
    # url = f"{MCP_BASE_URL}/api/cases/{case_id}/turns}"
    url = f"{MCP_BASE_URL}/api/cases/{case_id}/turns"  # 안전하게 재정의
    params = {"run": run_no}
    try:
        with httpx.Client(timeout=30) as client:
            r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"[MCP] 대화 로그 조회 실패: {e}")
        raise HTTPException(status_code=502, detail=f"MCP 대화로그 조회 실패: {e}")

    # 서버 스키마에 맞게 정규화
    turns: Any = None
    if isinstance(data, dict):
        if "turns" in data:
            turns = data["turns"]
        elif "result" in data and isinstance(data["result"], dict) and "turns" in data["result"]:
            turns = data["result"]["turns"]
        else:
            if all(isinstance(v, list) for v in data.values()):
                turns = next(iter(data.values()))
    elif isinstance(data, list):
        turns = data

    if not isinstance(turns, list):
        raise HTTPException(status_code=502, detail="MCP 응답에서 turns 배열을 찾을 수 없습니다.")
    return turns  # type: ignore[return-value]

# ─────────────────────────────────────────────────────────
# 판정 결과 저장 / 조회 (DB는 결과 저장·조회에만 사용)
# ─────────────────────────────────────────────────────────
def _persist_verdict(
    db: Session,
    *,
    case_id: UUID,
    run_no: int,
    verdict: Dict[str, Any],
) -> bool:
    """
    verdict 예:
      {
        "phishing": False,
        "evidence": "...",
        "risk": {"score": 10, "level": "low", "rationale": "..."},
        "victim_vulnerabilities": [...],
        "continue": {"recommendation": "continue", "reason": "..."}
      }
    """
    success = False

    # 1) AdminCaseSummary가 있으면 라운드별로 저장/업서트
    try:
        if hasattr(m, "AdminCaseSummary"):
            Model = m.AdminCaseSummary
            row = (
                db.query(Model)
                  .filter(Model.case_id == case_id, Model.run == run_no)
                  .first()
            )
            if not row:
                row = Model(case_id=case_id, run=run_no)
                db.add(row)

            row.phishing = bool(verdict.get("phishing", False))

            if hasattr(Model, "evidence"):
                setattr(row, "evidence", str(verdict.get("evidence", ""))[:4000])

            risk = verdict.get("risk") or {}
            if hasattr(Model, "risk_score"):
                setattr(row, "risk_score", int(risk.get("score", 0) or 0))
            if hasattr(Model, "risk_level"):
                setattr(row, "risk_level", str(risk.get("level", "") or ""))
            if hasattr(Model, "risk_rationale"):
                setattr(row, "risk_rationale", str(risk.get("rationale", "") or "")[:2000])

            if hasattr(Model, "vulnerabilities"):
                setattr(row, "vulnerabilities", verdict.get("victim_vulnerabilities", []))
            if hasattr(Model, "verdict_json"):
                setattr(row, "verdict_json", verdict)

            success = True
    except Exception as e:
        logger.warning(f"[admin.make_judgement] AdminCaseSummary 저장/업데이트 실패: {e}")

    # 2) 항상 AdminCase에 최신 요약 + 히스토리 라인 누적
    try:
        case = db.get(m.AdminCase, case_id)
        if not case:
            if success:
                db.commit()
            return success

        # 케이스 단위 phishing은 OR
        case.phishing = bool(getattr(case, "phishing", False) or verdict.get("phishing", False))

        # 최신 요약 컬럼이 존재할 경우에만 세팅(없어도 동작)
        risk = verdict.get("risk") or {}
        cont = verdict.get("continue") or {}

        if hasattr(case, "last_run_no"):
            case.last_run_no = run_no
        if hasattr(case, "last_risk_score"):
            case.last_risk_score = int(risk.get("score", 0) or 0)
        if hasattr(case, "last_risk_level"):
            case.last_risk_level = str(risk.get("level", "") or "")
        if hasattr(case, "last_risk_rationale"):
            case.last_risk_rationale = str(risk.get("rationale", "") or "")
        if hasattr(case, "last_vulnerabilities"):
            case.last_vulnerabilities = verdict.get("victim_vulnerabilities", [])
        if hasattr(case, "last_recommendation"):
            case.last_recommendation = str(cont.get("recommendation", "") or "")
        if hasattr(case, "last_recommendation_reason"):
            case.last_recommendation_reason = str(cont.get("reason", "") or "")

        # 라운드 히스토리 라인 누적 (run 포함)
        prev = (case.evidence or "").strip()
        piece = json.dumps({"run": run_no, "verdict": verdict}, ensure_ascii=False)
        case.evidence = (prev + ("\n" if prev else "") + piece)[:8000]

        success = True
        db.commit()
        return success

    except Exception as e:
        logger.warning(f"[admin.make_judgement] AdminCase 저장 실패: {e}")
        try:
            db.commit()
        except Exception:
            pass
        return success

def _read_persisted_verdict(db: Session, *, case_id: UUID, run_no: int) -> Optional[Dict[str, Any]]:
    # 1) AdminCaseSummary 우선
    try:
        if hasattr(m, "AdminCaseSummary"):
            Model = m.AdminCaseSummary
            row = (
                db.query(Model)
                  .filter(Model.case_id == case_id, Model.run == run_no)
                  .first()
            )
            if row:
                ev = ""
                if hasattr(row, "evidence") and getattr(row, "evidence", None):
                    ev = row.evidence
                elif hasattr(row, "reason") and getattr(row, "reason", None):
                    ev = row.reason
                risk = {}
                if hasattr(row, "risk_score"):
                    risk["score"] = int(getattr(row, "risk_score", 0) or 0)
                if hasattr(row, "risk_level"):
                    risk["level"] = getattr(row, "risk_level", None) or ""
                if hasattr(row, "risk_rationale"):
                    risk["rationale"] = getattr(row, "risk_rationale", None) or ""
                vul = []
                if hasattr(row, "vulnerabilities") and getattr(row, "vulnerabilities", None):
                    vul = list(row.vulnerabilities or [])
                # verdict_json이 있으면 우선
                if hasattr(row, "verdict_json") and getattr(row, "verdict_json", None):
                    vj = dict(row.verdict_json or {})
                    # 최소 필드 보장
                    vj.setdefault("evidence", ev)
                    vj.setdefault("risk", risk or {"score": 0, "level": "", "rationale": ""})
                    vj.setdefault("victim_vulnerabilities", vul)
                    vj.setdefault("phishing", bool(getattr(row, "phishing", False)))
                    vj.setdefault("continue", {"recommendation":"continue","reason":""})
                    return vj
                # 없으면 조립
                return {
                    "phishing": bool(getattr(row, "phishing", False)),
                    "evidence": ev,
                    "risk": risk or {"score": 0, "level": "", "rationale": ""},
                    "victim_vulnerabilities": vul,
                    "continue": {"recommendation":"continue","reason":""},
                }
    except Exception:
        pass

    # 2) Fallback: AdminCase.evidence에서 run별 JSON 찾기
    try:
        case = db.get(m.AdminCase, case_id)
        raw = (getattr(case, "evidence", "") or "")
        for line in raw.splitlines():
            try:
                obj = json.loads(line)
                if int(obj.get("run", -1)) == run_no and isinstance(obj.get("verdict"), dict):
                    return obj["verdict"]
            except Exception:
                continue
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────
# LLM 결과 파싱 보조
# ─────────────────────────────────────────────────────────
def _safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """코드펜스/설명 섞여도 JSON만 뽑아 파싱 시도."""
    text = text.strip()
    fence = re.compile(r"^```(?:json)?\s*(\{.*\})\s*```$", re.S)
    m = fence.match(text)
    if m:
        text = m.group(1).strip()
    if not (text.startswith("{") and text.endswith("}")):
        m2 = re.search(r"\{.*\}$", text, re.S)
        if m2:
            text = m2.group(0)
    try:
        return json.loads(text)
    except Exception:
        try:
            obj = ast.literal_eval(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None

# ─────────────────────────────────────────────────────────
# 툴 팩토리
# ─────────────────────────────────────────────────────────
def make_admin_tools(db: Session, guideline_repo):
    # ★ 동적 지침 생성기 인스턴스 (2안)
    dynamic_generator = DynamicGuidanceGenerator()

    @tool(
        "admin.make_judgement",
        args_schema=SingleData,
        description="(case_id, run_no)의 전체 대화를 MCP JSON 또는 전달받은 turns로 판정한다. DB는 결과 저장에만 사용한다."
    )
    def make_judgement(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        try:
            ji = _JudgeMakeInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"JudgeMakeInput 검증 실패: {e}")

        # 1) Action Input으로 턴이 오면 그대로 사용
        turns: Optional[List[Dict[str, Any]]] = ji.turns

        # 2) 없으면 MCP에서 가져오기 (DB 접근 금지)
        if turns is None and ji.log and isinstance(ji.log, dict):
            maybe = ji.log.get("turns")
            if isinstance(maybe, list):
                turns = maybe
        if turns is None:
            turns = _fetch_turns_from_mcp(ji.case_id, ji.run_no)

        # 3) 턴 기반 요약/판정 (admin_summary.summarize_run_full은 turns를 받아야 함)
        try:
            verdict = summarize_run_full(turns=turns)  # <- turns-only
        except TypeError as te:
            logger.error("[admin.make_judgement] summarize_run_full가 turns 기반 시그니처를 지원해야 합니다.")
            raise HTTPException(
                status_code=500,
                detail="summarize_run_full이 'turns' 인자를 지원하도록 업데이트해 주세요."
            ) from te

        # ── 정책 오버라이드: critical일 때만 stop, 그 외는 continue ──
        risk = verdict.get("risk") or {}
        score = int(risk.get("score", 0) or 0)
        score = 0 if score < 0 else (100 if score > 100 else score)
        risk["score"] = score

        level = str((risk.get("level") or "").lower())
        if level not in {"low", "medium", "high", "critical"}:
            level = ("critical" if score >= 75 else
                     "high"     if score >= 50 else
                     "medium"   if score >= 25 else
                     "low")
        risk["level"] = level
        verdict["risk"] = risk

        if level == "critical":
            verdict["continue"] = {
                "recommendation": "stop",
                "reason": "위험도가 critical로 판정되어 시뮬레이션을 종료합니다."
            }
        else:
            verdict["continue"] = {
                "recommendation": "continue",
                "reason": "위험도가 critical이 아니므로 다음 라운드를 진행합니다."
            }

        persisted = _persist_verdict(db, case_id=ji.case_id, run_no=ji.run_no, verdict=verdict)

        return {
            "ok": True,
            "persisted": persisted,
            "case_id": str(ji.case_id),
            "run_no": ji.run_no,
            **verdict,
        }

    @tool(
        "admin.judge",
        args_schema=SingleData,
        description="(case_id, run_no)의 **저장된 판정**을 조회한다. 저장된 결과가 없으면 '없음'을 알려준다."
    )
    def judge(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        try:
            ji = _JudgeReadInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"JudgeInput 검증 실패: {e}")

        saved = _read_persisted_verdict(db, case_id=ji.case_id, run_no=ji.run_no)
        if saved is not None:
            out = {
                "phishing": bool(saved.get("phishing", False)),
                "reason": str(saved.get("evidence", "")),  # 기존 호환
                "run_no": ji.run_no,
                # 신규 필드도 함께
                "evidence": saved.get("evidence", ""),
                "risk": saved.get("risk", {"score": 0, "level": "", "rationale": ""}),
                "victim_vulnerabilities": saved.get("victim_vulnerabilities", []),
                "continue": saved.get("continue", {"recommendation": "continue", "reason": ""}),
            }
            return out

        return {
            "ok": False,
            "case_id": str(ji.case_id),
            "run_no": ji.run_no,
            "message": "저장된 라운드 판정이 없습니다. admin.make_judgement를 먼저 호출하세요."
        }


    # ★★ 신규(2안): 동적 공격 지침 생성 - DynamicGuidanceGenerator 사용
    @tool(
        "admin.generate_guidance",
        args_schema=SingleData,
        description=(
            "판정결과(위험도/취약점/피싱여부/근거) + (선택) 시나리오/피해자/이전판정을 바탕으로 "
            "공격자용 맞춤 지침을 생성한다. 예: {'data': {'case_id':UUID,'run_no':int,"
            "'scenario':{...},'victim_profile':{...},'previous_judgements':[...]} }"
        )
    )
    def generate_guidance(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        case_id = payload.get("case_id")
        run_no = int(payload.get("run_no") or payload.get("round_no") or 1)
        
        try:
            case_uuid = UUID(str(case_id))
        except Exception:
            return {"ok": False, "error": "invalid_case_id", "message": "case_id must be UUID"}

        # 1) 저장된 판정 확보(V1 캐시)
        verdict = _read_persisted_verdict(db, case_id=case_uuid, run_no=run_no)
        if not verdict:
            return {"ok": False, "error": "no_saved_verdict", "message": "admin.make_judgement 이후 호출하세요."}

        # 2) 선택 컨텍스트
        scenario = payload.get("scenario") or {}
        victim_profile = payload.get("victim_profile") or {}
        previous_judgements = payload.get("previous_judgements") or []

        # 3) 동적 지침 생성기 호출
        try:
            result = dynamic_generator.generate_guidance(
                db=db,
                case_id=str(case_uuid),
                round_no=run_no,
                scenario=scenario,
                victim_profile=victim_profile,
                previous_judgments=previous_judgements,
                verdict=verdict,  # ★ 판정 결과 전달 (risk/vulns/evidence/phishing 활용)
            )
        except Exception as e:
            logger.exception("[admin.generate_guidance] 실패")
            return {"ok": False, "error": f"generator_failed: {e!s}"}

        # 4) 표준화된 응답
        return {
            "ok": True,
            "type": "A",
            "text": result.get("guidance_text", ""),
            "categories": result.get("selected_categories", []),
            "reasoning": result.get("reasoning", ""),
            "expected_effect": result.get("expected_effect", ""),
            "risk_level": (verdict.get("risk") or {}).get("level", ""),
            "targets": verdict.get("victim_vulnerabilities", []),
            "source": "dynamic_generator+verdict"
        }

    # ★ 신규: 최종예방책 생성
    @tool(
        "admin.make_prevention",
        args_schema=SingleData,
        description=(
            "대화(turns)+판단(judgements)+지침(guidances)로 최종 예방책(personalized_prevention) JSON을 생성한다. "
            "Action Input 예: {'data': {'case_id':UUID,'rounds':int,'turns':[...],'judgements':[...],'guidances':[...],'format':'personalized_prevention'}}"
        )
    )
    def make_prevention(data: Any) -> Dict[str, Any]:
        payload = _unwrap_data(data)
        try:
            pi = _MakePreventionInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"MakePreventionInput 검증 실패: {e}")

        llm = agent_chat(temperature=0.2)

        # 스키마 힌트
        schema_hint = {
            "personalized_prevention": {
                "summary": "string (2~3문장)",
                "analysis": {
                    "outcome": "success|fail",
                    "reasons": ["string", "string", "string"],
                    "risk_level": "low|medium|high"
                },
                "steps": ["명령형 한국어 단계 5~9개"],
                "tips": ["체크리스트형 팁 3~6개"]
            }
        }

        system = (
            "너는 보이스피싱 예방 전문가다. 입력된 대화/판단/지침을 바탕으로, "
            "아래 스키마에 맞춘 JSON만 출력하라. 한국어로 간결하고 실용적으로 작성하라. "
            "코드블럭/주석/설명 금지. 오직 JSON 한 개만 반환."
        )
        user = {
            "case_id": str(pi.case_id),
            "rounds": pi.rounds,
            "guidances": pi.guidances,
            "judgements": pi.judgements,
            "turns": pi.turns,
            "format": pi.format,
            "schema": schema_hint
        }

        messages = [
            ("system", system),
            ("human",
             "다음 입력을 바탕으로 'personalized_prevention' 키 하나만 있는 JSON을 출력하라.\n"
             + json.dumps(user, ensure_ascii=False))
        ]

        try:
            res = llm.invoke(messages)
            text = getattr(res, "content", str(res))
            parsed = _safe_json_parse(text) or {}
            if "personalized_prevention" not in parsed:
                return {
                    "ok": False,
                    "error": "missing_key_personalized_prevention",
                    "raw": text[:1200]
                }
            return {
                "ok": True,
                "case_id": str(pi.case_id),
                "personalized_prevention": parsed["personalized_prevention"]
            }
        except Exception as e:
            return {"ok": False, "error": f"llm_error: {e!s}"}

    @tool(
        "admin.save_prevention",
        args_schema=SingleData,
        description="개인화된 예방책을 DB에 저장한다. {'data': {'case_id':UUID,'offender_id':int,'victim_id':int,'run_no':int,'summary':str,'steps':[str,...]}}"
    )
    def save_prevention(data: Any) -> str:
        payload = _unwrap_data(data)
        try:
            spi = _SavePreventionInput(**payload)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"SavePreventionInput 검증 실패: {e}")

        obj = m.PersonalizedPrevention(
            case_id=spi.case_id,
            offender_id=spi.offender_id,
            victim_id=spi.victim_id,
            run=spi.run_no,
            content={"summary": spi.summary, "steps": spi.steps},
            note="agent-generated",
            is_active=True,
        )
        db.add(obj)
        db.commit()
        return str(obj.id)

    # 기존 + 신규 툴 모두 반환 (★ generate_guidance 추가됨)
    return [make_judgement, judge, generate_guidance, make_prevention, save_prevention]
