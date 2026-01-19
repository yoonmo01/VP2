// src/lib/streamReactSimulation.js
// SSE 스트림 함수 정의 (generator 기반)
import { v4 as uuid } from "uuid";

let __activeES = null;
let __activeStreamId = null;
let __ended = false; // 브라우저 자동 재연결/중복 close 방지 플래그

const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_PREFIX = "/api";
export const API_ROOT = `${API_BASE}${API_PREFIX}`;

// ANSI 컬러코드 제거
const stripAnsi = (s = "") => String(s).replace(/\x1B\[[0-9;]*m/g, "");
// "Finished chain" 포함 여부
const containsFinishedChain = (text = "") => /\bFinished chain\b/i.test(stripAnsi(text));

function buildQuery(obj = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    p.set(k, String(v));
  }
  return p.toString();
}

// 외부에서 강제 종료가 필요할 때 호출할 수 있도록 export
export function closeActiveStream(reason = "manual_close") {
  try { if (__activeES) __activeES.close(); } catch {}
  __activeES = null;
  __activeStreamId = null;
  __ended = true;
}

export function getActiveStreamId() {
  return __activeStreamId;
}

export async function* streamReactSimulation(payload = {}) {
  // ① stream_id 고정(한 번의 실행 동안 유지)
  const streamId = payload.stream_id ?? (__activeStreamId || (__activeStreamId = uuid()));
  const withId = { ...payload, stream_id: streamId };
  const url = `${API_ROOT}/react-agent/simulation/stream?${buildQuery(withId)}`;

  console.log('🚀 [streamReactSimulation] SSE 연결:', url);

  // ② 기존 열린 SSE가 있으면 닫기(중복 연결 방지)
  if (__activeES) { try { __activeES.close(); } catch {} }
  const es = new EventSource(url);
  __activeES = es;
  __ended = false;

  const queue = [];
  let notify;
  let done = false;

  const push = (data) => {
    console.log('📥 [push] 큐에 추가:', data?.type || typeof data);
    queue.push(data);
    if (notify) { notify(); notify = undefined; }
  };

  // 로컬 종료 헬퍼: 소비측(for-await)도 종료를 감지할 수 있게 신호를 밀어줌
  const endStream = (reason = "finished_chain") => {
    if (__ended) return;
    __ended = true;
    done = true;
    try { if (__activeES) __activeES.close(); } catch {}
    __activeES = null;
    __activeStreamId = null;
    // 소비측에 로컬 종료 이벤트 알림
    push({ type: "run_end_local", content: { reason }, ts: new Date().toISOString() });
  };

  // ③ 모든(또는 필요한) 이벤트 타입 등록
  // 백엔드에서 실제로 쏘는 이벤트 이름을 여기 반드시 반영
  const types = [
    "run_start",
    "log",
    "terminal",
    "agent_action",
    "tool_observation",
    "new_message",
    "case_created",
    "round_start",
    "simulation_progress",
    "conversation_logs",
    "conversation_log",
    "round_complete",
    "judgement",
    "guidance_generated",
    "prevention_tip",
    "result",
    "debug",
    "run_end",
    "error",
    "ping",
    "heartbeat",
  ];

  console.log('🎯 [EventSource] 리스너 등록:', types);

  es.onopen = () => {
    console.log('✅ [EventSource] 연결 성공!');
  };

  // 기본 message 채널도 받기(서버가 event: 를 명시 안할 수도 있음)
  es.onmessage = (e) => {
    if (__ended) return;
    let data = null;
    try { data = JSON.parse(e.data); } catch { data = e.data; }
    push(data);
    // 터미널/로그가 기본 채널로 들어오는 경우에도 종료 감지
    const t = (data?.type || "").toLowerCase();
    const content = typeof data === "string"
      ? data
      : (typeof data?.content === "string" ? data.content : (data?.content?.message ?? ""));
    if (t === "terminal" || t === "log" || typeof data === "string") {
      if (containsFinishedChain(content || data)) endStream("finished_chain");
    }
  };

  types.forEach((t) => {
    es.addEventListener(t, (e) => {
      console.log(`📨 [${t}] 이벤트 수신!`);
      if (__ended) return;
      let data = null;
      try { data = JSON.parse(e.data); } catch { data = e.data; }
      // type 보정
      if (data && typeof data === "object" && !data.type) data.type = t;

      // ✅ 디버깅 6: conversation_log 특별 표시
      if (t === "conversation_log") {
        console.log('🎯🎯🎯 [conversation_log] 감지!!!', data);
      }

      push(data);

      const content = typeof data === "string"
        ? data
        : (typeof data?.content === "string" ? data.content : (data?.content?.message ?? ""));

      // 명시적 종료 이벤트
      if (t === "run_end") { endStream("run_end_event"); return; }
      if (t === "error")   { endStream("error"); return; }
      // 터미널 로그에서 "Finished chain" 감지
      if ((t === "terminal" || t === "log") && containsFinishedChain(content || "")) {
        endStream("finished_chain");
        return;
      }
    });
  });

  // 브라우저 자동 재연결 루프 차단: 에러 시 즉시 종료
  es.onerror = () => {
    if (!__ended) {
      push({ type: "error", message: "SSE connection lost" });
      endStream("error_or_server_closed");
    }
  };

  try {
    while (!done) {
      if (queue.length === 0) {
        await new Promise((r) => (notify = r));
      }
      while (queue.length) {
        const ev = queue.shift();
         console.log('⬆️ [yield] 이벤트 반환:', ev?.type);
        yield ev;
        // UI 반영 텀 (토큰/이벤트 과밀 시 렌더 몰림 방지)
        await new Promise((r) => setTimeout(r, 30));
        if (ev?.type === "run_end" || ev?.type === "run_end_local" || ev?.type === "error") {
          endStream(ev?.type || "finished_chain");
          break;
        }
      }
    }
  } finally {
    try { if (__activeES) es.close(); } catch {}
    __activeES = null;
    __activeStreamId = null;
    __ended = false; // 다음 실행 대비 리셋
  }
}


// src/lib/streamReactSimulation.js
// import { v4 as uuid } from "uuid";

// let __activeES = null;
// let __activeStreamId = null;

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

//   const types = [
//     "log","terminal","agent_action","judgement","guidance","prevention",
//     "conversation_log","new_message","run_start","run_end","error"
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
//       if (!queue.length) await new Promise((r) => (notify = r));
//       while (queue.length) {
//         yield queue.shift();
//         await new Promise((r) => setTimeout(r, 50)); // UI tick
//       }
//     }
//   } finally {
//     try { if (__activeES) es.close(); } catch {}
//     __activeES = null;
//     __activeStreamId = null;
//   }
// }

// =======================================

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
