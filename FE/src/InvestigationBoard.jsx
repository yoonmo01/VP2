// src/components/InvestigationBoard.jsx
import React from "react";
import { Shield, Target, Lightbulb, TrendingUp } from "lucide-react";

/*== 색상 토큰 ==*/
const DEFAULT_THEME = {
  bg: "#030617",
  panel: "#061329",
  panelDark: "#04101f",
  border: "#A8862A",
  text: "#FFFFFF",
  sub: "#BFB38A",
  blurple: "#A8862A",
  success: "#10B981",
  warn: "#F59E0B",
  danger: "#EF4444",
  purple: "#A855F7",
  cyan: "#06B6D4",
};

/* ============================================================
   1) 🔵 핵심: 모든 judgement/guidance/prevention 구조를 통일
===============================================================*/
function normalizeRound(obj) {
  if (!obj) return null;

  const content = obj.content ?? obj.event?.content ?? {};
  const meta = obj.meta ?? obj.raw ?? {};

  const round_no =
    content.run_no ??
    meta.round_no ??
    obj.run_no ??
    obj.round ??
    obj.meta?.round_no ??
    null;

  return {
    ...obj,
    ...meta,
    ...content,
    round_no,
  };
}

/*== 위험도 스타일 ==*/
const getRiskStyle = (level) => {
  const lv = String(level || "").toLowerCase();
  if (lv === "critical") return { color: "#EF4444", label: "치명적", bg: "#EF444420" };
  if (lv === "high") return { color: "#F59E0B", label: "높음", bg: "#F59E0B20" };
  if (lv === "medium") return { color: "#06B6D4", label: "보통", bg: "#06B6D420" };
  if (lv === "low") return { color: "#10B981", label: "낮음", bg: "#10B98120" };
  return { color: "#6B7280", label: "알 수 없음", bg: "#6B728020" };
};

/*== 섹션 카드 ==*/
function Section({ icon: Icon, title, color, children, badge }) {
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={18} color={color} />
          <h3 className="text-sm font-semibold" style={{ color: "#FFFFFF" }}>
            {title}
          </h3>
        </div>
        {badge}
      </div>
      {children}
    </div>
  );
}

