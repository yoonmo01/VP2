// src/lib/streamReactSimulation.js
import { v4 as uuid } from "uuid";

let __activeES = null;
let __activeStreamId = null;

const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_PREFIX = "/api";
export const API_ROOT = `${API_BASE}${API_PREFIX}`;

export async function* streamReactSimulation(payload = {}) {
  const streamId = payload.stream_id ?? (__activeStreamId || (__activeStreamId = uuid()));
  const params = new URLSearchParams({ ...payload, stream_id: streamId });
  const url = `${API_ROOT}/react-agent/simulation/stream?${params.toString()}`;

  if (__activeES) try { __activeES.close(); } catch {}
  const es = new EventSource(url);
  __activeES = es;

  const queue = [];
  let notify;
  let done = false;

  const push = (data) => {
    queue.push(data);
    if (notify) { notify(); notify = undefined; }
  };

  const types = [
    "log","terminal","agent_action","judgement","guidance","prevention",
    "conversation_log","new_message","run_start","run_end","error"
  ];

  types.forEach((t) => {
    es.addEventListener(t, (e) => {
      try { push(JSON.parse(e.data)); }
      catch { push({ type: t, content: e.data }); }
      if (t === "run_end" || t === "error") done = true;
    });
  });

  es.onerror = () => {
    push({ type: "error", message: "SSE connection lost" });
    done = true;
  };

  try {
    while (!done) {
      if (!queue.length) await new Promise((r) => (notify = r));
      while (queue.length) {
        yield queue.shift();
        await new Promise((r) => setTimeout(r, 50)); // UI tick
      }
    }
  } finally {
    try { if (__activeES) es.close(); } catch {}
    __activeES = null;
    __activeStreamId = null;
  }
}

// src/lib/streamReactSimulation.js
// import { v4 as uuid } from "uuid";

// let __activeES = null;
// let __activeStreamId = null;
// let __ended = false;

// const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
// const API_BASE = RAW_API_BASE.replace(/\/$/, "");
// const API_PREFIX = "/api";
// export const API_ROOT = `${API_BASE}${API_PREFIX}`;

// /**
//  * streamReactSimulation
//  * - SSE 스트림을 consume하는 async generator
//  * - 각 이벤트를 yield로 전달해 useSimStream에서 실시간 처리
//  */
// export async function* streamReactSimulation(payload = {}) {
//   const streamId =
//     payload.stream_id ?? (__activeStreamId || (__activeStreamId = uuid()));
//   const params = new URLSearchParams({ ...payload, stream_id: streamId });
//   const url = `${API_ROOT}/react-agent/simulation/stream?${params.toString()}`;

//   // 기존 연결 종료
//   if (__activeES) {
//     try {
//       __activeES.close();
//     } catch {
//         // intentionally ignored
//     }
//   }

//   const es = new EventSource(url);
//   __activeES = es;

//   const queue = [];
//   let notify;
//   let done = false;

//   const push = (data) => {
//     queue.push(data);
//     if (notify) {
//       notify();
//       notify = undefined;
//     }
//   };

//   // ✅ 모든 이벤트 타입 등록
//   const types = [
//     "log",
//     "terminal",
//     "agent_action",
//     "tool_observation",
//     "judgement",
//     "guidance",
//     "prevention",
//     "conversation_log",
//     "chat",           // 🔹 추가
//     "message",        // 🔹 추가
//     "new_message",    // 🔹 추가
//     "run_start",
//     "run_end",
//     "error",
//   ];

//   types.forEach((t) => {
//     es.addEventListener(t, (e) => {
//       try {
//         push(JSON.parse(e.data));
//       } catch {
//         push({ type: t, content: e.data });
//       }
//       if (t === "run_end" || t === "error") done = true;
//     });
//   });

//   es.onerror = () => {
//     push({ type: "error", message: "SSE connection lost" });
//     done = true;
//   };

//   try {
//     while (!done) {
//       if (queue.length === 0) await new Promise((r) => (notify = r));
//       while (queue.length) {
//         const ev = queue.shift();
//         yield ev; // ⚡ UI에서 바로 반영
//         await new Promise((r) => setTimeout(r, 50)); // 약간의 틱
//         if (ev?.type === "run_end" || ev?.type === "error") {
//           done = true;
//           break;
//         }
//       }
//     }
//   } finally {
//     try {
//       if (__activeES) es.close();
//     } catch {
//         // intentionally ignored
//     }
//     __activeES = null;
//     __activeStreamId = null;
//     __ended = false;
//   }
// }

//=======================

// //SSE 스트림 함수 정의 (generator 기반)
// // src/lib/streamReactSimulation.js
// import { v4 as uuid } from "uuid";

// let __activeES = null;
// let __activeStreamId = null;
// let __ended = false; // ✅ 여기에 선언 필요

// const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
// const API_BASE = RAW_API_BASE.replace(/\/$/, "");
// const API_PREFIX = "/api";
// export const API_ROOT = `${API_BASE}${API_PREFIX}`;

// export async function* streamReactSimulation(payload = {}) {
//   const streamId = payload.stream_id ?? (__activeStreamId || (__activeStreamId = uuid()));
//   const params = new URLSearchParams({ ...payload, stream_id: streamId });
//   const url = `${API_ROOT}/react-agent/simulation/stream?${params.toString()}`;

//   if (__activeES) try { __activeES.close(); } catch {}
//   const es = new EventSource(url);
//   __activeES = es;

//   const queue = [];
//   let notify;
//   let done = false;

//   const push = (data) => {
//     queue.push(data);
//     if (notify) { notify(); notify = undefined; }
//   };

//   // 모든 메시지 종류에 대해 등록
//   const types = [
//     "log","terminal","agent_action","tool_observation","judgement",
//     "guidance","prevention","conversation_log","run_start","run_end","error"
//   ];
//   types.forEach((t) => {
//     es.addEventListener(t, (e) => {
//       try { push(JSON.parse(e.data)); }
//       catch { push({ type: t, content: e.data }); }
//       if (t === "run_end" || t === "error") done = true;
//     });
//   });

//   es.onerror = () => {
//     push({ type: "error", message: "SSE connection lost" });
//     done = true;
//   };

//   try {
//     while (!done) {
//       if (queue.length === 0) await new Promise((r) => (notify = r));
//       while (queue.length) {
//         const ev = queue.shift();
//         yield ev;
//         await new Promise((r) => setTimeout(r, 50)); // ⚡️ UI 반영 틱
//         if (ev?.type === "run_end" || ev?.type === "error") {
//           done = true;
//           break;
//         }
//       }
//     }
//   } finally {
//     try { if (__activeES) es.close(); } catch {// intentionally ignored}
//     __activeES = null;
//     __activeStreamId = null;
//     __ended = false;
//   }
// }
// }
