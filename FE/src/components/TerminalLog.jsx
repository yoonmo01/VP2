// src/components/TerminalLog.jsx
import React, { useEffect, useMemo, useRef } from "react";

const DEFAULT_THEME = {
  bg: "#1e1e1e",
  panel: "#1f1f23",
  border: "#2a2a2e",
  text: "#d4d4d4",
  purple: "#C586C0", // Action
  cyan: "#4FC1FF",   // Action Input
  green: "#6A9955",  // JSON
  gray: "#9CA3AF",   // 일반 텍스트
  dim: "#555",
  black: "#000",
};

/**
 * props:
 * - logs: string[] (SSE로 실시간 들어오는 로그 배열)
 * - COLORS: 테마
 */
export default function TerminalLog({
  logs = [],
  COLORS,
  autoScroll = true,
  height = 500,
  className = "",
}) {
  const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };
  const wrapRef = useRef(null);

  /** 
   * 🧩 실시간 라인 분류
   * logs는 문자열 배열 (SSE 이벤트별 content)
   * 각 라인을 색상 구분해서 렌더링
   */
  const parsedLines = useMemo(() => {
    const lines = [];
    logs.forEach((entry) => {
      if (!entry) return;
      const text =
      typeof entry === "string"
        ? entry
        : entry.content || entry.message || JSON.stringify(entry);
      const split = text.split(/\r?\n/);
      split.forEach((line) => {
        const trimmed = line.trimStart();
        if (!trimmed) return;
        if (trimmed.startsWith("Action:")) {
          lines.push({ type: "action", text: line });
        } else if (trimmed.startsWith("Action Input:")) {
          lines.push({ type: "input", text: line });
        } else if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
            try {
              const obj = JSON.parse(trimmed);
              lines.push({
                type: "json",
                text: JSON.stringify(obj, null, 2),
              });
            } catch {
              lines.push({ type: "json", text: line });
            }
        } else if (trimmed.startsWith("---") || trimmed.startsWith("===")) {
          lines.push({ type: "divider", text: line });
        } else {
          lines.push({ type: "plain", text: line });
        }
      });
    });
    return lines;
  }, [logs]);

  /** 🧭 자동 스크롤 */
   useEffect(() => {
      if (!autoScroll) return;
      const el = wrapRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }, [parsedLines, autoScroll]);

  /** 🖌️ 타입별 색상 */
  const getStyle = (type) => {
    switch (type) {
      case "action":
        return { color: theme.purple, fontWeight: 600 };
      case "input":
        return { color: theme.cyan };
      case "json":
        return {
          color: theme.green,
          fontFamily: "monospace",
          whiteSpace: "pre-wrap",
        };
      case "divider":
        return {
          color: theme.dim,
          fontStyle: "italic",
          borderBottom: `1px solid ${theme.border}`,
          margin: "6px 0",
        };
      default:
        return { color: theme.gray };
    }
  };

  return (
    <div
      className={`rounded-2xl border overflow-hidden shadow-lg flex flex-col ${className}`}
      style={{
        background: `linear-gradient(180deg, ${theme.bg} 0%, ${theme.panel} 100%)`,
        borderColor: theme.border,
        boxShadow: `0 8px 30px ${theme.black}55, inset 0 1px 0 ${theme.black}40`,
        // display: "flex",
        // flexDirection: "column",
        flex: 1,   
        height: "100%",
      }}
    >
      {/* 헤더 */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b"
        style={{ borderColor: theme.border, backgroundColor: theme.panel }}
      >
        <div className="flex items-center gap-2">
          <span style={{ background: "#ff5f56" }} className="w-3 h-3 rounded-full inline-block" />
          <span style={{ background: "#ffbd2e" }} className="w-3 h-3 rounded-full inline-block" />
          <span style={{ background: "#27c93f" }} className="w-3 h-3 rounded-full inline-block" />
        </div>
        <span
          style={{
            color: theme.dim,
            fontSize: 12,
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace",
          }}
        >
          agent • terminal-stream
        </span>
      </div>

      {/* 본문 */}
      <div
        ref={wrapRef}
        // className="px-4 py-3 overflow-auto"
        className="flex-1 px-4 py-3 overflow-auto"
        style={{
          // height,
          color: theme.text,
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace",
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        {parsedLines.length === 0 ? (
          <p style={{ color: theme.dim }}>No logs available</p>
        ) : (
          parsedLines.map((line, i) => (
            <div key={i} style={getStyle(line.type)}>
              {line.text || "\u00A0"}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// import React, { useMemo, useEffect, useRef } from "react";

// const THEME = {
//   bg: "#0D1117",
//   panel: "#161B22",
//   border: "#30363D",
//   text: "#C9D1D9",
//   gray: "#8B949E",
//   info: "#58A6FF",
//   warn: "#E3B341",
//   error: "#F85149",
//   offender: "#FF7B72",
//   victim: "#3FB950",
//   key: "#79C0FF",
//   number: "#D2A8FF",
//   string: "#A5D6FF",
// };

// export default function TerminalLog({ data }) {
//   const logRef = useRef(null);

//   /**
//    * ✅ data 형태 통합
//    * 문자열 | 객체 | 배열 모두 안전하게 문자열 리스트로 변환
//    */
//   const lines = useMemo(() => {
//     if (!data) return [];
//     if (Array.isArray(data)) {
//       return data.flatMap((d) => (typeof d === "object" ? [JSON.stringify(d)] : [String(d)]));
//     }
//     if (typeof data === "object") {
//       return [JSON.stringify(data)];
//     }
//     return String(data).split(/\r?\n/);
//   }, [data]);

//   /**
//    * ✅ 색상 하이라이트 (정규식 기반)
//    */
//   const highlight = (line) => {
//     let colored = line;

//     colored = colored
//       // 로그 등급
//       .replace(/\[INFO\]/g, `<span style="color:${THEME.info}">[INFO]</span>`)
//       .replace(/\[WARNING\]/g, `<span style="color:${THEME.warn}">[WARNING]</span>`)
//       .replace(/\[ERROR\]/g, `<span style="color:${THEME.error}">[ERROR]</span>`)
//       // 피싱범 / 피해자
//       .replace(/"offender"/g, `<span style="color:${THEME.offender}">"offender"</span>`)
//       .replace(/"victim"/g, `<span style="color:${THEME.victim}">"victim"</span>`)
//       // Action 구문
//       .replace(/Action:/g, `<span style="color:${THEME.warn}; font-weight:600;">Action:</span>`)
//       .replace(/Action Input:/g, `<span style="color:${THEME.info}; font-weight:600;">Action Input:</span>`)
//       // JSON 키값
//       .replace(/"(\w+)"(?=\s*:)/g, `<span style="color:${THEME.key}">"$1"</span>`)
//       // 문자열 값
//       .replace(/:\s*"([^"]*)"/g, `: <span style="color:${THEME.string}">"$1"</span>`)
//       // 숫자 값
//       .replace(/:\s*(\d+)(?=[,\n\r}])/g, `: <span style="color:${THEME.number}">$1</span>`)
//       // HTTP Request / Response
//       .replace(/HTTP Request:/g, `<span style="color:${THEME.info}">HTTP Request:</span>`)
//       .replace(/HTTP\/1\.1 500 Internal Server Error/g, `<span style="color:${THEME.error}; font-weight:600;">HTTP/1.1 500 Internal Server Error</span>`)
//       .replace(/HTTP\/1\.1 200 OK/g, `<span style="color:${THEME.victim}; font-weight:600;">HTTP/1.1 200 OK</span>`);

//     return colored;
//   };

//   /**
//    * ✅ 렌더링용 HTML
//    * 줄 단위로 각각 <div>로 감싸서 출력
//    */
//   const html = useMemo(() => {
//     return lines
//       .map(
//         (line, idx) => `
//         <div key="${idx}" style="white-space:pre-wrap; font-family:SFMono-Regular, Menlo, Consolas, monospace; line-height:1.5;">
//           ${highlight(line)}
//         </div>`
//       )
//       .join("");
//   }, [lines]);

//   /**
//    * ✅ 자동 스크롤 (새 로그 추가 시 하단으로)
//    */
//   useEffect(() => {
//     if (logRef.current) {
//       logRef.current.scrollTop = logRef.current.scrollHeight;
//     }
//   }, [html]);

//   return (
//     <div
//       className="rounded-2xl border overflow-hidden shadow-lg"
//       style={{
//         background: THEME.bg,
//         borderColor: THEME.border,
//         height: "100%",
//         display: "flex",
//         flexDirection: "column",
//       }}
//     >
//       {/* 상단 바 */}
//       <div
//         className="flex items-center justify-between px-4 py-2 border-b"
//         style={{
//           borderColor: THEME.border,
//           backgroundColor: THEME.panel,
//         }}
//       >
//         <div className="flex items-center gap-2">
//           <span style={{ background: "#ff5f56" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#ffbd2e" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#27c93f" }} className="w-3 h-3 rounded-full inline-block" />
//         </div>
//         <span
//           style={{
//             color: THEME.gray,
//             fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
//             fontSize: 12,
//           }}
//         >
//           simulator • live log stream
//         </span>
//       </div>

//       {/* 본문 로그 */}
//       <div
//         ref={logRef}
//         className="overflow-auto font-mono text-sm p-4"
//         style={{
//           color: THEME.text,
//           lineHeight: "1.5",
//           whiteSpace: "pre-wrap",
//           fontFamily: "SFMono-Regular, Menlo, Monaco, Consolas, monospace",
//         }}
//         dangerouslySetInnerHTML={{ __html: html }}
//       />
//     </div>
//   );
// }




// src/components/TerminalLog.jsx
// import React, { useMemo, useEffect, useRef } from "react";

// const DEFAULT_THEME = {
//   bg: "#0D1117",
//   panel: "#161B22",
//   border: "#30363D",
//   text: "#C9D1D9",
//   green: "#3FB950",
//   purple: "#A371F7",
//   blue: "#58A6FF",
//   yellow: "#E3B341",
//   red: "#F85149",
//   gray: "#8B949E",
//   offender: "#FF7B72",
//   victim: "#3FB950",
// };


// export default function TerminalLog({ data }) {
//   const theme = DEFAULT_THEME;
//   const logRef = useRef(null);

//   // ✅ 문자열 + 배열 데이터 모두 대응
//   const lines = useMemo(() => {
//     if (!data) return [];
//     if (Array.isArray(data)) return data;
//     return String(data).split(/\r?\n/);
//   }, [data]);

//   // ✅ 새 로그 수신 시 맨 아래로 스크롤
//   useEffect(() => {
//     if (logRef.current) {
//       logRef.current.scrollTop = logRef.current.scrollHeight;
//     }
//   }, [data]);

//   // ✅ 개별 로그 줄 렌더링 함수
//   const renderLine = (line, i) => {
//     const text = typeof line === "string" ? line : JSON.stringify(line);
//     const trimmed = text.trimStart();
//     let color = theme.text;
//     let glyph = "▸";
//     let glyphColor = theme.gray;

//     // 1️⃣ 시스템 로그 색 구분
//     if (trimmed.startsWith("[INFO]")) {
//       color = theme.gray;
//       glyph = "●";
//       glyphColor = theme.gray;
//     } else if (trimmed.startsWith("[WARNING]")) {
//       color = theme.yellow;
//       glyph = "▲";
//       glyphColor = theme.yellow;
//     } else if (trimmed.startsWith("[ERROR]")) {
//       color = theme.red;
//       glyph = "✖";
//       glyphColor = theme.red;
//     }

//     // 2️⃣ 에이전트 체인 (Thought, Action, Final)
//     else if (trimmed.startsWith("Thought")) {
//       color = theme.green;
//       glyph = "💭";
//       glyphColor = theme.green;
//     } else if (trimmed.startsWith("Action")) {
//       color = theme.purple;
//       glyph = "⚙️";
//       glyphColor = theme.purple;
//     } else if (trimmed.startsWith("Final Answer")) {
//       color = theme.blue;
//       glyph = "✅";
//       glyphColor = theme.blue;
//     }

//     // 3️⃣ 대화 로그 (offender / victim)
//     else if (trimmed.includes('"role": "offender"')) {
//       color = theme.offender;
//       glyph = "🧑‍💼";
//       glyphColor = theme.offender;
//     } else if (trimmed.includes('"role": "victim"')) {
//       color = theme.victim;
//       glyph = "🙍‍♀️";
//       glyphColor = theme.victim;
//     }

//     return (
//       <div key={`${i}-${trimmed.slice(0, 20)}`} className="flex">
//         <span
//           aria-hidden
//           style={{
//             color: glyphColor,
//             width: 20,
//             display: "inline-block",
//             textAlign: "center",
//             marginRight: 6,
//           }}
//         >
//           {glyph}
//         </span>
//         <span style={{ color, whiteSpace: "pre-wrap" }}>{trimmed || "\u00A0"}</span>
//       </div>
//     );
//   };

//   return (
//     <div
//       className="rounded-2xl border overflow-hidden shadow-lg"
//       style={{
//         background: `linear-gradient(180deg, ${theme.bg} 0%, ${theme.panel} 100%)`,
//         borderColor: theme.border,
//         boxShadow: `0 8px 30px ${theme.black}55, inset 0 1px 0 ${theme.black}40`,
//         height: "100%",
//         display: "flex",
//         flexDirection: "column",
//       }}
//     >
//       {/* 상단 바 */}
//       <div
//         className="flex items-center justify-between px-4 py-2 border-b"
//         style={{ borderColor: theme.border, backgroundColor: theme.panel }}
//       >
//         <div className="flex items-center gap-2">
//           <span style={{ background: "#ff5f56" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#ffbd2e" }} className="w-3 h-3 rounded-full inline-block" />
//           <span style={{ background: "#27c93f" }} className="w-3 h-3 rounded-full inline-block" />
//         </div>
//         <span
//           style={{
//             color: theme.gray,
//             fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
//             fontSize: 12,
//           }}
//         >
//           simulator • live stream
//         </span>
//       </div>

//       {/* 로그 본문 */}
//       <div
//         ref={logRef}
//         className="px-4 py-3 overflow-auto font-mono text-sm"
//         style={{
//           flex: 1,
//           color: theme.text,
//           lineHeight: "1.5",
//           whiteSpace: "pre-wrap",
//           tabSize: 2,
//         }}
//       >
//         {lines.map(renderLine)}
//       </div>
//     </div>
//   );
// }

// src/components/TerminalLog.jsx
// import React, { useMemo, useEffect, useRef } from "react";

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

// export default function TerminalLog({ data }) {
//   const theme = DEFAULT_THEME;
//   const logRef = useRef(null);

//   // 문자열을 줄 단위로 쪼개기
//   const lines = useMemo(() => {
//     if (!data) return [];
//     return String(data).split(/\r?\n/);
//   }, [data]);

//   // 처음 로드 시 맨 위로 스크롤
//   useEffect(() => {
//     if (logRef.current) {
//       logRef.current.scrollTop = 0;
//     }
//   }, [data]);

//   return (
//     <div
//       className="rounded-2xl border overflow-hidden shadow-lg"
//       style={{
//         background: `linear-gradient(180deg, ${theme.bg} 0%, ${theme.panel} 100%)`,
//         borderColor: theme.border,
//         boxShadow: `0 8px 30px ${theme.black}55, inset 0 1px 0 ${theme.black}40`,
//         height: "100%",
//         display: "flex",
//         flexDirection: "column",
//       }}
//     >
//       {/* 상단 바 (맥북 VSCode 터미널 느낌) */}
//       <div
//         className="flex items-center justify-between px-4 py-2 border-b"
//         style={{ borderColor: theme.border, backgroundColor: theme.panel }}
//       >
//         <div className="flex items-center gap-2">
//           <span
//             style={{ background: "#ff5f56" }}
//             className="w-3 h-3 rounded-full inline-block"
//           />
//           <span
//             style={{ background: "#ffbd2e" }}
//             className="w-3 h-3 rounded-full inline-block"
//           />
//           <span
//             style={{ background: "#27c93f" }}
//             className="w-3 h-3 rounded-full inline-block"
//           />
//         </div>
//         <span
//           style={{
//             color: theme.dim,
//             fontFamily:
//               "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
//             fontSize: 12,
//           }}
//         >
//           simulator • stream
//         </span>
//       </div>

//       {/* 로그 영역 */}
//       <div
//         ref={logRef}
//         className="px-4 py-3 overflow-auto font-mono text-sm"
//         style={{
//           flex: 1,
//           color: theme.text,
//           lineHeight: "1.5",
//           whiteSpace: "pre-wrap",
//           tabSize: 2,
//         }}
//       >
//         {lines.map((line, i) => {
//           const trimmed = line.trimStart();
//           let color = theme.text;
//           let glyph = "▸";
//           let glyphColor = theme.dim;

//           if (trimmed.startsWith("Thought")) {
//             color = theme.green;
//             glyph = "●";
//             glyphColor = theme.green;
//           } else if (trimmed.startsWith("Action")) {
//             color = theme.purple;
//             glyph = "◆";
//             glyphColor = theme.purple;
//           }

//           return (
//             <div key={`${i}-${line.slice(0, 12)}`} className="flex">
//               <span
//                 aria-hidden
//                 style={{
//                   color: glyphColor,
//                   width: 16,
//                   display: "inline-block",
//                   textAlign: "center",
//                   marginRight: 6,
//                 }}
//               >
//                 {glyph}
//               </span>
//               <span style={{ color }}>{line || "\u00A0"}</span>
//             </div>
//           );
//         })}
//       </div>
//     </div>
//   );
// }


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