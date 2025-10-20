// src/hooks/useSimStream.js
import { useState, useCallback } from "react";
import { streamReactSimulation } from "../lib/streamReactSimulation";

export function useSimStream(setMessages) {
  const [logs, setLogs] = useState([]);
  const [messages, setLocalMessages] = useState([]);
  const [judgement, setJudgement] = useState(null);
  const [guidance, setGuidance] = useState(null);
  const [prevention, setPrevention] = useState(null);
  const [running, setRunning] = useState(false);

  const start = useCallback(async (payload) => {
    if (running) return;
    setRunning(true);
    setLogs([]);
    setJudgement(null);
    setGuidance(null);
    setPrevention(null);

    for await (const ev of streamReactSimulation(payload)) {
      console.log("[SSE Event]", ev);

      // ✅ 1. 터미널 로그 이벤트 (기존 유지)
      if (["log", "terminal", "agent_action"].includes(ev.type)) {
        setLogs((prev) => [...prev, ev.content || JSON.stringify(ev)]);
      }

      // ✅ 2. 단일 메시지 이벤트 (기존 유지)
      else if (ev.type === "new_message") {
        const content = ev.content || ev.message || "";
        if (!content.trim()) continue;
        const role = (ev.role || "offender").toLowerCase();

        const newMsg = {
          sender: role,
          role,
          type: "chat",
          side: role === "offender" ? "left" : "right",
          content,
          timestamp: new Date().toLocaleTimeString(),
        };

        setLocalMessages((prev) => [...prev, newMsg]);
        if (setMessages) setMessages((prev) => [...prev, newMsg]);
      }

      // ✅ 3. conversation_log (대화 turn 전체)
      else if (ev.type === "conversation_log") {
        try {
          const data = ev.data || ev;
          const turns = data.turns || data?.data?.turns || [];
          if (!Array.isArray(turns) || turns.length === 0) continue;

          // 🔍 전체 구조 출력
          console.log("🎯 [DEBUG] 대화 턴 전체 구조:", turns);

          // 🔍 각 턴별 대화 요약 출력
          turns.forEach((t, i) => {
            try {
              if (t.role === "offender") {
                console.log(`🔴 [피싱범 #${i + 1}]`, t.text);
              } else if (t.role === "victim") {
                let parsed = {};
                try {
                  parsed = JSON.parse(t.text);
                } catch {
                  parsed = { dialogue: t.text };
                }
                console.log(
                  `🟢 [피해자 #${i + 1}]`,
                  "\n대화:", parsed.dialogue,
                  "\n속마음:", parsed.thoughts,
                  "\n설득도:", parsed.is_convinced
                );
              }
            } catch (innerErr) {
              console.error("⚠️ 개별 턴 파싱 오류:", innerErr, t);
            }
          });

          // ✅ MessageBubble용 객체 생성
          const newMsgs = turns.map((t) => {
            const isVictim = t.role === "victim";
            let dialogueText = t.text;
            let thoughts = null;
            let convinced = null;

            if (isVictim) {
              try {
                const parsed = JSON.parse(t.text);
                dialogueText = parsed.dialogue || "";
                thoughts = parsed.thoughts || null;
                convinced = parsed.is_convinced || null;
              } catch {
                // JSON 파싱 실패 시 원문 그대로 사용
              }
            }

            return {
              sender: t.role,
              role: t.role,
              type: "chat",
              side: isVictim ? "right" : "left",
              content: dialogueText,
              thoughts,
              convinced,
              timestamp: new Date().toLocaleTimeString(),
            };
          });

          // ✅ 상태 업데이트
          setLocalMessages((prev) => [...prev, ...newMsgs]);
          if (setMessages) setMessages((prev) => [...prev, ...newMsgs]);
        } catch (err) {
          console.error("❌ conversation_log 파싱 실패:", err, ev);
        }
      }

      // ✅ 4. 분석 결과 이벤트 (기존 유지)
      else if (ev.type === "judgement") setJudgement(ev);
      else if (ev.type === "guidance_generated") setGuidance(ev);
      else if (ev.type === "prevention_tip") setPrevention(ev);

      // ✅ 5. 종료 이벤트
      else if (["run_end", "error"].includes(ev.type)) {
        setRunning(false);
        break;
      }
    }

    setRunning(false);
  }, [running, setMessages]);

  return { logs, messages, start, running, judgement, guidance, prevention };
}



// src/hooks/useSimStream.js ===> 터미널 로그는 작동되는 코드임!!!!
// import { useState, useCallback } from "react";
// import { streamReactSimulation } from "../lib/streamReactSimulation";

