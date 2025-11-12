# run_cycle.py
from __future__ import annotations
import json
from typing import Any, Dict, List, Tuple, Optional
import argparse

from sqlalchemy import text
from app.db.session import SessionLocal
from app.db import models as m
from app.services.simulation import run_two_bot_simulation
from app.schemas.conversation import ConversationRunRequest

# ─────────────────────────────────────────────────────────
# 코드 상에 직접 정의하는 시나리오 (DB/CLI 미의존)
# ─────────────────────────────────────────────────────────
# SCENARIO: Dict[str, Any] = {
#     "name": "기관 사칭형 2",
#     "type": "기관 사칭형",
#     "purpose": "검·경을 사칭해 ‘대포통장 연루’ 혐의를 조작하고 권위·불안을 이용해 녹취조사 명목으로 개인정보와 계좌 현황을 확보한 뒤 최종적으로 자금 이동에 협조하도록 유도한다",
#     "steps": [
#         "자신과 사건 소개",
#         "가상의 사건 인물과 관련한 사건 내용 설명(가상의 사건 인물과의 관계 물어봄)",
#         "피해자 연루 설명",
#         "통화 녹음·조사 강조",
#         "은행/계좌 확인 유도",
#         "출석/추가 지시 요구",
#     ],
#     # 필요하면 지침을 여기에 추가 가능:
#     # "guideline": "긴급성·권위를 강조하고 절차 위주로 짧게 지시.",
#     # "guidance_type": "A",
# }
# SCENARIO: Dict[str, Any] = {
#     "name": "대출사기형",
#     "type": "대출사기형",
#     "purpose": "저금리 대출 안내를 통하여 개인정보 탈취 및 문자를 통한 서류 제출 유도",
#     "steps": [
#         "자신 소개와 상담 신청 명분 제시",
#         "통화 상대방이 본인인지 확인",
#         "대출 가능성 강조 및 유리한 조건 제시",
#         "개인정보 탈취 및 비대면 진행 이유 설명",
#         "문자를 통해 링크·신청서·서류 제출 유도",
#     ],
#     # 필요하면 지침을 여기에 추가 가능:
#     # "guideline": "긴급성·권위를 강조하고 절차 위주로 짧게 지시.",
#     # "guidance_type": "A",
# }
SCENARIO: Dict[str, Any] = {
    "name": "몸캠 피싱형",
    "type": "몸캠 피싱형",
    "purpose": "성매매 업소 방문 영상을 불법 촬영했으며 지인 연락처도 확보했다고 피해자를 속이고 협박하여, 영상 유포를 막는 대가로 금전적 합의를 뜯어내는 것",
    "steps": [
        "대상 확인 및 자신 소개",
        "자신의 신분과 상황을 설정",
        "사건·증거 제시(촬영·포착 사실 고지)",
        "사건·증거로 확증·협박 강화",
        "금전·추후 지시로 합의 요구",
    ],
    # 필요하면 지침을 여기에 추가 가능:
    # "guideline": "긴급성·권위를 강조하고 절차 위주로 짧게 지시.",
    # "guidance_type": "A",
}

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--cycles", type=int, default=5, help="사이클 횟수")
    p.add_argument("--max-rounds", type=int, default=15, help="각 대화의 최대 턴 수")
    p.add_argument(
        "--skip-n",
        type=int,
        default=0,
        help="이미 처리한 offender×victim 페어 개수만큼 건너뛰기 (예: 35면 36번째부터 실행)",
    )
    # 피해자 선택 옵션 (둘 다 주면 victim-id 가 우선)
    p.add_argument(
        "--victim-id", type=int, default=None,
        help="사용할 victim의 DB id (선택). 주면 해당 ID의 피해자를 사용"
    )
    p.add_argument(
        "--victim-index", type=int, default=None,
        help="활성화된 피해자 목록에서 1-based 인덱스로 선택 (예: 1 = 첫 번째 활성 피해자). victim-id 없을 때 사용"
    )
    return p.parse_args()


def run_one(
    db,
    offender: m.PhishingOffender,
    victim: m.Victim,
    *,
    case_scenario: Dict[str, Any],
    max_rounds: int,
) -> Tuple[str, int]:
    """
    하나의 시뮬레이션 케이스 실행.
    - 오펜더 DB 레코드는 필요 (req.offender_id로 조회함)
    - case_scenario는 코드 상의 SCENARIO을 사용
    """
    req = ConversationRunRequest(
        offender_id=offender.id,
        victim_id=victim.id,
        case_scenario=case_scenario,
        # 필요 시 지침을 아래처럼 case_scenario에서 끌어올 수 있음:
        # guidance={"text": case_scenario.get("guideline",""), "type": case_scenario.get("guidance_type","")},
        max_rounds=max_rounds,
        history=[],
        last_victim="",
        last_offender="",
    )
    print(f"[Scenario Source] run_cycle constant → name='{case_scenario.get('name','')}', type='{case_scenario.get('type','')}'")

    case_id, total_turns = run_two_bot_simulation(db, req)
    return str(case_id), total_turns


