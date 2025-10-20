// src/MessageBubble.jsx
import { useEffect, useState } from "react";

function getRiskColors(pct) {
  const v = Math.max(0, Math.min(100, Number(pct) || 0));
  if (v >= 70) return { text: "#EF4444", border: "#EF4444" };
  if (v >= 41) return { text: "#F59E0B", border: "#F59E0B" };
  return { text: "#10B981", border: "#10B981" };
}

export default function MessageBubble({ message, selectedCharacter, victimImageUrl, COLORS }) {
  const isVictim = message.sender === "victim";
  const isScammer = message.sender === "offender";

  const [dialogue, setDialogue] = useState("");
  const [thoughts, setThoughts] = useState(null);
  const [convincedPct, setConvincedPct] = useState(null);

  useEffect(() => {
    let d = "";
    let th = null;
    let conv = null;

    try {
      // 피해자 메시지(JSON 형태)
      if (isVictim) {
        if (typeof message.content === "object" && message.content.dialogue) {
          // 이미 파싱된 객체
          d = message.content.dialogue;
          th = message.content.thoughts;
          conv = message.content.is_convinced * 10;
        } else if (typeof message.content === "string" && message.content.trim().startsWith("{")) {
          // JSON 문자열 → 파싱
          const parsed = JSON.parse(message.content);
          d = parsed.dialogue || "";
          th = parsed.thoughts || null;
          conv = (parsed.is_convinced ?? 0) * 10;
        } else {
          // 일반 문자열
          d = message.content;
        }
      } else {
        // 공격자(피싱범) 메시지
        d = message.content;
      }
    } catch (err) {
      console.warn("피해자 메시지 파싱 실패:", err);
      d = message.content;
    }

    setDialogue(d);
    setThoughts(th);
    setConvincedPct(conv);
  }, [message, isVictim]);

  const risk = getRiskColors(convincedPct ?? 0);

  return (
    <div className={`flex ${isVictim ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className="max-w-md rounded-2xl border p-4"
        style={{
          backgroundColor: isVictim ? COLORS.white : "#2c2f33",
          color: isVictim ? COLORS.black : COLORS.text,
          borderColor: COLORS.border,
        }}
      >
        {/* 이름/프로필 */}
        <div className="flex items-center mb-2">
          {isScammer && (
            <>
              <img
                src={new URL("./assets/offender_profile.png", import.meta.url).href}
                alt="피싱범"
                className="w-8 h-8 rounded-full object-cover mr-2"
              />
              <span className="text-sm font-medium text-red-400">피싱범</span>
            </>
          )}
          {isVictim && selectedCharacter && (
            <>
              {victimImageUrl ? (
                <img
                  src={victimImageUrl}
                  alt={selectedCharacter.name}
                  className="w-8 h-8 rounded-full object-cover mr-2"
                />
              ) : (
                <span className="text-lg mr-2">{selectedCharacter.avatar || "👤"}</span>
              )}
              <span className="text-sm font-medium text-blue-400">
                {selectedCharacter.name}
              </span>
            </>
          )}
        </div>

        {/* 속마음 */}
        {thoughts && (
          <div
            className="mb-3 p-3 rounded-xl border border-dashed text-sm"
            style={{ borderColor: risk.border, color: risk.text }}
          >
            💭 {thoughts}
          </div>
        )}

        {/* 대화 */}
        <div className="px-4 py-2 bg-[#1f2937] rounded-xl text-sm leading-relaxed">
          💬 {dialogue}
        </div>

        {/* 설득도 바 */}
        {isVictim && convincedPct !== null && (
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
              <div
                className="h-full transition-all duration-700 ease-in-out"
                style={{ width: `${convincedPct}%`, backgroundColor: risk.text }}
              />
            </div>
            <span className="text-xs" style={{ color: risk.text }}>
              {convincedPct}%
            </span>
          </div>
        )}

        {/* 타임스탬프 */}
        <div className="text-xs text-right mt-2 opacity-70" style={{ color: COLORS.sub }}>
          {message.timestamp}
        </div>
      </div>
    </div>
  );
}


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
