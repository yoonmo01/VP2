// src/MessageBubble.jsx
import { useEffect, useState } from "react";
import { MessageSquareText , Brain, Box, Circle, Minus } from "lucide-react";  // ⭐ 라운드 구분용 아이콘

function getRiskColors(pct) {
  const v = Math.max(0, Math.min(100, Number(pct) || 0));
  if (v >= 70)
    return {
      border: "rgba(239,68,68,0.75)",
      bg: "rgba(239,68,68,0.10)",
      text: "#EF4444",
    };
  if (v >= 41)
    return {
      border: "rgba(245,158,11,0.75)",
      bg: "rgba(245,158,11,0.10)",
      text: "#F59E0B",
    };
  return {
    border: "rgba(16,185,129,0.75)",
    bg: "rgba(16,185,129,0.10)",
    text: "#10B981",
  };
}

export default function MessageBubble({
  message,
  selectedCharacter,
  victimImageUrl,
  COLORS,
}) {
  const isVictim = message.sender === "victim";
  const isScammer = message.sender === "offender";
  const isSystem = message.sender === "system";
  const isRoundDivider = message.isRoundDivider === true;

  const [parsed, setParsed] = useState({
    dialogue: "",
    thoughts: null,
    is_convinced: null,
  });

  useEffect(() => {
    const content = message.content;

    if (isScammer && typeof content === "string") {
      setParsed({
        dialogue: content,
        thoughts: null,
        is_convinced: null,
      });
      return;
    }

    if (isVictim && typeof content === "object") {
      setParsed({
        dialogue: content.dialogue ?? "",
        thoughts: content.thoughts ?? null,
        is_convinced: content.is_convinced ?? null,
      });
      return;
    }

    setParsed({
      dialogue: typeof content === "string" ? content : "",
      thoughts: null,
      is_convinced: null,
    });
  }, [message, isVictim, isScammer]);

  const convincedPct =
    typeof parsed.is_convinced === "number"
      ? parsed.is_convinced * 10
      : null;

  const risk = getRiskColors(convincedPct ?? 0);

  /* ============================================================
     ⭐ 라운드 구분 UI (가장 먼저 렌더링)
     ============================================================ */
  if (isRoundDivider) {
    return (
      <div className="flex justify-center my-10">
        <div
          className="flex items-center gap-3 px-6 py-3 rounded-2xl shadow-lg border backdrop-blur-sm"
          style={{
            background: "linear-gradient(135deg, #EBF2FF 0%, #D8E5FF 100%)",
            borderColor: "#94A9FF",
            color: "#1E3A8A",
            fontWeight: 700,
            fontSize: "1.05rem",
            letterSpacing: "0.3px",
          }}
        >
          <Circle className="w-4 h-4 text-blue-700" strokeWidth={2} />
          <span>ROUND {message.round}</span>
          <Minus className="w-6 h-6 text-blue-300" strokeWidth={1.5} />
        </div>
      </div>
    );
  }

  /* ============================================================
     ⭐ 일반 메시지(피싱범 / 피해자 / 시스템)
     ============================================================ */
  return (
    <div
      className={`flex ${
        isVictim ? "justify-end" : isScammer ? "justify-start" : "justify-center"
      } mb-6`}
    >
      <div className="max-w-md lg:max-w-lg">

        {/* 카드 전체 영역 */}
        <div
          className="rounded-3xl shadow-xl overflow-hidden transition-all duration-200"
          style={{
            backgroundColor: isVictim
              ? "#F3F8FF"
              : isSystem
              ? "#F9FAFB"
              : "#1F2937",
            border: isVictim
              ? "2px solid #93C5FD"
              : isSystem
              ? "2px solid #E5E7EB"
              : "2px solid #374151",
          }}
        >

          {/* 헤더 */}
          <div
            className="px-5 py-3"
            style={{
              background: isVictim
                ? "linear-gradient(135deg, #E0EDFF 0%, #C7DBFF 100%)"
                : isSystem
                ? "#F3F4F6"
                : "linear-gradient(135deg, #2F3541 0%, #1C212A 100%)",
              borderBottom: isVictim
                ? "1px solid #93C5FD"
                : isSystem
                ? "1px solid #D1D5DB"
                : "1px solid #4B5563",
            }}
          >
            <div className="flex items-center justify-between">

              {/* 프로필 */}
              <div className="flex items-center gap-2">
                {isScammer && (
                  <>
                    <img
                      src={new URL("./assets/offender_profile.png", import.meta.url).href}
                      alt="피싱범"
                      className="w-9 h-9 rounded-full object-cover ring-2 ring-red-400/50"
                    />
                    <span className="text-base font-semibold text-red-300">피싱범</span>
                  </>
                )}

                {isVictim && selectedCharacter && (
                  <>
                    {victimImageUrl ? (
                      <img
                        src={victimImageUrl}
                        alt={selectedCharacter.name}
                        className="w-9 h-9 rounded-full object-cover ring-2 ring-blue-400/50"
                      />
                    ) : (
                      <span className="text-xl">{selectedCharacter.avatar ?? ""}</span>
                    )}
                    <span className="text-base font-semibold text-blue-700">
                      {selectedCharacter.name}
                    </span>
                  </>
                )}
              </div>

              {/* 신뢰도 UI */}
              {isVictim && convincedPct !== null && (
                <div className="flex items-center gap-3">
                  <div
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold shadow-md"
                    style={{
                      backgroundColor: risk.bg,
                      border: `1.5px solid ${risk.border}`,
                      color: risk.text,
                    }}
                  >
                    <Box className="w-3.5 h-3.5" />
                    <span>신뢰도 {convincedPct}%</span>
                  </div>

                  <div className="w-24 h-2 rounded-full bg-gray-300 overflow-hidden">
                    <div
                      className="h-full transition-all duration-300"
                      style={{
                        width: `${convincedPct}%`,
                        backgroundColor: risk.text,
                      }}
                    ></div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 속마음 */}
          {isVictim && parsed.thoughts && (
            <div className="px-5 pt-2 pb-1">
              <div
                className="rounded-xl px-4 py-3 shadow-sm"
                style={{
                  backgroundColor: risk.bg,
                  border: `1px dashed ${risk.border}`,
                  color: risk.text,
                  fontSize: "0.92rem",
                }}
              >
                <div className="flex items-start gap-3">

                  {/* 아이콘 박스 */}
                  <div
                    className="flex items-center justify-center rounded-md"
                    style={{
                      width: "22px",
                      height: "22px",
                      backgroundColor: "rgba(255,255,255,0.35)",
                      border: `1px solid ${risk.border}`,
                    }}
                  >
                    <Brain
                      className="w-4 h-4"
                      style={{ color: risk.text }}
                      strokeWidth={1.8}
                    />
                  </div>

                  <span className="italic font-medium leading-relaxed">
                    {parsed.thoughts}
                  </span>
                </div>
              </div>
            </div>
          )}


          {/* 대화 */}
          <div className="px-6 pt-2 pb-4">
            <div
              className="flex items-start gap-3"
              style={{
                color: isVictim ? "#1E3A8A" : isSystem ? "#374151" : "#F3F4F6",
                backgroundColor: isVictim ? "#E1E9FF" : "transparent",
                padding: isVictim ? "14px 16px" : undefined,
                borderRadius: isVictim ? "12px" : undefined,
                fontSize: "1rem",
                fontWeight: 500,
                lineHeight: "1.6",
              }}
            >
              {/* 아이콘 박스 */}
              <div
                className="flex items-center justify-center rounded-md"
                style={{
                  width: "22px",
                  height: "22px",
                  backgroundColor: isVictim ? "#D9E4FF" : "rgba(255,255,255,0.15)",
                }}
              >
                <MessageCircleMore
                  className="w-4 h-4"
                  strokeWidth={1.8}
                  style={{
                    color: isVictim ? "#1E3A8A" : "#E5E7EB",
                  }}
                />
              </div>

              <span>{parsed.dialogue}</span>
            </div>
          </div>
           
          {/* 타임스탬프 */}
          <div
            className="px-5 py-2 text-xs text-right font-medium"
            style={{
              color: "#9CA3AF",
              backgroundColor: isVictim ? "#F0F9FF" : isSystem ? "#FAFAFA" : "#111827",
              borderTop: isVictim
                ? "1px solid #DBEAFE"
                : isSystem
                ? "1px solid #F3F4F6"
                : "1px solid #1F2937",
            }}
          >
            {message.timestamp}
          </div>
        </div>
      </div>
    </div>
  );
}

// // src/MessageBubble.jsx
// import { useEffect, useState } from "react";

// function getRiskColors(pct) {
//   const v = Math.max(0, Math.min(100, Number(pct) || 0));
//   if (v >= 70)
//     return {
//       border: "rgba(239,68,68,0.75)",
//       bg: "rgba(239,68,68,0.10)",
//       text: "#EF4444",
//     };
//   if (v >= 41)
//     return {
//       border: "rgba(245,158,11,0.75)",
//       bg: "rgba(245,158,11,0.10)",
//       text: "#F59E0B",
//     };
//   return {
//     border: "rgba(16,185,129,0.75)",
//       bg: "rgba(16,185,129,0.10)",
//       text: "#10B981",
//     };
// }

// export default function MessageBubble({
//   message,
//   selectedCharacter,
//   victimImageUrl,
//   COLORS,
// }) {
//   const isVictim = message.sender === "victim";
//   const isScammer = message.sender === "offender";
//   const isSystem = message.sender === "system";

//   const [parsed, setParsed] = useState({
//     dialogue: "",
//     thoughts: null,
//     is_convinced: null,
//   });

//   useEffect(() => {
//     const content = message.content;

//     if (isScammer && typeof content === "string") {
//       setParsed({
//         dialogue: content,
//         thoughts: null,
//         is_convinced: null,
//       });
//       return;
//     }

//     if (isVictim && typeof content === "object") {
//       setParsed({
//         dialogue: content.dialogue ?? "",
//         thoughts: content.thoughts ?? null,
//         is_convinced: content.is_convinced ?? null,
//       });
//       return;
//     }

//     setParsed({
//       dialogue: typeof content === "string" ? content : "",
//       thoughts: null,
//       is_convinced: null,
//     });
//   }, [message, isVictim, isScammer]);

//   const convincedPct =
//     typeof parsed.is_convinced === "number"
//       ? parsed.is_convinced * 10
//       : null;

//   const risk = getRiskColors(convincedPct ?? 0);

//   return (
//     <div
//       className={`flex ${
//         isVictim ? "justify-end" : isScammer ? "justify-start" : "justify-center"
//       } mb-6`}
//     >
//       <div className="max-w-md lg:max-w-lg">
//         {/* 카드 전체 영역 */}
//         <div
//           className="rounded-3xl shadow-xl overflow-hidden transition-all duration-200"
//           style={{
//             backgroundColor: isVictim
//               ? "#F3F8FF"
//               : isSystem
//               ? "#F9FAFB"
//               : "#1F2937",
//             border: isVictim
//               ? "2px solid #93C5FD"
//               : isSystem
//               ? "2px solid #E5E7EB"
//               : "2px solid #374151",
//           }}
//         >
//           {/* 헤더 */}
//           <div
//             className="px-5 py-3"
//             style={{
//               background: isVictim
//                 ? "linear-gradient(135deg, #E0EDFF 0%, #C7DBFF 100%)"
//                 : isSystem
//                 ? "#F3F4F6"
//                 : "linear-gradient(135deg, #2F3541 0%, #1C212A 100%)",
//               borderBottom: isVictim
//                 ? "1px solid #93C5FD"
//                 : isSystem
//                 ? "1px solid #D1D5DB"
//                 : "1px solid #4B5563",
//             }}
//           >
//             <div className="flex items-center justify-between">
//               {/* 프로필 */}
//               <div className="flex items-center gap-2">
//                 {isScammer && (
//                   <>
//                     <img
//                       src={new URL("./assets/offender_profile.png", import.meta.url).href}
//                       alt="피싱범"
//                       className="w-9 h-9 rounded-full object-cover ring-2 ring-red-400/50"
//                     />
//                     <span className="text-base font-semibold text-red-300">피싱범</span>
//                   </>
//                 )}

//                 {isVictim && selectedCharacter && (
//                   <>
//                     {victimImageUrl ? (
//                       <img
//                         src={victimImageUrl}
//                         alt={selectedCharacter.name}
//                         className="w-9 h-9 rounded-full object-cover ring-2 ring-blue-400/50"
//                       />
//                     ) : (
//                       <span className="text-xl">{selectedCharacter.avatar ?? "👤"}</span>
//                     )}
//                     <span className="text-base font-semibold text-blue-700">
//                       {selectedCharacter.name}
//                     </span>
//                   </>
//                 )}
//               </div>

//               {/* ⭐ 신뢰도 UI — 아이콘 교체 + 텍스트 + 프로그래스바 */}
//               {isVictim && convincedPct !== null && (
//                 <div className="flex items-center gap-3">
                  
//                   {/* 신뢰도 텍스트 배지 */}
//                   <div
//                     className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold shadow-md"
//                     style={{
//                       backgroundColor: risk.bg,
//                       border: `1.5px solid ${risk.border}`,
//                       color: risk.text,
//                     }}
//                   >
//                     {/* Shield Icon */}
//                     <svg
//                       className="w-3.5 h-3.5"
//                       fill="currentColor"
//                       viewBox="0 0 20 20"
//                     >
//                       <path d="M10 2l6 3v5c0 5-6 8-6 8s-6-3-6-8V5l6-3z" />
//                     </svg>

//                     <span>신뢰도 {convincedPct}%</span>
//                   </div>

//                   {/* 프로그래스바 */}
//                   <div className="w-24 h-2 rounded-full bg-gray-300 overflow-hidden">
//                     <div
//                       className="h-full transition-all duration-300"
//                       style={{
//                         width: `${convincedPct}%`,
//                         backgroundColor: risk.text,
//                       }}
//                     ></div>
//                   </div>
//                 </div>
//               )}
//             </div>
//           </div>

//           {/* 속마음 */}
//           {isVictim && parsed.thoughts && (
//             <div className="px-5 pt-2 pb-1">  {/* 간격 좁힘 */}
//               <div
//                 className="rounded-xl px-4 py-3 shadow-sm"
//                 style={{
//                   backgroundColor: risk.bg,           // 🔥 고정값 제거 → risk 기반으로 회귀
//                   border: `1px dashed ${risk.border}`, // 🔥 점선 적용
//                   color: risk.text,                    // 🔥 텍스트도 risk 기반
//                   fontSize: "0.92rem",
//                 }}
//               >
//                 <div className="flex items-start gap-2">
//                   <span className="text-xl flex-shrink-0">💭</span>
//                   <span className="italic font-medium leading-relaxed">
//                     {parsed.thoughts}
//                   </span>
//                 </div>
//               </div>
//             </div>
//           )}

//           {/* 대화 */}
//           <div className="px-6 pt-2 pb-4">
//             <div
//               className="flex items-start gap-3"
//               style={{
//                 color: isVictim ? "#1E3A8A" : isSystem ? "#374151" : "#F3F4F6",
//                 backgroundColor: isVictim ? "#E1E9FF" : "transparent", // 더 차분한 블루톤
//                 padding: isVictim ? "14px 16px" : undefined,
//                 borderRadius: isVictim ? "12px" : undefined,
//                 fontSize: "1rem",
//                 fontWeight: 500,
//                 lineHeight: "1.6",
//               }}
//             >
//               <span className="text-xl flex-shrink-0">💬</span>
//               <span>{parsed.dialogue}</span>
//             </div>
//           </div>

//           {/* 타임스탬프 */}
//           <div
//             className="px-5 py-2 text-xs text-right font-medium"
//             style={{
//               color: "#9CA3AF",
//               backgroundColor: isVictim ? "#F0F9FF" : isSystem ? "#FAFAFA" : "#111827",
//               borderTop: isVictim
//                 ? "1px solid #DBEAFE"
//                 : isSystem
//                 ? "1px solid #F3F4F6"
//                 : "1px solid #1F2937",
//             }}
//           >
//             {message.timestamp}
//           </div>
//         </div>
//       </div>
//     </div>
//   );
// }


// src/MessageBubble.jsx
// import { useEffect, useState } from "react";

// /** 설득도 퍼센트별 색상 팔레트 */
// function getRiskColors(pct) {
//   const v = Math.max(0, Math.min(100, Number(pct) || 0));
//   if (v >= 70)
//     return {
//       border: "rgba(239,68,68,0.75)",
//       bg: "rgba(239,68,68,0.10)",
//       text: "#EF4444",
//     };
//   if (v >= 41)
//     return {
//       border: "rgba(245,158,11,0.75)",
//       bg: "rgba(245,158,11,0.10)",
//       text: "#F59E0B",
//     };
//   return {
//     border: "rgba(16,185,129,0.75)",
//     bg: "rgba(16,185,129,0.10)",
//     text: "#10B981",
//   };
// }

// export default function MessageBubble({
//   message,
//   selectedCharacter,
//   victimImageUrl,
//   COLORS,
// }) {
//   const isVictim = message.sender === "victim";
//   const isScammer = message.sender === "offender";
//   const isSystem = message.sender === "system";

//   /** 파싱된 내용 (victim only) */
//   const [parsed, setParsed] = useState({
//     dialogue: "",
//     thoughts: null,
//     is_convinced: null,
//   });

//   useEffect(() => {
//     const content = message.content;

//     // 🔥 offender → content는 문자열이어야 한다.
//     if (isScammer && typeof content === "string") {
//       setParsed({
//         dialogue: content,
//         thoughts: null,
//         is_convinced: null,
//       });
//       return;
//     }

//     // 🔥 victim → content는 object이어야 한다.
//     if (isVictim && typeof content === "object") {
//       setParsed({
//         dialogue: content.dialogue ?? "",
//         thoughts: content.thoughts ?? null,
//         is_convinced: content.is_convinced ?? null,
//       });
//       return;
//     }

//     // fallback: 그냥 문자열로 처리
//     setParsed({
//       dialogue: typeof content === "string" ? content : "",
//       thoughts: null,
//       is_convinced: null,
//     });
//   }, [message, isVictim, isScammer]);

//   const convincedPct =
//     typeof parsed.is_convinced === "number"
//       ? parsed.is_convinced * 10
//       : null;

//   const risk = getRiskColors(convincedPct ?? 0);

//   // ----------------------------- 렌더링 -----------------------------
//   return (
//     <div
//       className={`flex ${
//         isVictim ? "justify-end" : isScammer ? "justify-start" : "justify-center"
//       } mb-5`}
//     >
//       <div
//         className="max-w-md lg:max-w-lg px-5 py-3 rounded-2xl border"
//         style={{
//           backgroundColor: isVictim
//             ? COLORS.white
//             : isSystem
//             ? "rgba(88,101,242,.12)"
//             : "#313338",
//           color: isVictim ? COLORS.black : COLORS.text,
//           border: `1px solid ${COLORS.border}`,
//         }}
//       >
//         {/* ===== 프로필 영역 ===== */}
//         <div className="flex items-center mb-2">
//           {isScammer && (
//             <>
//               <img
//                 src={new URL("./assets/offender_profile.png", import.meta.url).href}
//                 alt="피싱범"
//                 className="w-8 h-8 rounded-full object-cover mr-2"
//               />
//               <span className="text-sm font-medium text-red-400">피싱범</span>
//             </>
//           )}

//           {isVictim && selectedCharacter && (
//             <>
//               {victimImageUrl ? (
//                 <img
//                   src={victimImageUrl}
//                   alt={selectedCharacter.name}
//                   className="w-8 h-8 rounded-full object-cover mr-2"
//                 />
//               ) : (
//                 <span className="text-lg mr-2">{selectedCharacter.avatar ?? "👤"}</span>
//               )}
//               <span className="text-sm font-medium text-blue-400">
//                 {selectedCharacter.name}
//               </span>
//             </>
//           )}
//         </div>

//         {/* ===== 속마음 ===== */}
//         {isVictim && parsed.thoughts && (
//           <div
//             className="mb-3 p-3 rounded-xl border border-dashed text-sm leading-relaxed"
//             style={{
//               borderColor: risk.border,
//               backgroundColor: risk.bg,
//               color: risk.text,
//             }}
//           >
//             💭 {parsed.thoughts}
//           </div>
//         )}

//         {/* ===== 대화 ===== */}
//         <div
//           className="px-4 py-3 rounded-xl"
//           style={{
//             backgroundColor: isVictim ? COLORS.white : "#27272a",
//             color: isVictim ? COLORS.black : COLORS.text,
//             boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
//           }}
//         >
//           💬 {parsed.dialogue}
//         </div>

//         {/* ===== 설득도 바 ===== */}
//         {isVictim && convincedPct !== null && (
//           <div className="mt-3 flex items-center gap-2">
//             <div className="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
//               <div
//                 className="h-full transition-all duration-700 ease-in-out"
//                 style={{
//                   width: `${convincedPct}%`,
//                   backgroundColor: risk.text,
//                 }}
//               />
//             </div>
//             <span className="text-xs opacity-70">{convincedPct}%</span>
//           </div>
//         )}

//         {/* ===== 타임스탬프 ===== */}
//         <div
//           className="text-xs mt-2 opacity-70 text-right"
//           style={{ color: COLORS.sub }}
//         >
//           {message.timestamp}
//         </div>
//       </div>
//     </div>
//   );
// }

//====================================================================================

// // src/MessageBubble.jsx
// import { useEffect, useState } from "react";

// function getRiskColors(pct) {
//   const v = Math.max(0, Math.min(100, Number(pct) || 0));
//   if (v >= 70) return { text: "#EF4444", border: "#EF4444" };
//   if (v >= 41) return { text: "#F59E0B", border: "#F59E0B" };
//   return { text: "#10B981", border: "#10B981" };
// }

// export default function MessageBubble({
//   message,
//   selectedCharacter,
//   victimImageUrl,
//   COLORS,
// }) {
//   const isVictim = message.sender === "victim";
//   const isScammer = message.sender === "offender";

//   const [dialogue, setDialogue] = useState("");
//   const [thoughts, setThoughts] = useState(null);
//   const [convincedPct, setConvincedPct] = useState(null);

//   useEffect(() => {
//     let d = "";
//     let th = null;
//     let conv = null;

//     const c = message?.content;

//     try {
//       if (isVictim) {
//         if (typeof c === "object") {
//           d = c.dialogue ?? "";
//           th = c.thoughts ?? null;
//           conv = (c.is_convinced ?? 0) * 10;
//         } else if (typeof c === "string") {
//           const trimmed = c.trim();
//           if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
//             const parsed = JSON.parse(trimmed);
//             d = parsed.dialogue ?? "";
//             th = parsed.thoughts ?? null;
//             conv = (parsed.is_convinced ?? 0) * 10;
//           } else {
//             d = c;
//           }
//         }
//       } else {
//         // 공격자
//         d = typeof c === "string" ? c : JSON.stringify(c);
//       }
//     } catch (err) {
//       console.warn("메시지 파싱 실패:", err);
//       d = String(c ?? "");
//     }

//     setDialogue(d);
//     setThoughts(th);
//     setConvincedPct(conv);
//   }, [message, isVictim]);

//   const risk = getRiskColors(convincedPct ?? 0);

//   return (
//     <div className={`flex ${isVictim ? "justify-end" : "justify-start"} mb-4`}>
//       <div
//         className="max-w-md rounded-2xl border p-4"
//         style={{
//           backgroundColor: isVictim ? COLORS.white : "#2c2f33",
//           color: isVictim ? COLORS.black : COLORS.text,
//           borderColor: COLORS.border,
//         }}
//       >
//         {/* 이름/프로필 */}
//         <div className="flex items-center mb-2">
//           {isScammer && (
//             <>
//               <img
//                 src={new URL("./assets/offender_profile.png", import.meta.url).href}
//                 alt="피싱범"
//                 className="w-8 h-8 rounded-full object-cover mr-2"
//               />
//               <span className="text-sm font-medium text-red-400">피싱범</span>
//             </>
//           )}

//           {isVictim && selectedCharacter && (
//             <>
//               {victimImageUrl ? (
//                 <img
//                   src={victimImageUrl}
//                   alt={selectedCharacter.name}
//                   className="w-8 h-8 rounded-full object-cover mr-2"
//                 />
//               ) : (
//                 <span className="text-lg mr-2">
//                   {selectedCharacter.avatar || "👤"}
//                 </span>
//               )}
//               <span className="text-sm font-medium text-blue-400">
//                 {selectedCharacter.name}
//               </span>
//             </>
//           )}
//         </div>

//         {/* 속마음 */}
//         {thoughts && (
//           <div
//             className="mb-3 p-3 rounded-xl border border-dashed text-sm"
//             style={{ borderColor: risk.border, color: risk.text }}
//           >
//             💭 {thoughts}
//           </div>
//         )}

//         {/* 대화 */}
//         <div className="px-4 py-2 bg-[#1f2937] rounded-xl text-sm leading-relaxed">
//           💬 {dialogue}
//         </div>

//         {/* 설득도 */}
//         {isVictim && convincedPct !== null && (
//           <div className="mt-2 flex items-center gap-2">
//             <div className="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
//               <div
//                 className="h-full transition-all duration-700 ease-in-out"
//                 style={{ width: `${convincedPct}%`, backgroundColor: risk.text }}
//               />
//             </div>
//             <span className="text-xs" style={{ color: risk.text }}>
//               {convincedPct}%
//             </span>
//           </div>
//         )}

//         {/* 타임스탬프 */}
//         <div className="text-xs text-right mt-2 opacity-70" style={{ color: COLORS.sub }}>
//           {message.timestamp}
//         </div>
//       </div>
//     </div>
//   );
// }


// // src/MessageBubble.jsx
// import { useEffect, useState } from "react";

// /** 설득도에 따른 색상 팔레트 계산 */
// function getRiskColors(pct) {
//   const v = Math.max(0, Math.min(100, Number(pct) || 0));
//   if (v >= 70)
//     return {
//       border: "rgba(239,68,68,0.75)",
//       bg: "rgba(239,68,68,0.10)",
//       text: "#EF4444",
//       tagBg: "rgba(239,68,68,0.12)",
//     };
//   if (v >= 41)
//     return {
//       border: "rgba(245,158,11,0.75)",
//       bg: "rgba(245,158,11,0.10)",
//       text: "#F59E0B",
//       tagBg: "rgba(245,158,11,0.12)",
//     };
//   return {
//     border: "rgba(16,185,129,0.75)",
//     bg: "rgba(16,185,129,0.10)",
//     text: "#10B981",
//     tagBg: "rgba(16,185,129,0.12)",
//   };
// }

// export default function MessageBubble({
//   message,
//   selectedCharacter,
//   victimImageUrl,
//   COLORS,
// }) {
//   const isVictim = message.sender === "victim";
//   const isScammer = message.sender === "offender";
//   const isSystem = message.type === "system";
//   const [convincedPct, setConvincedPct] = useState(null);
//   const [parsed, setParsed] = useState({
//     dialogue: message.content || "",
//     thoughts: null,
//     convinced: null,
//   });

//   /** 피해자 메시지 JSON 파싱 */
//   useEffect(() => {
//     try {
//       if (
//         isVictim &&
//         typeof message.content === "string" &&
//         message.content.trim().startsWith("{")
//       ) {
//         const parsed = JSON.parse(message.content);
//         setParsed({
//           dialogue: parsed.dialogue ?? "",
//           thoughts: parsed.thoughts ?? null,
//           convinced: parsed.is_convinced ?? null,
//         });
//         setConvincedPct(parsed.is_convinced * 10); // 1~10 scale → %
//       } else {
//         setParsed({
//           dialogue: message.content,
//           thoughts: null,
//           convinced: null,
//         });
//       }
//     } catch (err) {
//       console.warn("피해자 메시지 파싱 실패:", err);
//       setParsed({
//         dialogue: message.content,
//         thoughts: null,
//         convinced: null,
//       });
//     }
//   }, [message, isVictim]);

//   const risk = getRiskColors(convincedPct ?? 0);

//   /** --------------------------- 렌더링 --------------------------- */
//   return (
//     <div
//       className={`flex ${
//         isVictim ? "justify-end" : isScammer ? "justify-start" : "justify-center"
//       } mb-5`}
//     >
//       <div
//         className="max-w-md lg:max-w-lg px-5 py-3 rounded-2xl border transition-all duration-300"
//         style={{
//           backgroundColor: isVictim
//             ? COLORS.white
//             : isSystem
//             ? "rgba(88,101,242,.12)"
//             : "#313338",
//           color: isVictim ? COLORS.black : COLORS.text,
//           border: `1px solid ${COLORS.border}`,
//         }}
//       >
//         {/* 상단 프로필 영역 */}
//         <div className="flex items-center mb-2">
//           {/* 프로필 이미지 or 아이콘 */}
//           {isScammer && (
//             <>
//               <img
//                 src={new URL("./assets/offender_profile.png", import.meta.url).href}
//                 alt="피싱범"
//                 className="w-8 h-8 rounded-full object-cover mr-2"
//               />
//               <span className="text-sm font-medium text-red-400">피싱범</span>
//             </>
//           )}

//           {isVictim && selectedCharacter && (
//             <>
//               {victimImageUrl ? (
//                 <img
//                   src={victimImageUrl}
//                   alt={selectedCharacter.name}
//                   className="w-8 h-8 rounded-full object-cover mr-2"
//                 />
//               ) : (
//                 <span className="text-lg mr-2">{selectedCharacter.avatar ?? "👤"}</span>
//               )}
//               <span className="text-sm font-medium text-blue-400">
//                 {selectedCharacter.name}
//               </span>
//             </>
//           )}
//         </div>

//         {/* 속마음 (피해자만) */}
//         {isVictim && parsed.thoughts && (
//           <div
//             className="mb-3 p-3 rounded-xl border border-dashed text-sm leading-relaxed"
//             style={{
//               borderColor: risk.border,
//               backgroundColor: risk.bg,
//               color: risk.text,
//             }}
//           >
//             💭 {parsed.thoughts}
//           </div>
//         )}

//         {/* 실제 대화 */}
//         <div
//           className="px-4 py-3 rounded-xl"
//           style={{
//             backgroundColor: isVictim ? COLORS.white : "#27272a",
//             color: isVictim ? COLORS.black : COLORS.text,
//             boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
//           }}
//         >
//           💬 {parsed.dialogue}
//         </div>

//         {/* 설득도 바 (피해자만) */}
//         {isVictim && typeof convincedPct === "number" && (
//           <div className="mt-3 flex items-center gap-2">
//             <div className="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
//               <div
//                 className="h-full transition-all duration-700 ease-in-out"
//                 style={{
//                   width: `${convincedPct}%`,
//                   backgroundColor:
//                     convincedPct >= 70
//                       ? "#EF4444"
//                       : convincedPct >= 40
//                       ? "#F59E0B"
//                       : "#10B981",
//                 }}
//               />
//             </div>
//             <span className="text-xs opacity-70">{convincedPct}%</span>
//           </div>
//         )}

//         {/* 타임스탬프 */}
//         <div className="text-xs mt-2 opacity-70 text-right" style={{ color: COLORS.sub }}>
//           {message.timestamp}
//         </div>
//       </div>
//     </div>
//   );
// }
