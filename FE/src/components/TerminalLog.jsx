// src/components/TerminalLog.jsx
import React, { useMemo, useEffect, useRef } from "react";

const DEFAULT_THEME = {
  bg: "#1e1e1e",          // VSCode terminal 배경
  panel: "#1f1f23",
  border: "#2a2a2e",
  text: "#d4d4d4",        // 기본 하양
  green: "#6A9955",       // Thought
  purple: "#C586C0",      // Action
  dim: "#808080",         // 보조 텍스트
  black: "#000000",
};

export default function TerminalLog({ data }) {
  const theme = DEFAULT_THEME;
  const logRef = useRef(null);

  // 문자열을 줄 단위로 쪼개기
  const lines = useMemo(() => {
    if (!data) return [];
    return String(data).split(/\r?\n/);
  }, [data]);

  // 처음 로드 시 맨 위로 스크롤
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = 0;
    }
  }, [data]);

  return (
    <div
      className="rounded-2xl border overflow-hidden shadow-lg"
      style={{
        background: `linear-gradient(180deg, ${theme.bg} 0%, ${theme.panel} 100%)`,
        borderColor: theme.border,
        boxShadow: `0 8px 30px ${theme.black}55, inset 0 1px 0 ${theme.black}40`,
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* 상단 바 (맥북 VSCode 터미널 느낌) */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b"
        style={{ borderColor: theme.border, backgroundColor: theme.panel }}
      >
        <div className="flex items-center gap-2">
          <span
            style={{ background: "#ff5f56" }}
            className="w-3 h-3 rounded-full inline-block"
          />
          <span
            style={{ background: "#ffbd2e" }}
            className="w-3 h-3 rounded-full inline-block"
          />
          <span
            style={{ background: "#27c93f" }}
            className="w-3 h-3 rounded-full inline-block"
          />
        </div>
        <span
          style={{
            color: theme.dim,
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
            fontSize: 12,
          }}
        >
          simulator • stream
        </span>
      </div>

      {/* 로그 영역 */}
      <div
        ref={logRef}
        className="px-4 py-3 overflow-auto font-mono text-sm"
        style={{
          flex: 1,
          color: theme.text,
          lineHeight: "1.5",
          whiteSpace: "pre-wrap",
          tabSize: 2,
        }}
      >
        {lines.map((line, i) => {
          const trimmed = line.trimStart();
          let color = theme.text;
          let glyph = "▸";
          let glyphColor = theme.dim;

          if (trimmed.startsWith("Thought")) {
            color = theme.green;
            glyph = "●";
            glyphColor = theme.green;
          } else if (trimmed.startsWith("Action")) {
            color = theme.purple;
            glyph = "◆";
            glyphColor = theme.purple;
          }

          return (
            <div key={`${i}-${line.slice(0, 12)}`} className="flex">
              <span
                aria-hidden
                style={{
                  color: glyphColor,
                  width: 16,
                  display: "inline-block",
                  textAlign: "center",
                  marginRight: 6,
                }}
              >
                {glyph}
              </span>
              <span style={{ color }}>{line || "\u00A0"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// // src/components/TerminalLog.jsx
// import React, { useMemo, useEffect, useRef } from "react";

// export default function TerminalLog({ data }) {
//   const logRef = useRef(null);

//   const coloredLines = useMemo(() => {
//     const lines = (data || "").split(/\r?\n/);

//     return lines.map((raw, idx) => {
//       const normalized = raw.replace(/^[\s\u00A0\uFEFF]+/, "");
//       let color = "#ffffff"; // 기본: 하양

//       if (/^Thought\b/i.test(normalized)) {
//         color = "#21c55d"; // 초록
//       } else if (/^Action\b/i.test(normalized)) {
//         color = "#ba68c8"; // 보라
//       }

//       return (
//         <div key={idx} style={{ color, whiteSpace: "pre-wrap" }}>
//           {raw}
//         </div>
//       );
//     });
//   }, [data]);

//   // 처음 열 때 맨 위로 보이게
//   useEffect(() => {
//     if (logRef.current) {
//       logRef.current.scrollTop = 0;
//     }
//   }, [data]);

//   return (
//     <div
//       className="flex flex-col rounded-lg overflow-hidden shadow-lg"
//       style={{
//         backgroundColor: "#1e1e1e",
//         height: "100%",
//         border: "1px solid #2a2a2a",
//       }}
//     >
//       {/* 🔴🟡🟢 맥북 스타일 윈도우 버튼 바 */}
//       <div
//         className="flex items-center gap-2 px-3 py-2"
//         style={{
//           backgroundColor: "#2d2d2d",
//           borderBottom: "1px solid #2a2a2a",
//         }}
//       >
//         <span
//           className="w-3 h-3 rounded-full"
//           style={{ backgroundColor: "#ff5f56" }}
//         />
//         <span
//           className="w-3 h-3 rounded-full"
//           style={{ backgroundColor: "#ffbd2e" }}
//         />
//         <span
//           className="w-3 h-3 rounded-full"
//           style={{ backgroundColor: "#27c93f" }}
//         />
//         <span className="ml-3 text-xs text-gray-400 font-mono">
//           bash — vscode
//         </span>
//       </div>

//       {/* 로그 출력 영역 */}
//       <div
//         ref={logRef}
//         className="font-mono text-sm p-3 overflow-y-auto"
//         style={{
//           color: "#ffffff",
//           flex: 1,
//           lineHeight: 1.6,
//         }}
//       >
//         {coloredLines}
//       </div>
//     </div>
//   );
// }





// import React, { useEffect, useMemo, useRef } from "react";

// const DEFAULT_THEME = {
//   bg: "#1e1e1e",          // VSCode terminal 배경
//   panel: "#1f1f23",
//   border: "#2a2a2e",
//   text: "#d4d4d4",        // 기본 하양
//   green: "#6A9955",       // Thought
//   purple: "#C586C0",      // Action
//   dim: "#808080",         // 보조 텍스트
//   black: "#000000",
// };

// function classify(line) {
//   const trimmed = line.trimStart();
//   if (trimmed.startsWith("Thought:")) return "thought";
//   if (trimmed.startsWith("Action:")) return "action";
//   return "plain";
// }

// export default function TerminalLog({
//   data,           // string | string[]
//   height = 420,   // px
//   COLORS,         // 선택: 프로젝트 컬러 오버라이드
//   autoScroll = true,
//   className = "",
// }) {
//   const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };
//   const wrapRef = useRef(null);

//   // 문자열/배열 모두 지원
//   const lines = useMemo(() => {
//     if (!data) return [];
//     if (Array.isArray(data)) {
//       return data.flatMap(s => String(s).split(/\r?\n/));
//     }
//     return String(data).split(/\r?\n/);
//   }, [data]);

//   // 새 라인이 추가되면 맨 아래로 스크롤
//   useEffect(() => {
//     if (!autoScroll) return;
//     const el = wrapRef.current;
//     if (!el) return;
//     el.scrollTop = el.scrollHeight;
//   }, [lines.length, autoScroll]);

//   return (
//     <div
//       className={`rounded-2xl border overflow-hidden ${className}`}
//       style={{
//         background: `linear-gradient(180deg, ${theme.bg} 0%, ${theme.panel} 100%)`,
//         borderColor: theme.border,
//         boxShadow: `0 8px 30px ${theme.black}55, inset 0 1px 0 ${theme.black}40`,
//       }}
//     >
//       {/* 헤더 바 (VSCode 터미널 캡 느낌) */}
//       <div
//         className="flex items-center justify-between px-4 py-2 border-b"
//         style={{ borderColor: theme.border, backgroundColor: theme.panel }}
//       >
//         <div className="flex items-center gap-2">
//           <span style={{ background: "#ff5f56" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#ffbd2e" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#27c93f" }} className="w-3 h-3 rounded-full inline-block" />
//         </div>
//         <span style={{ color: theme.dim, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace", fontSize: 12 }}>
//           simulator • stream
//         </span>
//       </div>

//       {/* 본문 */}
//       <div
//         ref={wrapRef}
//         className="px-4 py-3 overflow-auto"
//         style={{
//           height,
//           color: theme.text,
//           fontFamily:
//             "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
//           fontSize: 13,
//           lineHeight: "1.5",
//           whiteSpace: "pre-wrap",
//           tabSize: 2,
//         }}
//       >
//         {lines.map((line, i) => {
//           const kind = classify(line);
//           const color =
//             kind === "thought" ? theme.green :
//             kind === "action" ? theme.purple :
//             theme.text;

//           // VSCode 터미널 느낌의 앞쪽 프롬프트 표시(선택적)
//           const showPrompt = kind !== "plain";
//           const promptGlyph = kind === "thought" ? "●" : kind === "action" ? "◆" : "▸";
//           const promptColor =
//             kind === "thought" ? theme.green :
//             kind === "action" ? theme.purple :
//             theme.dim;

//           return (
//             <div key={`${i}-${line.slice(0, 12)}`} className="flex">
//               <span
//                 aria-hidden
//                 style={{
//                   color: promptColor,
//                   width: 16,
//                   display: "inline-block",
//                   textAlign: "center",
//                   marginRight: 6,
//                 }}
//               >
//                 {showPrompt ? promptGlyph : " "}
//               </span>
//               <span style={{ color }}>{line || "\u00A0"}</span>
//             </div>
//           );
//         })}
//       </div>
//     </div>
//   );
// }