def main():
    args = parse_args()
    db = SessionLocal()
    try:
        # --- 연결/데이터 자가진단 ---
        row = db.execute(text("select current_database(), current_user")).fetchone()
        print("DB CHECK:", row)

        # 테이블 카운트 (존재하지 않으면 0)
        try:
            cnt_off = db.execute(text("select count(*) from phishingoffender")).scalar()
        except Exception:
            cnt_off = 0
        try:
            cnt_vic = db.execute(text("select count(*) from victim")).scalar()
        except Exception:
            cnt_vic = 0
        print(f"TABLE COUNTS => phishingoffender={cnt_off}, victim={cnt_vic}")
        # ----------------------------

        # 공격자(오펜더) 목록: 기존처럼 활성화된 모든 오펜더 사용
        # offenders: List[m.PhishingOffender] = (
        #     db.query(m.PhishingOffender)
        #     .filter(m.PhishingOffender.is_active.is_(True))
        #     .order_by(m.PhishingOffender.id)
        #     .all()
        # )
        # 필요 시 한 명만 고정해서 혼동 최소화 (예: id=1)
        offenders: List[m.PhishingOffender] = (
            db.query(m.PhishingOffender)
            .filter(m.PhishingOffender.is_active.is_(True))
            .order_by(m.PhishingOffender.id)
            .limit(1)  # ← 한 명만
            .all()
        )

        if not offenders:
            raise RuntimeError("활성화된 오펜더 데이터가 없습니다. seed를 먼저 넣어주세요.")

        # 피해자: 선택 방식
        selected_victim: Optional[m.Victim] = None
        if args.victim_id is not None:
            # id로 직접 선택 (우선)
            v = db.get(m.Victim, args.victim_id)
            if v is None:
                raise RuntimeError(f"victim id={args.victim_id} 를 찾을 수 없습니다.")
            selected_victim = v
        else:
            # 활성화된 피해자 목록에서 index 선택 (1-based) 또는 기본: 첫 번째
            victims_query = (
                db.query(m.Victim)
                .filter(m.Victim.is_active.is_(True))
                .order_by(m.Victim.id)
            )
            if args.victim_index is not None:
                idx = int(args.victim_index)
                if idx <= 0:
                    raise RuntimeError("--victim-index 는 1 이상의 정수여야 합니다.")
                # offset (idx-1)로 하나 가져오기
                victim_row = victims_query.offset(idx - 1).limit(1).one_or_none()
                if victim_row is None:
                    raise RuntimeError(f"활성화된 피해자 목록에 인덱스 {idx} 가 존재하지 않습니다.")
                selected_victim = victim_row
            else:
                # 기본: 첫 번째 활성 피해자
                victim_row = victims_query.first()
                if victim_row is None:
                    raise RuntimeError("활성화된 피해자가 없습니다. seed를 먼저 넣어주세요.")
                selected_victim = victim_row

        victims: List[m.Victim] = [selected_victim]
        # ────────────────────────────────────────────────
        # ✅ 피해자 정보 로그 출력 (터미널용 브리핑)
        print("\n=== 선택된 피해자 정보 ===")

        # 안전한 접근: profile 컬럼이 없을 수 있으므로 getattr 사용.
        # 1) 먼저 profile 전체 JSON 컬럼이 있는지 시도
        vp = getattr(selected_victim, "profile", None)
        if not vp:
            # 2) profile이 없으면 개별 컬럼(meta, knowledge, traits)을 시도
            meta = getattr(selected_victim, "meta", {}) or {}
            traits = getattr(selected_victim, "traits", {}) or {}
            knowledge = getattr(selected_victim, "knowledge", {}) or {}
        else:
            # profile이 있으면 내부 구조에서 꺼냄
            meta = vp.get("meta", {}) if isinstance(vp, dict) else {}
            traits = vp.get("traits", {}) if isinstance(vp, dict) else {}
            knowledge = vp.get("knowledge", {}) if isinstance(vp, dict) else {}

        # 출력: 안전한 기본값 사용
        print(f"이름: {getattr(selected_victim, 'name', '정보없음')}")
        print(f"나이: {meta.get('age', '?')}세,  성별: {meta.get('gender', '?')}")
        print(f"지역: {meta.get('address', '정보없음')}, 학력: {meta.get('education', '정보없음')}")

        print("\n[금융 이해 특성]")
        for note in knowledge.get("comparative_notes", []) if isinstance(knowledge, dict) else []:
            print(f" - {note}")

        print("\n[취약 성향]")
        for vn in traits.get("vulnerability_notes", []) if isinstance(traits, dict) else []:
            print(f" - {vn}")

        print("──────────────────────────────────────────\n")
        # ────────────────────────────────────────────────

        CYCLES = args.cycles
        MAX_ROUNDS = args.max_rounds
        SKIP_N = args.skip_n

        total_new = 0
        processed_global = 0
        results = []

        for cycle in range(1, CYCLES + 1):
            print(f"\n=== Cycle {cycle}/{CYCLES} 시작 ===")
            for off in offenders:
                for vic in victims:
                    # 이미 처리한 건너뛰기
                    if processed_global < SKIP_N:
                        processed_global += 1
                        continue

                    case_id, turns = run_one(
                        db,
                        off,
                        vic,
                        case_scenario=SCENARIO,
                        max_rounds=MAX_ROUNDS,
                    )
                    processed_global += 1
                    total_new += 1

                    results.append({
                        "cycle": cycle,
                        "case_id": case_id,
                        "offender_id": off.id,
                        "victim_id": vic.id,
                        "turns": turns,
                    })
                    print(f"[{processed_global}] cycle={cycle} offender={off.id} victim={vic.id} → case={case_id} turns={turns}")

        print("\n=== Batch summary ===")
        expected = len(offenders) * len(victims) * CYCLES
        print(f"이번 실행에서 새로 처리한 케이스: {total_new}")
        print(f"예상 총 케이스 수: {expected} ( {len(offenders)} x {len(victims)} x {CYCLES} )")
        if results:
            print(json.dumps(results[:5], ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
