// src/InvestigationBoard.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";

/*== 색상 토큰 ==*/
const COLORS = {
  bg: "#1E1F22",
  panel: "#2B2D31",
  panelDark: "#1a1b1e",
  border: "#3F4147",
  text: "#DCDDDE",
  sub: "#B5BAC1",
  blurple: "#5865F2",
  success: "#57F287",
  warn: "#FEE75C",
  danger: "#ED4245",
  black: "#0A0A0A",
  white: "#FFFFFF",
};

/*== 유틸 ==*/
const getRiskColor = (score) => {
  if (score >= 75) return "#FF4D4F";
  if (score >= 50) return "#FAAD14";
  return "#52C41A";
};
const toKoreanLevel = (level) => {
  const lv = String(level || "").toLowerCase();
  if (lv === "high") return "높음";
  if (lv === "medium") return "보통";
  if (lv === "low") return "낮음";
  return level || "알수없음";
};

/*== 첫 번째 대화 (더미) ==*/
const DIALOG1 = {
  banner: "첫번째 대화",
  judgement: {
    title: "피싱판정결과",
    isPhishing: false,
    reasonTitle: "피싱 실패 근거",
    reason:
      "송금·인출·대출 실행 등 실제 금전 이동 발화가 전혀 없습니다. 피해자가 “주민등록번호 앞자리·생년월을 알려주겠다”고 의사 표현은 했지만 실제 숫자는 말하지 않음 → [B기준] 불충족. 링크/QR 접속, 악성앱·원격제어 앱 설치/승인 등 [C기준] 없음. 지점 대표번호로 직접 확인 의사, 최종적으로 “나중에 연락”으로 종료 → [phishing=false] 근거 충족.",
  },
  risk: {
    score: 56,
    level: "medium",
    label: "위험도",
    reasonTitle: "위험도 근거",
    reasons: [
      "민감정보 제공 직전 단계까지 접근.",
      "실제 금전 이동/링크 접속/앱 설치는 없음.",
    ],
  },
  guidance: {
    title: "지침",
    categories: ["R", "D", "F"],
    reasoning:
      "'격리형 장기통제(R)' + '전문성 연출(D)' + '의심 무마(F)'를 통해 신뢰 형성과 외부 차단을 시도.",
    expected_effect:
      "공포감으로 협조 가능성 증가, 외부 확인 지연, 지시 수용성 상승.",
  },
};

/*== 두 번째 대화 (더미) ==*/
const DIALOG2 = {
  banner: "두번째 대화",
  judgement: {
    title: "피싱판정결과",
    isPhishing: true, // ✅ 방어 실패
    reasonTitle: "피싱 성공 근거",
    reason:
      "금전 이동 실행 의사 표명: “얼마를, 어디로 이체해야 하나요?” (turn 15)\n수취인·계좌 확인: “수취인명이 ‘OO안전보호센터(가명)’ 맞나요?” (turn 17)\n경고 무시 진행 문의: “고위험 거래 경고가 뜹니다. 계속 진행해야 하나요?” (turn 19)\n이체 승인 발화: “네… 이체 진행하겠습니다.” (turn 21) → A 기준 충족\n\n(참고) 직후 “입금 접수 완료”(turn 22) — 흐름상 완료 정황 일치\n기관 사칭/권위 압박 누적, 링크/앱/원격제어 요구 반복.",
  },
  risk: {
    score: 78,
    level: "high",
    label: "위험도",
    reasonTitle: "위험도 근거",
    reasons: [
      "A 기준(금전 이동) 확정.",
      "C/D 기준(디지털 접근·기관 사칭) 누적.",
      "경고 인지 후에도 진행(경고 무시 패턴).",
    ],
  },
};