/*== RoundBlock ==*/
function RoundBlock({ conv, theme }) {
  if (!conv) return null;

  const {
    run_no,
    phishing,
    evidence,
    risk,
    victim_vulnerabilities = [],
  } = conv;

  const riskStyle = getRiskStyle(risk?.level);
  const riskScore = risk?.score ?? 0;

  return (
    <div
      className="rounded-xl p-6 mb-6"
      style={{ backgroundColor: theme.panel, border: `1px solid ${theme.border}` }}
    >
      {/* 헤더 */}
      <div
        className="flex items-center justify-between mb-6 pb-4"
        style={{ borderBottom: `1px solid ${theme.border}40` }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold"
            style={{ backgroundColor: theme.blurple, color: "#000" }}
          >
            {run_no}
          </div>
          <span className="font-semibold" style={{ color: theme.text }}>
            라운드 {run_no}
          </span>
        </div>

        <div
          className="px-4 py-1.5 rounded-full text-xs font-bold"
          style={{
            backgroundColor: phishing ? "#EF444420" : "#10B98120",
            color: phishing ? "#EF4444" : "#10B981",
            border: `1px solid ${phishing ? "#EF4444" : "#10B981"}`,
          }}
        >
          {phishing ? "피싱 성공" : "피싱 실패"}
        </div>
      </div>

      {/* 피싱 판정 */}
      <Section icon={Shield} title="피싱 판정 결과" color={theme.blurple}>
        <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
          {evidence || "근거 없음"}
        </p>
      </Section>

      {/* 위험도 */}
      {risk && (
        <Section
          icon={TrendingUp}
          title="위험도"
          color={riskStyle.color}
          badge={
            <div className="flex items-center gap-2">
              <span
                className="px-3 py-1 rounded-full text-xs font-bold"
                style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
              >
                {riskStyle.label}
              </span>
              <span
                className="px-3 py-1 rounded-full text-xs font-mono font-bold"
                style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
              >
                {riskScore}점
              </span>
            </div>
          }
        >
          <div className="space-y-3">
            <div
              className="w-full h-2 rounded-full overflow-hidden"
              style={{ backgroundColor: theme.panelDark }}
            >
              <div
                className="h-2 transition-all duration-1000"
                style={{ width: `${riskScore}%`, backgroundColor: riskStyle.color }}
              />
            </div>
            <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
              {risk?.rationale}
            </p>
          </div>
        </Section>
      )}
    </div>
  );
}

/*== GuidanceBlock ==*/
function GuidanceBlock({ guidance, theme }) {
  if (!guidance) return null;

  const text = guidance.text ?? guidance.content;
  const categories = guidance.categories ?? [];
  const reasoning = guidance.reasoning;
  const expected_effect = guidance.expected_effect;

  const TOOLTIP_MAP = {
    A: "어휘/어조 조절: 피해자 수준에 맞는 언어 사용",
    B: "긴급성 강조: 시간 압박을 통한 판단력 흐림",
    C: "감정적 접근: 두려움, 책임감, 걱정 자극",
    D: "전문성 연출: 용어, 절차, 공식성 강조",
    E: "점진적 요구: 단계별 정보 수집 전략",
    F: "의심 무마: 보안 우려 해소, 정당성 강조",
    G: "사칭 다변화: 인물/기관 변경으로 신뢰성 증대",
    H: "수법 복합화: 여러 피싱 기법 조합 활용",
    I: "심리적 압박: 위협, 협박을 통한 강제성",
    J: "격리 및 통제: 외부 접촉 차단, 물리적/심리적 고립 유도",
    K: "카드배송-검사사칭 연계형: 카드기사 사칭 → 가짜센터 연결 → 원격제어 앱 유도",
    L: "납치빙자형 극단적 공포: 가족 음성 모방 + 협박으로 즉시 송금 유도",
    M: "홈캠 해킹 협박형: 사생활 노출 위협 + 개인정보 활용",
    N: "공신력 기관 사칭: 정부·시청·군부대 등 명분으로 선입금 유도",
    O: "가족사칭 정보수집: 비밀번호 설정 도움 명목으로 정보 탈취",
    P: "허위계약서 작성유도: 검사 사칭 → 계약서로 해제 유도",
    Q: "국세청 사칭 세무협박: 세금 미납·포탈 위협으로 송금 유도",
    R: "격리형 장기통제: 보호조사 명목으로 고립 및 통제",
    S: "권위 편향 활용: 금융기관/전문가 신분으로 신뢰 유도",
    T: "손실 회피 심리: 채무 해결/금리 인하 제시로 절박함 자극",
    U: "희소성 효과 조성: ‘오늘만’ 등으로 즉흥 결정 유도",
    V: "휴리스틱 의존 악용: 익숙한 절차·패턴으로 의심 차단",
    W: "2차 피해 암시: 비협조 시 추가 피해 암시로 압박",
  };

  return (
    <div
      className="rounded-xl p-6 mb-10"
      style={{ backgroundColor: theme.panelDark, border: `1px solid ${theme.border}` }}
    >
      <Section icon={Lightbulb} title="공격 지침 (Guidance)" color={theme.purple}>
        <div className="space-y-3">
          {categories.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {categories.map((cat, i) => (
                <span
                  key={i}
                  className="relative group px-2 py-1 rounded text-xs font-mono font-bold"
                  style={{
                    backgroundColor: "#A855F720",
                    color: theme.purple,
                    border: `1px solid #A855F740`,
                  }}
                >
                  {cat}
                  <div
                    className="absolute hidden group-hover:block bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 rounded text-[11px]"
                    style={{
                      backgroundColor: theme.panel,
                      color: theme.text,
                      border: `1px solid ${theme.border}`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {TOOLTIP_MAP[cat]}
                  </div>
                </span>
              ))}
            </div>
          )}

          <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
            {text}
          </p>

          {reasoning && (
            <div
              className="p-3 rounded-lg"
              style={{
                backgroundColor: theme.panel,
                borderLeft: `2px solid ${theme.cyan}`,
              }}
            >
              <div className="text-xs mb-1" style={{ color: theme.cyan }}>
                추론 과정
              </div>
              <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
                {reasoning}
              </p>
            </div>
          )}

          {expected_effect && (
            <div
              className="p-3 rounded-lg"
              style={{
                backgroundColor: theme.panel,
                borderLeft: `2px solid ${theme.success}`,
              }}
            >
              <div className="text-xs mb-1" style={{ color: theme.success }}>
                예상 효과
              </div>
              <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
                {expected_effect}
              </p>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

/* ============================================================
   ⭐ 메인 InvestigationBoard
===============================================================*/
export default function InvestigationBoard({
  COLORS,
  judgements = [],
  guidances = [],
  preventions = [],
}) {
  const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };

  // 🔵 모든 raw 데이터를 normalize(라운드 번호 통일)
  const J = judgements.map(normalizeRound);
  const G = guidances.map(normalizeRound);
  const P = preventions.map(normalizeRound);

  const rounds = [];

  J.forEach((j) => {
    if (!j.round_no) return;

    rounds.push({
      round_no: j.round_no,
      judgement: j,
      guidance: G.find((g) => g.round_no === j.round_no),
      prevention: P.find((p) => p.round_no === j.round_no),
    });
  });

  rounds.sort((a, b) => a.round_no - b.round_no);

  return (
    <div className="h-full overflow-y-auto p-6" style={{ backgroundColor: theme.bg }}>
      {rounds.map((r, idx) => (
        <div key={`round-${idx}`}>
          <RoundBlock conv={r.judgement} theme={theme} />
          {r.guidance && (
            <GuidanceBlock guidance={r.guidance} theme={theme} />
          )}
        </div>
      ))}
    </div>
  );
}

// // src/components/InvestigationBoard.jsx
// import React, { useEffect, useState, useMemo } from "react";
// import { Shield, Target, Lightbulb, TrendingUp } from "lucide-react";

// /*== 색상 토큰 ==*/
// const DEFAULT_THEME = {
//   bg: "#030617",
//   panel: "#061329",
//   panelDark: "#04101f",
//   border: "#A8862A",
//   text: "#FFFFFF",
//   sub: "#BFB38A",
//   blurple: "#A8862A",
//   success: "#10B981",
//   warn: "#F59E0B",
//   danger: "#EF4444",
//   purple: "#A855F7",
//   cyan: "#06B6D4",
// };

// /*== 위험도 스타일 ==*/
// const getRiskStyle = (level) => {
//   const lv = String(level || "").toLowerCase();
//   if (lv === "critical") return { color: "#EF4444", label: "치명적", bg: "#EF444420" };
//   if (lv === "high") return { color: "#F59E0B", label: "높음", bg: "#F59E0B20" };
//   if (lv === "medium") return { color: "#06B6D4", label: "보통", bg: "#06B6D420" };
//   if (lv === "low") return { color: "#10B981", label: "낮음", bg: "#10B98120" };
//   return { color: "#6B7280", label: "알 수 없음", bg: "#6B728020" };
// };

// /*== 섹션 카드 ==*/
// function Section({ icon: Icon, title, color, children, badge }) {
//   return (
//     <div className="mb-6">
//       <div className="flex items-center justify-between mb-3">
//         <div className="flex items-center gap-2">
//           <Icon size={18} color={color} />
//           <h3 className="text-sm font-semibold" style={{ color: "#FFFFFF" }}>
//             {title}
//           </h3>
//         </div>
//         {badge}
//       </div>
//       {children}
//     </div>
//   );
// }

// /*== 라운드별 피싱 판정 블록 ==*/
// // function RoundBlock({ conv, theme }) {
// //   const { run_no, phishing, evidence, risk, victim_vulnerabilities = [] } = conv || {};
// //   const riskStyle = getRiskStyle(risk?.level);
// //   const riskScore = risk?.score ?? 0;

// //   return (
// //     <div
// //       className="rounded-xl p-6 mb-6"
// //       style={{
// //         backgroundColor: theme.panel,
// //         border: `1px solid ${theme.border}`,
// //       }}
// //     >
// //       {/* 헤더 */}
// //       <div
// //         className="flex items-center justify-between mb-6 pb-4"
// //         style={{ borderBottom: `1px solid ${theme.border}40` }}
// //       >
// //         <div className="flex items-center gap-3">
// //           <div
// //             className="w-8 h-8 rounded-lg flex items-center justify-center font-bold"
// //             style={{ backgroundColor: theme.blurple, color: "#000" }}
// //           >
// //             {run_no}
// //           </div>
// //           <span className="font-semibold" style={{ color: theme.text }}>
// //             라운드 {run_no}
// //           </span>
// //         </div>

// //         <div
// //           className="px-4 py-1.5 rounded-full text-xs font-bold"
// //           style={{
// //             backgroundColor: phishing ? "#EF444420" : "#10B98120",
// //             color: phishing ? "#EF4444" : "#10B981",
// //             border: `1px solid ${phishing ? "#EF4444" : "#10B981"}`,
// //           }}
// //         >
// //           {phishing ? "피싱 성공" : "피싱 실패"}
// //         </div>
// //       </div>

// //       {/* 피싱 판정 결과 */}
// //       <Section icon={Shield} title="피싱 판정 결과" color={theme.blurple}>
// //         <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
// //           {evidence || "근거 없음"}
// //         </p>
// //       </Section>

// //       {/* 위험도 */}
// //       {risk && (
// //         <Section
// //           icon={TrendingUp}
// //           title="위험도"
// //           color={riskStyle.color}
// //           badge={
// //             <div className="flex items-center gap-2">
// //               <span
// //                 className="px-3 py-1 rounded-full text-xs font-bold"
// //                 style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
// //               >
// //                 {riskStyle.label}
// //               </span>
// //               <span
// //                 className="px-3 py-1 rounded-full text-xs font-mono font-bold"
// //                 style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
// //               >
// //                 {riskScore}점
// //               </span>
// //             </div>
// //           }
// //         >
// //           <div className="space-y-3">
// //             <div
// //               className="w-full h-2 rounded-full overflow-hidden"
// //               style={{ backgroundColor: theme.panelDark }}
// //             >
// //               <div
// //                 className="h-2 transition-all duration-1000"
// //                 style={{ width: `${riskScore}%`, backgroundColor: riskStyle.color }}
// //               />
// //             </div>
// //             <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
// //               {risk.rationale}
// //             </p>
// //           </div>
// //         </Section>
// //       )}

// //       {/* 취약 요인 */}
// //       {victim_vulnerabilities.length > 0 && (
// //         <Section
// //           icon={Target}
// //           title="피해자 취약 요인"
// //           color={theme.warn}
// //           badge={
// //             <span
// //               className="px-2 py-0.5 rounded text-xs font-bold"
// //               style={{ backgroundColor: "#F59E0B20", color: theme.warn }}
// //             >
// //               {victim_vulnerabilities.length}
// //             </span>
// //           }
// //         >
// //           <div className="space-y-2">
// //             {victim_vulnerabilities.map((v, i) => (
// //               <div key={i} className="flex gap-3">
// //                 <span
// //                   className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0 text-xs font-bold"
// //                   style={{ backgroundColor: "#F59E0B20", color: theme.warn }}
// //                 >
// //                   {i + 1}
// //                 </span>
// //                 <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
// //                   {v}
// //                 </p>
// //               </div>
// //             ))}
// //           </div>
// //         </Section>
// //       )}
// //     </div>
// //   );
// // }

// /*== 라운드별 GuidanceGeneration 블록 ==*/
// function GuidanceBlock({ guidance, theme }) {
//   if (!guidance) return null;

//   // ✅ 문자열 content + 객체형 병합 보정
//   const normalized = guidance?.content
//     ? { text: guidance.content, ...guidance }
//     : guidance || {};

//   const guidanceText = normalized.text;
//   const categories = normalized.categories || [];
//   const reasoning = normalized.reasoning;
//   const expectedEffect = normalized.expected_effect;

//   return (
//     <div
//       className="rounded-xl p-6 mb-10"
//       style={{
//         backgroundColor: theme.panelDark,
//         border: `1px solid ${theme.border}`,
//       }}
//     >
//       <Section icon={Lightbulb} title="공격 지침 (GuidanceGeneration)" color={theme.purple}>
//         <div className="space-y-3">
//           {/* 카테고리 */}
//           {categories.length > 0 && (
//             <div className="flex flex-wrap gap-2 mb-3">
//               {categories.map((cat, i) => (
//                 <span
//                   key={i}
//                   className="px-2 py-1 rounded text-xs font-mono font-bold"
//                   style={{
//                     backgroundColor: "#A855F720",
//                     color: theme.purple,
//                     border: `1px solid #A855F740`,
//                   }}
//                 >
//                   {cat}
//                 </span>
//               ))}
//             </div>
//           )}

//           {/* 본문 */}
//           <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
//             {guidanceText}
//           </p>

//           {/* 추론 */}
//           {reasoning && (
//             <div
//               className="p-3 rounded-lg"
//               style={{
//                 backgroundColor: theme.panel,
//                 borderLeft: `2px solid ${theme.cyan}`,
//               }}
//             >
//               <div className="text-xs mb-1 font-medium" style={{ color: theme.cyan }}>
//                 추론 과정
//               </div>
//               <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
//                 {reasoning}
//               </p>
//             </div>
//           )}

//           {/* 예상 효과 */}
//           {expectedEffect && (
//             <div
//               className="p-3 rounded-lg"
//               style={{
//                 backgroundColor: theme.panel,
//                 borderLeft: `2px solid ${theme.success}`,
//               }}
//             >
//               <div className="text-xs mb-1 font-medium" style={{ color: theme.success }}>
//                 예상 효과
//               </div>
//               <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
//                 {expectedEffect}
//               </p>
//             </div>
//           )}
//         </div>
//       </Section>
//     </div>
//   );
// }

// /*== 메인 컴포넌트 ==*/
// export default function InvestigationBoard({ COLORS, judgement, guidance, prevention }) {
//   const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };
//   const [roundData, setRoundData] = useState([]);

//   const mergeRoundData = (type, data) => {
//     const runNo = data?.run_no ?? data?.meta?.round_no ?? 1;
//     setRoundData((prev) => {
//       const existing = prev.find((r) => r.run_no === runNo) || { run_no: runNo };
//       const updated = {
//         ...existing,
//         run_no: runNo,
//         phishing: data?.phishing ?? data?.content?.phishing ?? existing.phishing,
//         evidence: data?.evidence ?? data?.content?.evidence ?? existing.evidence,
//         risk: data?.risk ?? data?.content?.risk ?? existing.risk,
//         victim_vulnerabilities:
//           data?.victim_vulnerabilities ??
//           data?.content?.victim_vulnerabilities ??
//           existing.victim_vulnerabilities ??
//           [],
//         guidance: type === "guidance" ? data : existing.guidance,
//         prevention: type === "prevention" ? data : existing.prevention,
//       };
//       const newList = prev.filter((r) => r.run_no !== runNo).concat(updated);
//       return newList.sort((a, b) => (a.run_no ?? 0) - (b.run_no ?? 0));
//     });
//   };

//   useEffect(() => {
//     if (judgement) {
//       const data = judgement.content || judgement;
//       mergeRoundData("judgement", data);
//     }
//   }, [judgement]);

//   // ✅ guidance 전체 객체 병합 (content만 쓰지 않음)
//   useEffect(() => {
//     if (guidance) {
//       const runNo =
//         guidance?.meta?.round_no ??
//         guidance?.run_no ??
//         (roundData.length > 0 ? roundData[roundData.length - 1].run_no + 1 : 1);
//       mergeRoundData("guidance", { ...guidance, run_no: runNo });
//     }
//   }, [guidance]);

//   useEffect(() => {
//     if (prevention) {
//       const data = prevention.content || prevention;
//       mergeRoundData("prevention", data);
//     }
//   }, [prevention]);

//   return (
//     <div className="h-full overflow-y-auto p-6" style={{ backgroundColor: theme.bg }}>
//       {roundData.length > 0 ? (
//         <>
//           <div className="mb-6">
//             <h1 className="text-xl font-bold mb-1" style={{ color: theme.text }}>
//               피싱 판정 결과
//             </h1>
//             <p className="text-sm" style={{ color: theme.sub }}>
//               총 {roundData.length}개 라운드 분석 완료
//             </p>
//           </div>

//           {roundData.map((conv, idx) => (
//             <div key={idx}>
//               <RoundBlock conv={conv} theme={theme} />
//               <GuidanceBlock guidance={conv.guidance} theme={theme} />
//             </div>
//           ))}
//         </>
//       ) : (
//         <div className="flex flex-col items-center justify-center h-full gap-3">
//           <Shield size={48} color={theme.blurple} className="animate-pulse" />
//           <div className="text-center">
//             <p className="font-medium mb-1" style={{ color: theme.text }}>
//               분석 데이터 대기 중
//             </p>
//             <p className="text-sm" style={{ color: theme.sub }}>
//               시뮬레이션 결과가 표시됩니다
//             </p>
//           </div>
//         </div>
//       )}
//     </div>
//   );
// }

// import React, { useEffect, useState, useMemo } from "react";
// import { Shield, AlertTriangle, Target, Lightbulb, TrendingUp } from "lucide-react";

// /*== 색상 토큰 ==*/
// const DEFAULT_THEME = {
//   bg: "#030617",
//   panel: "#061329",
//   panelDark: "#04101f",
//   border: "#A8862A",
//   text: "#FFFFFF",
//   sub: "#BFB38A",
//   blurple: "#A8862A",
//   success: "#10B981",
//   warn: "#F59E0B",
//   danger: "#EF4444",
//   purple: "#A855F7",
//   cyan: "#06B6D4",
// };

// /*== 위험도 스타일 ==*/
// const getRiskStyle = (level) => {
//   const lv = String(level || "").toLowerCase();
//   if (lv === "critical") return { color: "#EF4444", label: "치명적", bg: "#EF444420" };
//   if (lv === "high") return { color: "#F59E0B", label: "높음", bg: "#F59E0B20" };
//   if (lv === "medium") return { color: "#06B6D4", label: "보통", bg: "#06B6D420" };
//   if (lv === "low") return { color: "#10B981", label: "낮음", bg: "#10B98120" };
//   return { color: "#6B7280", label: "알 수 없음", bg: "#6B728020" };
// };

// /*== 섹션 카드 ==*/
// function Section({ icon: Icon, title, color, children, badge }) {
//   return (
//     <div className="mb-6">
//       <div className="flex items-center justify-between mb-3">
//         <div className="flex items-center gap-2">
//           <Icon size={18} color={color} />
//           <h3 className="text-sm font-semibold" style={{ color: "#FFFFFF" }}>
//             {title}
//           </h3>
//         </div>
//         {badge}
//       </div>
//       {children}
//     </div>
//   );
// }

// /*== 개별 라운드 ==*/
// function RoundBlock({ conv, theme }) {
//   const {
//     run_no,
//     phishing,
//     evidence,
//     risk,
//     victim_vulnerabilities = [],
//     guidance,
//   } = conv || {};

//   const riskStyle = getRiskStyle(risk?.level || guidance?.meta?.analysis_context?.risk_level);
//   const riskScore = risk?.score ?? guidance?.meta?.analysis_context?.risk_score ?? 0;


//   const guidanceText = useMemo(() => {
//     if (!guidance) return null;
//     if (typeof guidance === "string") return guidance;
//     if (guidance.content) return guidance.content;
//     if (guidance.raw?.text) return guidance.raw.text;
//     return null;
//   }, [guidance]);

//   const categories = guidance?.raw?.categories || [];
//   const reasoning = guidance?.raw?.reasoning;
//   const expectedEffect = guidance?.raw?.expected_effect;

//   return (
//     <div
//       className="rounded-xl p-6 mb-6"
//       style={{
//         backgroundColor: theme.panel,
//         border: `1px solid ${theme.border}`,
//       }}
//     >
//       {/* 헤더 */}
//       <div className="flex items-center justify-between mb-6 pb-4" style={{ borderBottom: `1px solid ${theme.border}40` }}>
//         <div className="flex items-center gap-3">
//           <div
//             className="w-8 h-8 rounded-lg flex items-center justify-center font-bold"
//             style={{
//               backgroundColor: theme.blurple,
//               color: "#000",
//             }}
//           >
//             {run_no}
//           </div>
//           <span className="font-semibold" style={{ color: theme.text }}>
//             라운드 {run_no}
//           </span>
//         </div>
        
//         <div
//           className="px-4 py-1.5 rounded-full text-xs font-bold"
//           style={{
//             backgroundColor: phishing ? "#EF444420" : "#10B98120",
//             color: phishing ? "#EF4444" : "#10B981",
//             border: `1px solid ${phishing ? "#EF4444" : "#10B981"}`,
//           }}
//         >
//           {phishing ? "피싱 성공" : "피싱 실패"}
//         </div>
//       </div>

//       {/* 판정 근거 */}
//       <Section icon={Shield} title="피싱 판정 결과" color={theme.blurple}>
//         <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
//           {evidence || "근거 없음"}
//         </p>
//       </Section>

//       {/* 위험도 */}
//       {risk && (
//         <Section
//           icon={TrendingUp}
//           title="위험도"
//           color={riskStyle.color}
//           badge={
//             <div className="flex items-center gap-2">
//               <span
//                 className="px-3 py-1 rounded-full text-xs font-bold"
//                 style={{
//                   backgroundColor: riskStyle.bg,
//                   color: riskStyle.color,
//                 }}
//               >
//                 {riskStyle.label}
//               </span>
//               <span
//                 className="px-3 py-1 rounded-full text-xs font-mono font-bold"
//                 style={{
//                   backgroundColor: riskStyle.bg,
//                   color: riskStyle.color,
//                 }}
//               >
//                 {riskScore}점
//               </span>
//             </div>
//           }
//         >
//           <div className="space-y-3">
//             {/* 위험도 바 */}
//             <div
//               className="w-full h-2 rounded-full overflow-hidden"
//               style={{ backgroundColor: theme.panelDark }}
//             >
//               <div
//                 className="h-2 transition-all duration-1000"
//                 style={{
//                   width: `${riskScore}%`,
//                   backgroundColor: riskStyle.color,
//                 }}
//               />
//             </div>
            
//             {/* 근거 */}
//             <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
//               {risk.rationale}
//             </p>
//           </div>
//         </Section>
//       )}

//       {/* 취약점 */}
//       {victim_vulnerabilities.length > 0 && (
//         <Section
//           icon={Target}
//           title="피해자 취약 요인"
//           color={theme.warn}
//           badge={
//             <span
//               className="px-2 py-0.5 rounded text-xs font-bold"
//               style={{
//                 backgroundColor: "#F59E0B20",
//                 color: theme.warn,
//               }}
//             >
//               {victim_vulnerabilities.length}
//             </span>
//           }
//         >
//           <div className="space-y-2">
//             {victim_vulnerabilities.map((v, i) => (
//               <div key={i} className="flex gap-3">
//                 <span
//                   className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0 text-xs font-bold"
//                   style={{
//                     backgroundColor: "#F59E0B20",
//                     color: theme.warn,
//                   }}
//                 >
//                   {i + 1}
//                 </span>
//                 <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
//                   {v}
//                 </p>
//               </div>
//             ))}
//           </div>
//         </Section>
//       )}

//       {/* 공격 가이던스 */}
//       {guidanceText && (
//         <Section icon={Lightbulb} title="공격 가이던스 (GuidanceGeneration)" color={theme.purple}>
//           <div className="space-y-3">

//             {/* 카테고리 */}
//             {categories.length > 0 && (
//               <div className="flex flex-wrap gap-2 mb-3">
//                 {categories.map((cat, i) => (
//                   <span
//                     key={i}
//                     className="px-2 py-1 rounded text-xs font-mono font-bold"
//                     style={{
//                       backgroundColor: "#A855F720",
//                       color: theme.purple,
//                       border: `1px solid #A855F740`,
//                     }}
//                   >
//                     {cat}
//                   </span>
//                 ))}
//               </div>
//             )}

//             {/* 핵심 가이던스 텍스트 */}
//             <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
//               {guidanceText}
//             </p>

//             {/* 추론 */}
//             {reasoning && (
//               <div
//                 className="p-3 rounded-lg"
//                 style={{
//                   backgroundColor: theme.panelDark,
//                   borderLeft: `2px solid ${theme.cyan}`,
//                 }}
//               >
//                 <div className="text-xs mb-1 font-medium" style={{ color: theme.cyan }}>
//                   추론 과정
//                 </div>
//                 <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
//                   {reasoning}
//                 </p>
//               </div>
//             )}

//             {/* 예상 효과 */}
//             {expectedEffect && (
//               <div
//                 className="p-3 rounded-lg"
//                 style={{
//                   backgroundColor: theme.panelDark,
//                   borderLeft: `2px solid ${theme.success}`,
//                 }}
//               >
//                 <div className="text-xs mb-1 font-medium" style={{ color: theme.success }}>
//                   예상 효과
//                 </div>
//                 <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
//                   {expectedEffect}
//                 </p>
//               </div>
//             )}

//             {/* 분석 맥락 (meta.analysis_context) */}
//             {guidance?.meta?.analysis_context && (
//               <div
//                 className="p-3 rounded-lg mt-3"
//                 style={{
//                   backgroundColor: theme.panelDark,
//                   borderLeft: `2px solid ${theme.warn}`,
//                 }}
//               >
//                 <div className="text-xs mb-1 font-medium" style={{ color: theme.warn }}>
//                   분석 맥락 (Victim Analysis)
//                 </div>

//                 {/* 성향 (OCEAN) */}
//                 {guidance.meta.analysis_context.victim_traits?.ocean && (
//                   <div className="grid grid-cols-2 gap-1 text-xs" style={{ color: theme.sub }}>
//                     {Object.entries(guidance.meta.analysis_context.victim_traits.ocean).map(
//                       ([trait, value]) => (
//                         <div key={trait}>
//                           <span className="font-semibold">{trait}</span>: {value}
//                         </div>
//                       )
//                     )}
//                   </div>
//                 )}

//                 {/* 취약성 노트 */}
//                 {guidance.meta.analysis_context.victim_traits?.vulnerability_notes?.length > 0 && (
//                   <ul className="list-disc list-inside mt-2 text-xs" style={{ color: theme.sub }}>
//                     {guidance.meta.analysis_context.victim_traits.vulnerability_notes.map((v, i) => (
//                       <li key={i}>{v}</li>
//                     ))}
//                   </ul>
//                 )}

//                 {/* 위험도 정보 */}
//                 <div className="mt-2 text-xs" style={{ color: theme.sub }}>
//                   <b>위험도:</b> {guidance.meta.analysis_context.risk_level} ({guidance.meta.analysis_context.risk_score}점)
//                 </div>
//               </div>
//             )}
//           </div>
//         </Section>
//       )}
//     </div>
//   );
// }

// /*== 메인 컴포넌트 ==*/
// export default function InvestigationBoard({
//   COLORS,
//   judgement,
//   guidance,
//   prevention,
// }) {
//   const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };
//   const [roundData, setRoundData] = useState([]);

//   const mergeRoundData = (type, data) => {
//     const runNo = data?.run_no ?? data?.content?.run_no ?? 1;

//     setRoundData((prev) => {
//       const existing = prev.find((r) => r.run_no === runNo) || { run_no: runNo };

//       const updated = {
//         ...existing,
//         run_no: runNo,
//         phishing: data?.phishing ?? data?.content?.phishing ?? existing.phishing,
//         evidence: data?.evidence ?? data?.content?.evidence ?? existing.evidence,
//         risk: data?.risk ?? data?.content?.risk ?? existing.risk,
//         victim_vulnerabilities:
//           data?.victim_vulnerabilities ??
//           data?.content?.victim_vulnerabilities ??
//           existing.victim_vulnerabilities ??
//           [],
//         guidance: type === "guidance" ? data : existing.guidance,
//         prevention: type === "prevention" ? data : existing.prevention,
//       };

//       const newList = prev.filter((r) => r.run_no !== runNo).concat(updated);
//       return newList.sort((a, b) => (a.run_no ?? 0) - (b.run_no ?? 0));
//     });
//   };

//   useEffect(() => {
//     if (judgement) {
//       const data = judgement.content || judgement;
//       mergeRoundData("judgement", data);
//     }
//   }, [judgement]);

//   useEffect(() => {
//     if (guidance) {
//       const data = guidance.content || guidance;
//       const runNo = data?.run_no ?? roundData[roundData.length - 1]?.run_no ?? 1;
//       mergeRoundData("guidance", { ...data, run_no: runNo });
//     }
//   }, [guidance]);

//   useEffect(() => {
//     if (prevention) {
//       const data = prevention.content || prevention;
//       mergeRoundData("prevention", data);
//     }
//   }, [prevention]);

//   return (
//     <div
//       className="h-full overflow-y-auto p-6"
//       style={{ backgroundColor: theme.bg }}
//     >
//       {roundData.length > 0 ? (
//         <>
//           <div className="mb-6">
//             <h1 className="text-xl font-bold mb-1" style={{ color: theme.text }}>
//               피싱 판정 결과
//             </h1>
//             <p className="text-sm" style={{ color: theme.sub }}>
//               총 {roundData.length}개 라운드 분석 완료
//             </p>
//           </div>

//           {roundData.map((conv, idx) => (
//             <RoundBlock key={idx} conv={conv} theme={theme} />
//           ))}
//         </>
//       ) : (
//         <div className="flex flex-col items-center justify-center h-full gap-3">
//           <Shield size={48} color={theme.blurple} className="animate-pulse" />
//           <div className="text-center">
//             <p className="font-medium mb-1" style={{ color: theme.text }}>
//               분석 데이터 대기 중
//             </p>
//             <p className="text-sm" style={{ color: theme.sub }}>
//               시뮬레이션 결과가 표시됩니다
//             </p>
//           </div>
//         </div>
//       )}
//     </div>
//   );
// }

// // src/components/InvestigationBoard.jsx
// import React, { useEffect, useState, useMemo } from "react";

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

// /*== 유틸 함수 ==*/
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

// /*== 개별 라운드 블록 ==*/
// function ConversationBlock({ conv, COLORS }) {
//   const {
//     run_no,
//     phishing,
//     evidence,
//     risk,
//     victim_vulnerabilities = [],
//     guidance,
//     prevention,
//   } = conv || {};

//   const riskScore = risk?.score ?? 0;
//   const riskLevel = toKoreanLevel(risk?.level);
//   const riskColor = getRiskColor(riskScore);
//   const rationale = risk?.rationale || "근거 없음";

//   const formattedGuidance = useMemo(() => {
//     if (!guidance) return null;
//     if (Array.isArray(guidance)) {
//       return guidance
//         .filter((g) => g?.text)
//         .map((g, i) => `${i + 1}. ${g.text}`)
//         .join("\n\n");
//     }
//     if (typeof guidance === "object" && guidance.text) return guidance.text;
//     return guidance?.data?.text || guidance?.message || null;
//   }, [guidance]);

//   return (
//     <>
//       {/* 헤더 */}
//       <div className="p-4 border-b" style={{ borderColor: COLORS.border }}>
//         <div className="flex items-center justify-between">
//           <div className="flex items-center gap-2">
//             <div
//               className="w-2 h-2 rounded-full"
//               style={{ backgroundColor: "#FAAD14" }}
//             />
//             <h2 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//               {run_no ?? 0}번째 라운드 분석 결과
//             </h2>
//           </div>
//           <div className="ml-auto">
//             {phishing ? (
//               <span
//                 className="px-3 py-1 rounded text-xs text-white"
//                 style={{ backgroundColor: "#FF4D4F" }}
//               >
//                 피싱 방어 실패
//               </span>
//             ) : (
//               <span
//                 className="px-3 py-1 rounded text-xs text-white"
//                 style={{ backgroundColor: "#52C41A" }}
//               >
//                 피싱 방어 성공
//               </span>
//             )}
//           </div>
//         </div>
//       </div>

//       {/* 본문 */}
//       <div className="p-6 space-y-6">
//         {/* 피싱 판정 근거 */}
//         <section>
//           <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
//             {phishing ? "피싱 성공 근거" : "피싱 실패 근거"}
//           </h3>
//           <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//             <p
//               className="text-sm leading-relaxed whitespace-pre-wrap"
//               style={{ color: COLORS.sub }}
//             >
//               {evidence || "근거 없음"}
//             </p>
//           </div>
//         </section>

//         {/* 위험도 */}
//         {risk && (
//           <section>
//             <div className="flex items-center justify-between mb-4">
//               <div className="flex items-center gap-2">
//                 <div
//                   className="w-2 h-2 rounded-full"
//                   style={{ backgroundColor: COLORS.blurple }}
//                 />
//                 <h3 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//                   위험도
//                 </h3>
//               </div>
//               <span
//                 className="px-3 py-1 rounded text-xs text-white"
//                 style={{ backgroundColor: riskColor }}
//               >
//                 {riskLevel} (점수 {riskScore}점)
//               </span>
//             </div>

//             <div
//               className="w-full h-4 rounded-full overflow-hidden mb-2"
//               style={{ backgroundColor: COLORS.panel }}
//             >
//               <div
//                 className="h-4 transition-all duration-700 ease-in-out"
//                 style={{ width: `${riskScore}%`, backgroundColor: riskColor }}
//               />
//             </div>

//             <h4 className="font-medium mt-3 mb-1" style={{ color: COLORS.text }}>
//               위험도 근거
//             </h4>
//             <p
//               className="text-sm leading-relaxed whitespace-pre-wrap"
//               style={{ color: COLORS.sub }}
//             >
//               {rationale}
//             </p>
//           </section>
//         )}

//         {/* 피해자 취약 요인 */}
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

//         {/* 시뮬레이션 후 가이드라인 */}
//         {formattedGuidance && (
//           <section>
//             <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
//               💡 시뮬레이션 후 가이드라인
//             </h3>
//             <div className="p-4 rounded-lg mb-3" style={{ backgroundColor: COLORS.panel }}>
//               <p
//                 className="text-sm leading-relaxed whitespace-pre-wrap"
//                 style={{ color: COLORS.sub }}
//               >
//                 {formattedGuidance}
//               </p>
//             </div>
//           </section>
//         )}

//         {/* 예방 팁 */}
//         {prevention && (
//           <section>
//             <h3 className="text-lg font-semibold mb-3" style={{ color: COLORS.text }}>
//               🛡 예방 팁
//             </h3>
//             <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//               <p
//                 className="text-sm leading-relaxed whitespace-pre-wrap"
//                 style={{ color: COLORS.sub }}
//               >
//                 {prevention?.data?.tip || prevention?.message || "예방 팁 없음"}
//               </p>
//             </div>
//           </section>
//         )}
//       </div>
//     </>
//   );
// }

// /*== 메인 컴포넌트 ==*/
// export default function InvestigationBoard({
//   COLORS: theme = COLORS,
//   judgement,
//   guidance,
//   prevention,
// }) {
//   const [roundData, setRoundData] = useState([]);

//   // 공통 병합 함수
//   const mergeRoundData = (type, data) => {
//     const runNo = data?.run_no ?? 1;

//     setRoundData((prev) => {
//       const existing = prev.find((r) => r.run_no === runNo) || { run_no: runNo };

//       const updated = {
//         ...existing,
//         [type]: data,
//         phishing: data?.phishing ?? existing.phishing,
//         evidence: data?.evidence ?? existing.evidence,
//         risk: data?.risk ?? existing.risk,
//         victim_vulnerabilities:
//           data?.victim_vulnerabilities ?? existing.victim_vulnerabilities ?? [],
//         guidance: type === "guidance" ? data : existing.guidance,
//         prevention: type === "prevention" ? data : existing.prevention,
//       };

//       const newList = prev.filter((r) => r.run_no !== runNo).concat(updated);
//       return newList.sort((a, b) => (a.run_no ?? 0) - (b.run_no ?? 0));
//     });
//   };

//   /* === 데이터별 감시 === */
//   useEffect(() => {
//     if (judgement) mergeRoundData("judgement", judgement);
//   }, [judgement]);

//   useEffect(() => {
//     if (guidance) mergeRoundData("guidance", guidance);
//   }, [guidance]);

//   useEffect(() => {
//     if (prevention) mergeRoundData("prevention", prevention);
//   }, [prevention]);

//   return (
//     <div
//       className="h-full overflow-y-auto"
//       style={{ backgroundColor: theme.panelDark, maxHeight: "100vh" }}
//     >
//       {roundData.length > 0 ? (
//         roundData.map((conv, idx) => (
//           <ConversationBlock key={idx} conv={conv} COLORS={theme} />
//         ))
//       ) : (
//         <div className="p-6 text-sm opacity-70" style={{ color: theme.sub }}>
//           분석 데이터를 불러오는 중입니다...
//         </div>
//       )}
//     </div>
//   );
// }

// src/components/InvestigationBoard.jsx
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

// /*== 개별 라운드 블록 ==*/
// function ConversationBlock({ conv, COLORS }) {
//   const { run_no, phishing, evidence, risk, victim_vulnerabilities = [], guidance, prevention } = conv || {};

//   const riskScore = risk?.score ?? 0;
//   const riskLevel = toKoreanLevel(risk?.level);
//   const riskColor = getRiskColor(riskScore);
//   const rationale = risk?.rationale || "근거 없음";

//   /* guidance가 배열(JSON 구조)일 때 text를 묶어 표시 */
//   const formattedGuidance = useMemo(() => {
//     if (!guidance) return null;
//     if (Array.isArray(guidance)) {
//       return guidance
//         .filter((g) => g?.text)
//         .map((g, i) => `${i + 1}. ${g.text}`)
//         .join("\n\n");
//     }
//     if (typeof guidance === "object" && guidance.text) return guidance.text;
//     return guidance?.data?.text || guidance?.message || null;
//   }, [guidance]);

//   return (
//     <div className="border-b" style={{ borderColor: COLORS.border }}>
//       {/* 라운드 헤더 */}
//       <div className="p-4 border-b flex justify-between items-center" style={{ borderColor: COLORS.border }}>
//         <h2 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//           🔹 {run_no ?? 0}번째 라운드 분석 결과
//         </h2>
//         {phishing ? (
//           <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#FF4D4F" }}>
//             피싱 방어 실패
//           </span>
//         ) : (
//           <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: "#52C41A" }}>
//             피싱 방어 성공
//           </span>
//         )}
//       </div>

//       {/* 본문 */}
//       <div className="p-6 space-y-6">
//         {/* 피싱 근거 */}
//         <section>
//           <h3 className="text-lg font-semibold mb-2" style={{ color: COLORS.text }}>
//             {phishing ? "피싱 성공 근거" : "피싱 실패 근거"}
//           </h3>
//           <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//             <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
//               {evidence || "근거 없음"}
//             </p>
//           </div>
//         </section>

//         {/* 위험도 */}
//         {risk && (
//           <section>
//             <div className="flex items-center justify-between mb-3">
//               <h3 className="text-lg font-semibold" style={{ color: COLORS.text }}>
//                 위험도
//               </h3>
//               <span className="px-3 py-1 rounded text-xs text-white" style={{ backgroundColor: riskColor }}>
//                 {riskLevel} ({riskScore}점)
//               </span>
//             </div>

//             <div className="w-full h-4 rounded-full overflow-hidden mb-2" style={{ backgroundColor: COLORS.panel }}>
//               <div
//                 className="h-4 transition-all duration-700 ease-in-out"
//                 style={{ width: `${riskScore}%`, backgroundColor: riskColor }}
//               />
//             </div>

//             <h4 className="font-medium mt-3 mb-1" style={{ color: COLORS.text }}>
//               위험도 근거
//             </h4>
//             <p className="text-sm leading-relaxed" style={{ color: COLORS.sub }}>
//               {rationale}
//             </p>
//           </section>
//         )}

//         {/* 피해자 취약요소 */}
//         {victim_vulnerabilities.length > 0 && (
//           <section>
//             <h3 className="text-lg font-semibold mb-2" style={{ color: COLORS.text }}>
//               피해자 취약 요인
//             </h3>
//             <ul className="space-y-1 text-sm" style={{ color: COLORS.sub }}>
//               {victim_vulnerabilities.map((v, i) => (
//                 <li key={i}>• {v}</li>
//               ))}
//             </ul>
//           </section>
//         )}

//         {/* 가이드라인 */}
//         {formattedGuidance && (
//           <section>
//             <h3 className="text-lg font-semibold mb-2" style={{ color: COLORS.text }}>
//               💡 시뮬레이션 후 가이드라인
//             </h3>
//             <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//               <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
//                 {formattedGuidance}
//               </p>
//             </div>
//           </section>
//         )}

//         {/* 예방 팁 */}
//         {prevention && (
//           <section>
//             <h3 className="text-lg font-semibold mb-2" style={{ color: COLORS.text }}>
//               🛡 예방 팁
//             </h3>
//             <div className="p-4 rounded-lg" style={{ backgroundColor: COLORS.panel }}>
//               <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: COLORS.sub }}>
//                 {prevention?.data?.tip || prevention?.message || "예방 팁 없음"}
//               </p>
//             </div>
//           </section>
//         )}
//       </div>
//     </div>
//   );
// }

// /*== 메인 컴포넌트 ==*/
// export default function InvestigationBoard({
//   COLORS: theme = COLORS,
//   judgement,
//   guidance,
//   prevention,
// }) {
//   const [roundData, setRoundData] = useState([]);

//   /* ✅ 라운드별 데이터 수집 */
//   useEffect(() => {
//     if (!judgement && !guidance && !prevention) return;

//     // run_no를 기준으로 병합
//     const runNo = judgement?.run_no ?? guidance?.run_no ?? prevention?.run_no ?? 1;

//     setRoundData((prev) => {
//       const existing = prev.find((r) => r.run_no === runNo);
//       const updated = {
//         ...(existing || {}),
//         run_no: runNo,
//         phishing: judgement?.phishing ?? existing?.phishing,
//         evidence: judgement?.evidence ?? existing?.evidence,
//         risk: judgement?.risk ?? existing?.risk,
//         victim_vulnerabilities: judgement?.victim_vulnerabilities ?? existing?.victim_vulnerabilities ?? [],
//         guidance: guidance?.data || guidance || existing?.guidance,
//         prevention: prevention?.data || prevention || existing?.prevention,
//       };
//       const newList = prev.filter((r) => r.run_no !== runNo).concat(updated);
//       return newList.sort((a, b) => (a.run_no ?? 0) - (b.run_no ?? 0));
//     });
//   }, [judgement, guidance, prevention]);

//   return (
//     <div className="h-full overflow-y-auto" style={{ backgroundColor: theme.panelDark, maxHeight: "100vh" }}>
//       {roundData.length > 0 ? (
//         roundData.map((conv, idx) => <ConversationBlock key={idx} conv={conv} COLORS={theme} />)
//       ) : (
//         <div className="p-6 text-sm opacity-70" style={{ color: theme.sub }}>
//           분석 데이터를 불러오는 중입니다...
//         </div>
//       )}
//     </div>
//   );
// }

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