// export function useSimStream(setMessages) {
//   const [logs, setLogs] = useState([]);
//   const [messages, setLocalMessages] = useState([]);
//   const [judgement, setJudgement] = useState(null);
//   const [guidance, setGuidance] = useState(null);
//   const [prevention, setPrevention] = useState(null);
//   const [running, setRunning] = useState(false);

//   const start = useCallback(async (payload) => {
//     if (running) return;
//     setRunning(true);
//     setLogs([]);
//     setJudgement(null);
//     setGuidance(null);
//     setPrevention(null);

//     for await (const ev of streamReactSimulation(payload)) {
//       console.log("[SSE Event]", ev);

//       if (["log", "terminal", "agent_action"].includes(ev.type)) {
//         setLogs((prev) => [...prev, ev.content || JSON.stringify(ev)]);
//       }
//       else if (ev.type === "new_message") {
//         const content = ev.content || ev.message || "";
//         if (!content.trim()) continue;
//         const role = (ev.role || "offender").toLowerCase();

//         const newMsg = {
//           sender: role,
//           role,
//           type: "chat",
//           side: role === "offender" ? "left" : "right",
//           content,
//           timestamp: new Date().toLocaleTimeString(),
//         };

//         setLocalMessages((prev) => [...prev, newMsg]);
//         if (setMessages) setMessages((prev) => [...prev, newMsg]);
//       }
//       else if (ev.type === "judgement") setJudgement(ev);
//       else if (ev.type === "guidance_generated") setGuidance(ev);
//       else if (ev.type === "prevention_tip") setPrevention(ev);
//       else if (["run_end", "error"].includes(ev.type)) {
//         setRunning(false);
//         break;
//       }
//     }
//     setRunning(false);
//   }, [running, setMessages]);

//   return { logs, messages, start, running, judgement, guidance, prevention };
// }


// // src/hooks/useSimStream.js
// import { useEffect, useState, useCallback } from "react";
// import { streamReactSimulation } from "../lib/streamReactSimulation";

// const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
// const API_BASE = RAW_API_BASE.replace(/\/$/, "");
// const API_PREFIX = "/api";
// export const API_ROOT = `${API_BASE}${API_PREFIX}`;

// export function useSimStream(setMessages) {
//   const [logs, setLogs] = useState([]);
//   const [judgement, setJudgement] = useState(null);
//   const [guidance, setGuidance] = useState(null);
//   const [prevention, setPrevention] = useState(null);
//   const [running, setRunning] = useState(false);

//   const start = useCallback(
//     async (payload) => {
//       if (running) return;
//       setRunning(true);
//       setLogs([]);
//       setJudgement(null);
//       setGuidance(null);
//       setPrevention(null);
//       if (setMessages) setMessages([]); // 🔹 초기화

//       for await (const ev of streamReactSimulation(payload)) {
//         console.log("[SSE Event]", ev);

//         if (["log", "terminal", "agent_action"].includes(ev.type)) {
//           setLogs((prev) => [...prev, ev.content || JSON.stringify(ev)]);
//         }

//         else if (["new_message", "chat", "message"].includes(ev.type)) {
//           const content = ev.content || ev.message || "";
//           if (!content.trim()) continue;
//           const role = (ev.role || "offender").toLowerCase();

//           const newMsg = {
//             type: "chat",
//             sender: role,
//             role,
//             side: role === "offender" ? "left" : "right",
//             content,
//             timestamp: new Date().toLocaleTimeString(),
//           };

//           // ✅ 상위 messages 상태만 업데이트
//           if (setMessages) setMessages((prev) => [...prev, newMsg]);
//         }

//         else if (ev.type === "judgement") setJudgement(ev);
//         else if (ev.type === "guidance_generated") setGuidance(ev);
//         else if (ev.type === "prevention_tip") setPrevention(ev);

//         else if (["run_end", "run_end_local", "error"].includes(ev.type)) {
//           setRunning(false);
//           break;
//         }
//       }
//       setRunning(false);
//     },
//     [running, setMessages]
//   );

//   const stop = useCallback(() => {
//     setRunning(false);
//   }, []);

//   // ⚡ 백엔드 SSE 직접 구독 (optional)
//   useEffect(() => {
//     const es = new EventSource(`${API_ROOT}/simulator/stream`);
//     es.onmessage = (e) => {
//       const data = JSON.parse(e.data);

//       if (data.type === "log") setLogs((prev) => [...prev, data]);
//       if (["chat", "message"].includes(data.type)) {
//         if (setMessages)
//           setMessages((prev) => [...prev, data]);
//       }
//     };

//     return () => es.close();
//   }, [setMessages]);

//   return {
//     logs,
//     start,
//     stop,
//     running,
//     judgement,
//     guidance,
//     prevention,
//   };
// }
