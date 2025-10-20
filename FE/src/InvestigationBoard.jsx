// src/components/InvestigationBoard.jsx
import React, { useEffect, useState, useRef, useMemo } from "react";

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
  return "알 수 없음";
};

/*== 개별 결과 블록 ==*/
function ConversationBlock({ conv, COLORS }) {
  const { run_no, round_no, phishing, evidence, risk, victim_vulnerabilities = [], guidance, prevention } = conv || {};

  const displayRound = run_no ?? round_no ?? 0;
  const riskLevel = toKoreanLevel(risk?.level);
  const riskScore = risk?.score ?? 0;
  const riskColor = getRiskColor(riskScore);
  const rationale = risk?.rationale || "근거 없음";

  return (
    <div className="border-b" style={{ borderColor: COLORS.border }}>
      {/* 헤더 */}
      <div className="p-4 border-b" style={{ borderColor: COLORS.border }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS.blurple }} />
            <h2 className="text-lg font-semibold" style={{ color: COLORS.text }}>
              {displayRound}번째 대화 분석 결과
            </h2>
          </div>
          <div className="ml-auto">
            {phishing ? (
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
        {/* 피싱 근거 */}
        <section>
          <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
            {phishing ? "피싱 성공 근거" : "피싱 실패 근거"}
          </h3>
          <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
            <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
              {evidence}
            </p>
          </div>
        </section>

        {/* 위험도 */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS.blurple }} />
              <h3 className="text-lg font-semibold" style={{ color: COLORS.text }}>
                위험도
              </h3>
            </div>
            <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: riskColor }}>
              {riskLevel} ({riskScore}점)
            </span>
          </div>

          <div className="w-full h-4 rounded-full overflow-hidden mb-2" style={{ backgroundColor: COLORS.panel }}>
            <div
              className="h-4 transition-all duration-700 ease-in-out"
              style={{ width: `${riskScore}%`, backgroundColor: riskColor }}
            />
          </div>

          <h4 className="font-medium mt-3 mb-2" style={{ color: COLORS.text }}>
            위험도 근거
          </h4>
          <p className="text-sm leading-relaxed" style={{ color: COLORS.sub }}>
            {rationale}
          </p>
        </section>

        {/* 피해자 약점 */}
        {victim_vulnerabilities.length > 0 && (
          <section>
            <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
              피해자 취약 요인
            </h3>
            <ul className="space-y-2 text-sm" style={{ color: COLORS.sub }}>
              {victim_vulnerabilities.map((v, i) => (
                <li key={i} className="leading-relaxed whitespace-pre-wrap">
                  • {v}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 가이드라인 */}
        {guidance && (
          <section>
            <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
              시뮬레이션 후 가이드라인
            </h3>
            <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
              <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
                {guidance?.data?.text || guidance?.message || "가이드라인 없음"}
              </p>
            </div>
          </section>
        )}

        {/* 예방 팁 */}
        {prevention && (
          <section>
            <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
              예방 팁
            </h3>
            <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
              <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
                {prevention?.data?.tip || prevention?.message || "예방 팁 없음"}
              </p>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/*== 로딩 스켈레톤 ==*/
function LoadingSkeleton({ index, COLORS }) {
  return (
    <div className="p-6 space-y-4 text-center">
      <span
        className="px-3 py-1 rounded-full text-xs font-semibold"
        style={{ backgroundColor: COLORS.panel, color: COLORS.text, border: `1px solid ${COLORS.border}` }}
      >
        {index + 1}번째 대화 분석 중...
      </span>
      <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-24 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="h-32 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
      <div className="text-sm opacity-70" style={{ color: COLORS.sub }}>
        분석 결과를 계산 중입니다...
      </div>
    </div>
  );
}

/*== 메인 컴포넌트 ==*/
export default function InvestigationBoard({
  COLORS: theme = COLORS,
  insightsList = [],
  delaySec = 4,
}) {
  const [visibleCount, setVisibleCount] = useState(1);
  const timerRef = useRef(null);

  // ✅ 실시간 judgement 추가 반영
  useEffect(() => {
    if (!insightsList.length) return;
    setVisibleCount(insightsList.length);
  }, [insightsList]);

  // ✅ 자동 순차 표시 (기존 틀 유지)
  useEffect(() => {
    setVisibleCount(1);
    if (timerRef.current) clearInterval(timerRef.current);
    if (insightsList.length > 1) {
      let i = 1;
      timerRef.current = setInterval(() => {
        setVisibleCount((prev) => {
          if (prev < insightsList.length) return prev + 1;
          clearInterval(timerRef.current);
          return prev;
        });
        i++;
      }, delaySec * 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [insightsList, delaySec]);

  const visibleItems = useMemo(() => insightsList.slice(0, visibleCount), [insightsList, visibleCount]);

  return (
    <div className="h-full overflow-y-auto" style={{ backgroundColor: theme.panelDark, maxHeight: "100vh" }}>
      {visibleItems.map((conv, idx) => (
        <ConversationBlock key={idx} conv={conv} COLORS={theme} />
      ))}
      {visibleCount < insightsList.length && <LoadingSkeleton index={visibleCount} COLORS={theme} />}
    </div>
  );
}


// import React, { useEffect, useState, useRef, useMemo } from "react";

// /*== 색상 토큰 ==*/
// const COLORS = {
//   bg: "#1E1F22",
//   panel: "#2B2D31",
//   panelDark: "#1a1b1e",
//   border: "#3F4147",
//   text: "#DCDDDE",
//   sub: "#B5BAC1",
//   blurple: "#5865F2",
//   success: "#57F287",
//   warn: "#FEE75C",
//   danger: "#ED4245",
//   black: "#0A0A0A",
//   white: "#FFFFFF",
// };

// /*== 유틸 ==*/
// const getRiskColor = (score) => {
//   if (score >= 75) return "#FF4D4F";
//   if (score >= 50) return "#FAAD14";
//   return "#52C41A";
// };
// const toKoreanLevel = (level) => {
//   const lv = String(level || "").toLowerCase();
//   if (lv === "high") return "높음";
//   if (lv === "medium") return "보통";
//   if (lv === "low") return "낮음";
//   return "알 수 없음";
// };

// /*== 개별 결과 블록 ==*/
// function ConversationBlock({ conv, COLORS }) {
//   const { run_no, round_no, phishing, evidence, risk, victim_vulnerabilities = [] } = conv || {};

//   const displayRound = run_no ?? round_no ?? 0;
//   const riskLevel = toKoreanLevel(risk?.level);
//   const riskScore = risk?.score ?? 0;
//   const riskColor = getRiskColor(riskScore);
//   const rationale = risk?.rationale || "근거 없음";

//   return (
//     <div className="border-b" style={{ borderColor: COLORS.border }}>
//       {/* 헤더 */}
//       <div className="p-4 border-b" style={{ borderColor: COLORS.border }}>
//         <div className="flex items-center justify-between">
//           <div className="flex items-center gap-2">
//             <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS.blurple }} />
//             <h2 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//               {displayRound}번째 대화 분석 결과
//             </h2>
//           </div>
//           <div className="ml-auto">
//             {phishing ? (
//               <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#FF4D4F" }}>
//                 피싱 방어 실패
//               </span>
//             ) : (
//               <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#52C41A" }}>
//                 피싱 방어 성공
//               </span>
//             )}
//           </div>
//         </div>
//       </div>

//       {/* 본문 */}
//       <div className="p-6 space-y-6">
//         {/* 피싱 근거 */}
//         <section>
//           <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
//             {phishing ? "피싱 성공 근거" : "피싱 실패 근거"}
//           </h3>
//           <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//             <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
//               {evidence}
//             </p>
//           </div>
//         </section>

//         {/* 위험도 */}
//         <section>
//           <div className="flex items-center justify-between mb-4">
//             <div className="flex items-center gap-2">
//               <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS.blurple }} />
//               <h3 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//                 위험도
//               </h3>
//             </div>
//             <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: riskColor }}>
//               {riskLevel} ({riskScore}점)
//             </span>
//           </div>

//           <div className="w-full h-4 rounded-full overflow-hidden mb-2" style={{ backgroundColor: COLORS.panel }}>
//             <div
//               className="h-4 transition-all duration-700 ease-in-out"
//               style={{ width: `${riskScore}%`, backgroundColor: riskColor }}
//             />
//           </div>

//           <h4 className="font-medium mt-3 mb-2" style={{ color: COLORS.text }}>
//             위험도 근거
//           </h4>
//           <p className="text-sm leading-relaxed" style={{ color: COLORS.sub }}>
//             {rationale}
//           </p>
//         </section>

//         {/* 피해자 약점 */}
//         {victim_vulnerabilities.length > 0 && (
//           <section>
//             <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
//               피해자 취약 요인
//             </h3>
//             <ul className="space-y-2 text-sm" style={{ color: COLORS.sub }}>
//               {victim_vulnerabilities.map((v, i) => (
//                 <li key={i} className="leading-relaxed whitespace-pre-wrap">
//                   • {v}
//                 </li>
//               ))}
//             </ul>
//           </section>
//         )}
//       </div>
//     </div>
//   );
// }

// /*== 로딩 스켈레톤 ==*/
// function LoadingSkeleton({ index, COLORS }) {
//   return (
//     <div className="p-6 space-y-4 text-center">
//       <span
//         className="px-3 py-1 rounded-full text-xs font-semibold"
//         style={{ backgroundColor: COLORS.panel, color: COLORS.text, border: `1px solid ${COLORS.border}` }}
//       >
//         {index + 1}번째 대화 분석 중...
//       </span>
//       <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
//       <div className="h-24 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
//       <div className="h-4 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
//       <div className="h-32 rounded animate-pulse" style={{ backgroundColor: COLORS.panel }} />
//       <div className="text-sm opacity-70" style={{ color: COLORS.sub }}>
//         분석 결과를 계산 중입니다...
//       </div>
//     </div>
//   );
// }

// /*== 메인 컴포넌트 (n회 반복 지원) ==*/
// export default function InvestigationBoard({
//   COLORS: theme = COLORS,
//   insightsList = [],
//   delaySec = 4, // 각 라운드 분석 표시 간격(초)
// }) {
//   const [visibleCount, setVisibleCount] = useState(1);
//   const timerRef = useRef(null);

//   // insightsList 변경 시 초기화
//   useEffect(() => {
//     setVisibleCount(1);
//     if (timerRef.current) clearInterval(timerRef.current);
//     if (insightsList.length > 1) {
//       let i = 1;
//       timerRef.current = setInterval(() => {
//         setVisibleCount((prev) => {
//           if (prev < insightsList.length) return prev + 1;
//           clearInterval(timerRef.current);
//           return prev;
//         });
//         i++;
//       }, delaySec * 1000);
//     }
//     return () => {
//       if (timerRef.current) clearInterval(timerRef.current);
//     };
//   }, [insightsList, delaySec]);

//   const visibleItems = useMemo(() => insightsList.slice(0, visibleCount), [insightsList, visibleCount]);

//   return (
//     <div className="h-full overflow-y-auto" style={{ backgroundColor: theme.panelDark, maxHeight: "100vh" }}>
//       {visibleItems.map((conv, idx) => (
//         <ConversationBlock key={idx} conv={conv} COLORS={theme} />
//       ))}

//       {/* 다음 라운드 대기 표시 */}
//       {visibleCount < insightsList.length && (
//         <LoadingSkeleton index={visibleCount} COLORS={theme} />
//       )}
//     </div>
//   );
// }