/* 공통 블록 */
function ConversationBlock({ conv }) {
  const { judgement, risk, guidance } = conv || {};
  if (!judgement || !risk) return null;

  return (
    <>
      {/* 헤더 */}
      <div className="p-4 border-b" style={{ borderColor: COLORS.border }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: "#FAAD14" }} />
            <h2 className="text-lg font-semibold" style={{ color: COLORS.text }}>
              {judgement.title}
            </h2>
          </div>
          <div className="ml-auto">
            {judgement.isPhishing ? (
              <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#FF4D4F" }}>
                피싱 방어 실패
              </span>
            ) : (
              <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#52C41A" }}>
                피싱 방어 성공
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 본문 */}
      <div className="p-6 space-y-6">
        {/* 판단 근거 */}
        <section>
          <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
            {judgement.reasonTitle}
          </h3>
          <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
            <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
              {judgement.reason}
            </p>
          </div>
        </section>

        {/* 위험도 */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS.blurple }} />
              <h3 className="text-lg font-semibold" style={{ color: COLORS.text }}>
                {risk.label}
              </h3>
            </div>
            <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: getRiskColor(risk.score) }}>
              {toKoreanLevel(risk.level)} (점수 {risk.score}점)
            </span>
          </div>

          <div className="w-full h-4 rounded-full overflow-hidden mb-2" style={{ backgroundColor: COLORS.panel }}>
            <div className="h-4 transition-all" style={{ width: `${risk.score}%`, backgroundColor: getRiskColor(risk.score) }} />
          </div>
        </section>

        {/* 위험도 근거 리스트 */}
        <section>
          <h4 className="font-medium mb-2" style={{ color: COLORS.text }}>
            {risk.reasonTitle}
          </h4>
          <ul className="space-y-2 text-sm" style={{ color: COLORS.sub }}>
            {Array.isArray(risk.reasons) &&
              risk.reasons.map((r, i) => (
                <li key={i} className="leading-relaxed whitespace-pre-wrap">
                  • {r}
                </li>
              ))}
          </ul>
        </section>

        {/* 지침(선택) */}
        {guidance && (
          <section>
            <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
              {guidance.title || "지침"}
            </h3>

            {Array.isArray(guidance.categories) && guidance.categories.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {guidance.categories.map((c, idx) => (
                  <span
                    key={idx}
                    className="px-3 py-1 rounded-full text-xs font-medium"
                    style={{ backgroundColor: COLORS.border, color: COLORS.white }}
                  >
                    {c}
                  </span>
                ))}
              </div>
            )}

            {guidance.reasoning && (
              <div className="p-4 rounded-lg mb-3" style={{ backgroundColor: COLORS.panel }}>
                <h4 className="font-medium mb-2" style={{ color: COLORS.text }}>
                  의도/전략 설명
                </h4>
                <p className="text-sm leading-relaxed" style={{ color: COLORS.sub }}>
                  {guidance.reasoning}
                </p>
              </div>
            )}

            {guidance.expected_effect && (
              <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
                <h4 className="font-medium mb-2" style={{ color: COLORS.text }}>
                  예상 효과
                </h4>
                <p className="text-sm leading-relaxed" style={{ color: COLORS.sub }}>
                  {guidance.expected_effect}
                </p>
              </div>
            )}
          </section>
        )}
      </div>
    </>
  );
}

/* 로더(두 번째 대화 자리에서 기다릴 때) */
function SecondConvSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <div className="sticky top-0 z-10">
        <div
          className="flex items-center gap-3 px-4 py-2"
          style={{
            backgroundColor: COLORS.panelDark,
            borderTop: `1px solid ${COLORS.border}`,
            borderBottom: `1px solid ${COLORS.border}`,
          }}
        >
          <div className="flex-1 h-px" style={{ backgroundColor: COLORS.border }} />
          <span
            className="px-3 py-1 rounded-full text-xs font-semibold"
            style={{ backgroundColor: COLORS.panel, color: COLORS.text, border: `1px solid ${COLORS.border}` }}
          >
            두번째 대화 준비 중…
          </span>
          <div className="flex-1 h-px" style={{ backgroundColor: COLORS.border }} />
        </div>
      </div>

      <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-24 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-32 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="text-sm opacity-70" style={{ color: COLORS.sub }}>
        두번째 판정결과를 계산 중입니다…
      </div>
    </div>
  );
}

/*== 메인 컴포넌트: 두 번째 대화를 지연 렌더 ==*/
export default function InvestigationBoard({
  dataList,
  secondConvDelaySec = 5, // ✅ 두번째 판정결과 지연 (초)
}) {
  // 기본값: 첫번째 + 두번째 더미
  const list = useMemo(
    () =>
      Array.isArray(dataList) && dataList.length > 0
        ? dataList
        : [DIALOG1, DIALOG2],
    [dataList]
  );

  const [showSecond, setShowSecond] = useState(false);
  const timerRef = useRef(null);

  // 새 세션이 될 때마다(목록이 바뀔 때마다) 타이머/상태 초기화
  useEffect(() => {
    setShowSecond(false);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (list.length >= 2) {
      timerRef.current = setTimeout(() => {
        setShowSecond(true);
        timerRef.current = null;
      }, Math.max(0, secondConvDelaySec) * 1000);
    }
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [list, secondConvDelaySec]);

  return (
    <div className="h-full overflow-y-auto" style={{ backgroundColor: COLORS.panelDark, maxHeight: "100vh" }}>
      {/* 첫 번째 대화: 즉시 */}
      {list[0] && <ConversationBlock conv={list[0]} />}

      {/* 가운데 구분 배지 */}
      {list.length > 1 && (
        <div className="sticky top-0 z-10">
          <div
            className="flex items-center gap-3 px-4 py-2"
            style={{
              backgroundColor: COLORS.panelDark,
              borderTop: `1px solid ${COLORS.border}`,
              borderBottom: `1px solid ${COLORS.border}`,
            }}
          >
            <div className="flex-1 h-px" style={{ backgroundColor: COLORS.border }} />
            <span
              className="px-3 py-1 rounded-full text-xs font-semibold"
              style={{ backgroundColor: COLORS.panel, color: COLORS.text, border: `1px solid ${COLORS.border}` }}
            >
              두번째 대화
            </span>
            <div className="flex-1 h-px" style={{ backgroundColor: COLORS.border }} />
          </div>
        </div>
      )}

      {/* 두 번째 대화: ⏳ 지연 표시 */}
      {list.length > 1 && (showSecond ? <ConversationBlock conv={list[1]} /> : <SecondConvSkeleton />)}
    </div>
  );
}
