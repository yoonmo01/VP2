// src/components/TTSModal.jsx
import React, { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import AudioWaveform from "./AudioWaveForm";
import SpeakerAvatar from "./SpeakerAvatar";
import DEFAULT_COLORS from "../constants/colors";
import victim from "../../src/assets/victims/1.png";
import criminal from "../../src/assets/offender01.png";

const API_BASE = "http://127.0.0.1:8000";

// 백엔드에서 온 base64 → <audio>에서 재생 가능하도록 data URL로 변환
const toUrl = (b64, mime) => {
  const clean = (b64 || "").replace(/\s/g, "");
  const pad = "=".repeat((4 - (clean.length % 4)) % 4);
  const norm = clean.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const type = !mime || mime === "audio/wav" ? "audio/wav" : mime;
  return `data:${type};base64,${norm}`;
};

export default function TTSModal({
  isOpen,
  onClose,
  COLORS,
  caseId,               // 🔥 새로 추가: TTS 생성/조회에 사용할 case_id
  availableRuns = [],   // 🔥 새로 추가: [1,2,3] 같은 run_no 목록
}) {
  const theme = COLORS ?? DEFAULT_COLORS;


  const [loading, setLoading] = useState(false);

  // run_no → { items, urls } 캐시
  const [runCache, setRunCache] = useState({});
  const [activeRun, setActiveRun] = useState(null);

  // 현재 재생 중인 run의 아이템/오디오 URL
  const [dialogue, setDialogue] = useState([]);
  const [urls, setUrls] = useState([]);
  const [idx, setIdx] = useState(-1);
  const [currentText, setCurrentText] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);

  const audioRef = useRef(null);

  // 🔥 특정 run_no에 대해:
  //   1) /api/tts/start 로 TTS 생성 요청
  //   2) /api/tts/synthesize (case_id+run_no) 폴링해서 준비되면 items/urls 반환
  const generateAndFetchRun = async (runNo) => {
    if (!caseId) {
      alert("case_id가 없어 TTS를 생성할 수 없습니다.");
      return null;
    }

    setLoading(true);
    try {
      // 1) 비동기 TTS 생성 요청
      await fetch(`${API_BASE}/api/tts/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId, run_no: runNo }),
      });

      // 2) 캐시에 생성될 때까지 synthesize 폴링
      let items = null;
      for (let attempt = 0; attempt < 15; attempt++) {
        const res = await fetch(`${API_BASE}/api/tts/synthesize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: "dialogue",
            case_id: caseId,
            run_no: runNo,
          }),
        });

        if (res.ok) {
          const data = await res.json();
          items = (data.items || []).map((it) => ({
            ...it,
            totalDurationSec: Number(it.totalDurationSec) || 0,
            charTimeSec: Number(it.charTimeSec) || 0,
          }));
          break;
        }

        // 404면 "아직 준비 안 됨" → 잠깐 기다렸다가 재시도
        if (res.status !== 404) {
          throw new Error(`HTTP ${res.status}`);
        }
        await new Promise((r) => setTimeout(r, 1000));
      }

      if (!items || items.length === 0) {
        alert("TTS 오디오가 아직 준비되지 않았습니다.");
        return null;
      }

      const urls = items.map((it) => toUrl(it.audioContent, it.contentType));

      // run별 캐시에 저장
      setRunCache((prev) => ({
        ...prev,
        [runNo]: { items, urls },
      }));

      return { items, urls };
    } catch (e) {
      console.error(e);
      alert(`TTS 생성/조회 중 오류: ${e.message}`);
      return null;
    } finally {
      setLoading(false);
    }
  };

  // 특정 인덱스 대사 재생
  const playAt = async (i, sources, itemsArr) => {
    const a = audioRef.current;
    if (!a || !sources[i] || !itemsArr[i]) return;

    const item = itemsArr[i];
    setIdx(i);
    setCurrentText(item.text || "");
    setIsPlaying(true);

    try {
      a.pause();
      a.src = sources[i];
      a.load();

      await new Promise((resolve, reject) => {
        a.addEventListener("loadedmetadata", resolve, { once: true });
        a.addEventListener("error", reject, { once: true });
        setTimeout(() => reject(new Error("timeout")), 6000);
      });

      await a.play();
    } catch (err) {
      console.warn("[playAt] error:", err);
      setIsPlaying(false);
    }
  };

  // 특정 run_no 대화 전체 재생 (버튼 클릭 시 호출)
  const playRun = async (runNo) => {
    // 이미 캐시에 있으면 그대로 사용
    let cached = runCache[runNo];

    if (!cached) {
      // 없으면 생성+조회
      const result = await generateAndFetchRun(runNo);
      if (!result) return;
      cached = result;
    }

    const selItems = cached.items;
    const selUrls = cached.urls;

    if (!selItems || selItems.length === 0) {
      alert(`${runNo}번째 대화가 비어 있습니다.`);
      return;
    }

    setActiveRun(runNo);
    setDialogue(selItems);
    setUrls(selUrls);
    setIdx(-1);
    setCurrentText("");
    setIsPlaying(false);

    await playAt(0, selUrls, selItems);
  };

  // 오디오 끝나면 다음 턴 자동 재생
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;

    const onEnded = () => {
      const next = idx + 1;
      if (next < dialogue.length) {
        playAt(next, urls, dialogue);
      } else {
        setIdx(-1);
        setCurrentText("");
        setIsPlaying(false);
      }
    };

    a.addEventListener("ended", onEnded);
    return () => a.removeEventListener("ended", onEnded);
  }, [idx, dialogue, urls]);


  if (!isOpen) return null;

  const current = idx >= 0 ? dialogue[idx] : null;
  const currentSpeaker = current?.speaker;

  // 버튼에 쓸 run 목록 (availableRuns가 우선, 없으면 캐시에 만들어진 것들)
  const runKeys =
    availableRuns && availableRuns.length > 0
      ? availableRuns
      : Object.keys(runCache);

  const WAVE_HEIGHT = 140;
  const WAVE_MAX_BAR = 120;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 어두운 배경 */}
      <div className="absolute inset-0" style={{ backgroundColor: "#00000080" }} />

      {/* 모달 박스 */}
      <div
        className="relative mx-4 rounded-3xl border overflow-hidden flex flex-col"
        style={{
          width: 900,
          height: 760,
          backgroundColor: "#020617",
          borderColor: "#334155",
        }}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-xl font-bold text-white">음성 대화 시뮬레이션</h2>
          <button onClick={onClose} className="p-1 text-slate-300">
            <X size={20} />
          </button>
        </div>

        {/* 본문 */}
        <div className="flex-1 px-8 py-6 flex flex-col overflow-hidden gap-6">
          {/* 상단 버튼 영역 */}
          <div className="flex items-center justify-between gap-3">
            {/* run_no 개수만큼 자동 생성: 1번째 대화, 2번째 대화 ... */}
            <div className="flex items-center gap-2 flex-wrap">
              {runKeys
                .sort((a, b) => Number(a) - Number(b))
                .map((runKey) => (
                  <button
                    key={runKey}
                    onClick={() => playRun(Number(runKey))}
                    disabled={loading}
                    className={`px-4 py-2 text-sm rounded-md border text-slate-100 ${
                      Number(runKey) === activeRun
                        ? "border-amber-400 bg-amber-500/20"
                        : "border-slate-600"
                    }`}
                  >
                    {runKey}번째 대화
                  </button>
                ))}
            </div>

            {/* 수동으로 새로 불러오기 */}
            <button
              onClick={() => {
                // 필요하면 "전체 다시 가져오기"용으로 확장 가능
                alert("각 라운드 버튼을 눌러 TTS를 생성/재생하세요.");
              }}
              disabled={loading}
              className="px-4 py-2 rounded-md text-sm font-semibold bg-amber-500 text-black disabled:opacity-60"
            >
              {loading ? "TTS 생성 중..." : "도움말"}
            </button>
          </div>

          {/* 파형 + 아바타 */}
          <div
            className="grid items-center"
            style={{
              gridTemplateColumns: `${WAVE_MAX_BAR + 40}px 1fr ${
                WAVE_MAX_BAR + 40
              }px`,
              columnGap: 24,
            }}
          >
            <SpeakerAvatar
              speaker="offender"
              isActive={currentSpeaker === "offender"}
              isPlaying={isPlaying}
              COLORS={theme}
              size={WAVE_MAX_BAR}
              photoSrc={criminal}
            />

            <AudioWaveform
              isActive={isPlaying}
              speaker={currentSpeaker}
              COLORS={theme}
              heightPx={WAVE_HEIGHT}
              maxBarHeight={WAVE_MAX_BAR}
            />

            <SpeakerAvatar
              speaker="victim"
              isActive={currentSpeaker === "victim"}
              isPlaying={isPlaying}
              COLORS={theme}
              size={WAVE_MAX_BAR}
              photoSrc={victim}
            />
          </div>

          {/* 현재 대사 텍스트 */}
          <div className="min-h-20 p-4 rounded-md border border-slate-700 text-center text-slate-100 flex items-center justify-center">
            {currentText || "위의 라운드 버튼을 눌러 음성 대화를 재생하세요."}
          </div>
        </div>

        <audio ref={audioRef} className="hidden" />
      </div>
    </div>
  );
}




// // src/components/TTSModal.jsx
// import React, { useEffect, useRef, useState } from "react";
// import { X, Mic } from "lucide-react";
// import AudioWaveform from "./AudioWaveForm";
// import SpeakerAvatar from "./SpeakerAvatar";
// import DEFAULT_COLORS from "../constants/colors";
// import victim from "../../src/assets/victims/1.png";
// import criminal from "../../src/assets/offender01.png";

// const API_BASE = "http://127.0.0.1:8000";

// const toUrl = (b64, mime) => {
//   const clean = (b64 || "").replace(/\s/g, "");
//   const pad = "=".repeat((4 - (clean.length % 4)) % 4);
//   const norm = clean.replace(/-/g, "+").replace(/_/g, "/") + pad;
//   const type = !mime || mime === "audio/wav" ? "audio/wav" : mime;
//   return `data:${type};base64,${norm}`;
// };

// export default function TTSModal({ isOpen, onClose, COLORS }) {
//   const theme = COLORS ?? DEFAULT_COLORS;

//   // 전체 아이템
//   const [allItems, setAllItems] = useState([]);
//   const [loading, setLoading] = useState(false);

//   // run_no → 배열로 매핑되는 객체 구조
//   const [runGroups, setRunGroups] = useState({});
//   const [runUrls, setRunUrls] = useState({});

//   // 현재 재생 상태
//   const [dialogue, setDialogue] = useState([]);
//   const [urls, setUrls] = useState([]);
//   const [idx, setIdx] = useState(-1);
//   const [currentText, setCurrentText] = useState("");
//   const [isPlaying, setIsPlaying] = useState(false);

//   const audioRef = useRef(null);

//   // ---- normalize ----
//   const normalizeItems = (items) =>
//     (items || []).map((it) => ({
//       ...it,
//       totalDurationSec: Number(it.totalDurationSec) || 0,
//       charTimeSec: Number(it.charTimeSec) || 0,
//     }));

//   // ---- run_no 동적 그룹 생성 ----
//   const splitByRun = (items) => {
//     const groups = {};
//     items.forEach((it) => {
//       const run =
//         it.run_no ??
//         it.runNo ??
//         it.round_no ??
//         it.round ??
//         1; // fallback 1

//       if (!groups[run]) groups[run] = [];
//       groups[run].push(it);
//     });
//     return groups;
//   };

//   // ---- fetch once ----
//   const ensureFetched = async () => {
//     if (allItems.length > 0) return;
//     setLoading(true);

//     try {
//       const res = await fetch(`${API_BASE}/api/tts/synthesize`, {
//         method: "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({ mode: "dialogue" }),
//       });
//       if (!res.ok) throw new Error(`HTTP ${res.status}`);

//       const data = await res.json();
//       const items = normalizeItems(data.items || []);

//       setAllItems(items);

//       const groups = splitByRun(items);
//       const urlsByRun = {};

//       Object.entries(groups).forEach(([run, arr]) => {
//         urlsByRun[run] = arr.map((it) => toUrl(it.audioContent, it.contentType));
//       });

//       setRunGroups(groups);
//       setRunUrls(urlsByRun);
//     } catch (e) {
//       alert(`TTS 오류: ${e.message}`);
//       console.error(e);
//     } finally {
//       setLoading(false);
//     }
//   };

//   // ---- playAt ----
//   const playAt = async (i, sources, itemsArr) => {
//     const a = audioRef.current;
//     if (!a || !sources[i] || !itemsArr[i]) return;

//     const item = itemsArr[i];
//     setIdx(i);
//     setCurrentText(item.text || "");
//     setIsPlaying(true);

//     try {
//       a.pause();
//       a.src = sources[i];
//       a.load();

//       await new Promise((resolve, reject) => {
//         a.addEventListener("loadedmetadata", resolve, { once: true });
//         a.addEventListener("error", reject, { once: true });
//         setTimeout(() => reject(new Error("timeout")), 6000);
//       });

//       await a.play();
//     } catch (err) {
//       console.warn("[playAt] error:", err);
//       setIsPlaying(false);
//     }
//   };

//   // ---- run_no 선택 재생 ----
//   const playRun = async (runNo) => {
//     await ensureFetched();

//     const selItems = runGroups[runNo] || [];
//     const selUrls = runUrls[runNo] || [];

//     if (selItems.length === 0) {
//       alert(`${runNo}번째 대화가 없습니다.`);
//       return;
//     }

//     setDialogue(selItems);
//     setUrls(selUrls);
//     setIdx(-1);
//     setCurrentText("");
//     setIsPlaying(false);

//     playAt(0, selUrls, selItems);
//   };

//   // ---- audio events ----
//   useEffect(() => {
//     const a = audioRef.current;
//     if (!a) return;

//     const onEnded = () => {
//       const next = idx + 1;
//       if (next < dialogue.length) {
//         playAt(next, urls, dialogue);
//       } else {
//         setIdx(-1);
//         setCurrentText("");
//         setIsPlaying(false);
//       }
//     };

//     a.addEventListener("ended", onEnded);
//     return () => a.removeEventListener("ended", onEnded);
//   }, [idx, dialogue, urls]);

//   // ---- isOpen이 false면 렌더링 막기 ----
//   if (!isOpen) return null;

//   const current = idx >= 0 ? dialogue[idx] : null;
//   const currentSpeaker = current?.speaker;

//   const WAVE_HEIGHT = 140;
//   const WAVE_MAX_BAR = 120;

//   return (
//     <div className="fixed inset-0 z-50 flex items-center justify-center">
//       <div
//         className="absolute inset-0"
//         style={{ backgroundColor: `${theme.black}CC` }}
//       />

//       <div
//         className="relative w-[900px] mx-4 rounded-3xl border overflow-hidden flex flex-col"
//         style={{
//           height: "760px",
//           background: `linear-gradient(180deg, ${theme.panel} 0%, ${theme.panelDark} 100%)`,
//           borderColor: theme.border,
//         }}
//       >
//         {/* 헤더 */}
//         <div
//           className="flex items-center justify-between px-6 py-4 border-b"
//           style={{ borderColor: theme.border }}
//         >
//           <h2 className="text-2xl font-bold" style={{ color: theme.text }}>
//             음성 대화 시뮬레이션
//           </h2>
//           <button onClick={onClose} className="p-2 rounded-lg" style={{ color: theme.sub }}>
//             <X size={20} />
//           </button>
//         </div>

//         {/* 컨텐츠 */}
//         <div className="flex-1 px-8 py-6 flex flex-col overflow-hidden">

//           {/* 🔥 run_no 개수만큼 버튼 자동 생성 */}
//           <div className="flex items-center justify-between gap-3 mb-4">
//             <div className="flex items-center gap-3 flex-wrap">
//               {Object.keys(runGroups).length > 0 &&
//                 Object.keys(runGroups)
//                   .sort((a, b) => Number(a) - Number(b))
//                   .map((runKey) => (
//                     <button
//                       key={runKey}
//                       onClick={() => playRun(Number(runKey))}
//                       disabled={loading}
//                       className="px-4 py-2 rounded-md text-sm font-semibold"
//                       style={{
//                         backgroundColor: theme.panel,
//                         color: theme.text,
//                         border: `1px solid ${theme.border}`,
//                       }}
//                     >
//                       {runKey}번째 대화
//                     </button>
//                   ))}
//             </div>

//             <button
//               onClick={ensureFetched}
//               disabled={loading}
//               className="px-5 py-2.5 rounded-lg font-semibold"
//               style={{
//                 backgroundColor: theme.blurple,
//                 color: theme.white,
//               }}
//             >
//               {loading ? "준비 중..." : "데이터 불러오기"}
//             </button>
//           </div>

//           {/* 파형 */}
//           <div
//             className="grid items-center my-6"
//             style={{
//               gridTemplateColumns: `${WAVE_MAX_BAR + 40}px 1fr ${WAVE_MAX_BAR + 40}px`,
//               columnGap: "24px",
//             }}
//           >
//             <SpeakerAvatar
//               speaker="offender"
//               isActive={currentSpeaker === "offender"}
//               isPlaying={isPlaying}
//               COLORS={theme}
//               size={WAVE_MAX_BAR}
//               photoSrc={criminal}
//             />

//             <AudioWaveform
//               isActive={isPlaying}
//               speaker={currentSpeaker}
//               COLORS={theme}
//               heightPx={WAVE_HEIGHT}
//               maxBarHeight={WAVE_MAX_BAR}
//             />

//             <SpeakerAvatar
//               speaker="victim"
//               isActive={currentSpeaker === "victim"}
//               isPlaying={isPlaying}
//               COLORS={theme}
//               size={WAVE_MAX_BAR}
//               photoSrc={victim}
//             />
//           </div>

//           {/* 텍스트 */}
//           <div
//             className="min-h-24 p-5 rounded-lg border text-center"
//             style={{ borderColor: theme.border, color: theme.text }}
//           >
//             {currentText || "‘n번째 대화’를 눌러 재생하세요."}
//           </div>

//         </div>

//         <audio ref={audioRef} className="hidden" />
//       </div>
//     </div>
//   );
// }




// // // src/components/TTSModal.jsx
// // import React, { useEffect, useRef, useState } from "react";
// // import { X, Mic } from "lucide-react";
// // import AudioWaveform from "./AudioWaveform";
// // import SpeakerAvatar from "./SpeakerAvatar";
// // import DEFAULT_COLORS from "../constants/colors";
// // import victim from "../assets/avatars/01.png";
// // import criminal from "../assets/avatars/02.png";

// // const API_BASE = "http://127.0.0.1:8000";

// // const toUrl = (b64, mime) => {
// //   const clean = (b64 || "").replace(/\s/g, "");
// //   const pad = "=".repeat((4 - (clean.length % 4)) % 4);
// //   const norm = clean.replace(/-/g, "+").replace(/_/g, "/") + pad;
// //   const type = !mime || mime === "audio/wav" ? "audio/wav" : mime;
// //   return `data:${type};base64,${norm}`;
// // };

// // export default function TTSModal({ isOpen, onClose, COLORS }) {
// //   const theme = COLORS ?? DEFAULT_COLORS;

// //   const [loading, setLoading] = useState(false);
// //   const [dialogue, setDialogue] = useState([]);
// //   const [urls, setUrls] = useState([]);
// //   const [idx, setIdx] = useState(-1);
// //   const [currentText, setCurrentText] = useState("");
// //   const [isPlaying, setIsPlaying] = useState(false);

// //   const audioRef = useRef(null);

// //   useEffect(() => {
// //     // console.log("TTS theme:", theme);
// //   }, [theme]);

// //   const playAt = async (i, sources = null, itemsArr = null) => {
// //     const a = audioRef.current;
// //     if (!a) return;
// //     const srcArray = sources || urls;
// //     const itemsArray = itemsArr || dialogue;
// //     if (!srcArray[i] || !itemsArray[i]) return;

// //     const item = itemsArray[i];
// //     setIdx(i);
// //     setCurrentText(item.text || "");
// //     setIsPlaying(true);

// //     try {
// //       a.pause();
// //       a.src = srcArray[i];
// //       a.load();

// //       await new Promise((resolve, reject) => {
// //         a.addEventListener("loadedmetadata", resolve, { once: true });
// //         a.addEventListener("error", reject, { once: true });
// //         setTimeout(() => reject(new Error("timeout")), 6000);
// //       });

// //       await a.play();
// //     } catch (err) {
// //       console.warn("[playAt] error:", err);
// //       setIsPlaying(false);
// //     }
// //   };

// //   const handlePlayDialogue = async () => {
// //     setLoading(true);
// //     setDialogue([]);
// //     setUrls([]);
// //     setIdx(-1);
// //     setCurrentText("");
// //     setIsPlaying(false);

// //     try {
// //       const res = await fetch(`${API_BASE}/api/tts/synthesize`, {
// //         method: "POST",
// //         headers: { "Content-Type": "application/json" },
// //         body: JSON.stringify({ mode: "dialogue" }),
// //       });

// //       if (!res.ok) throw new Error(`HTTP ${res.status}`);

// //       const data = await res.json();
// //       const items = (data.items || []).map((it) => ({
// //         ...it,
// //         totalDurationSec: Number(it.totalDurationSec) || 0,
// //         charTimeSec: Number(it.charTimeSec) || 0,
// //       }));

// //       setDialogue(items);
// //       const urlsLocal = items.map((it) => toUrl(it.audioContent, it.contentType));
// //       setUrls(urlsLocal);
// //       playAt(0, urlsLocal, items);
// //     } catch (e) {
// //       alert(`TTS 오류: ${e.message}`);
// //       console.error(e);
// //       setIsPlaying(false);
// //     } finally {
// //       setLoading(false);
// //     }
// //   };

// //   useEffect(() => {
// //     const a = audioRef.current;
// //     if (!a) return;

// //     const onEnded = () => {
// //       const next = idx + 1;
// //       if (next < dialogue.length) {
// //         playAt(next, urls, dialogue);
// //       } else {
// //         setIdx(-1);
// //         setCurrentText("");
// //         setIsPlaying(false);
// //       }
// //     };
// //     const onPlay = () => setIsPlaying(true);
// //     const onPause = () => setIsPlaying(false);
// //     const onError = () => setIsPlaying(false);

// //     a.addEventListener("ended", onEnded);
// //     a.addEventListener("play", onPlay);
// //     a.addEventListener("pause", onPause);
// //     a.addEventListener("error", onError);

// //     return () => {
// //       a.removeEventListener("ended", onEnded);
// //       a.removeEventListener("play", onPlay);
// //       a.removeEventListener("pause", onPause);
// //       a.removeEventListener("error", onError);
// //     };
// //   }, [idx, urls, dialogue]);

// //   if (!isOpen) return null;

// //   const current = idx >= 0 ? dialogue[idx] : null;
// //   const currentSpeaker = current?.speaker;

// //   const modalShadow = `0 8px 30px ${theme.black}80, 0 2px 8px ${theme.accent}20`;

// //   // 파형/아바타 사이즈 연동 상수
// //   const WAVE_HEIGHT = 140;
// //   const WAVE_MAX_BAR = 120;

// //   return (
// //     <div className="fixed inset-0 z-50 flex items-center justify-center">
// //       <div
// //         className="absolute inset-0"
// //         style={{ backgroundColor: `${theme.black}CC` }}
// //         aria-hidden="true"
// //       />

// //       <div
// //         className="relative w/full max-w-[900px] mx-4 rounded-3xl border overflow-hidden flex flex-col"
// //         style={{
// //           background: `linear-gradient(180deg, ${theme.panel} 0%, ${theme.panelDark} 100%)`,
// //           borderColor: theme.border,
// //           boxShadow: modalShadow,
// //           backdropFilter: "saturate(1.05) blur(6px)",
// //           minHeight: "80vh",
// //           maxHeight: "95vh",
// //           height: "85vh", //고정 높이
// //         }}
// //         role="dialog"
// //         aria-modal="true"
// //       >
// //         <div
// //           className="flex items-center justify-between px-6 py-4 border-b rounded-t-3xl"
// //           style={{
// //             borderColor: theme.border,
// //             backgroundColor: theme.panel,
// //           }}
// //         >
// //           <h2 className="text-2xl font-bold" style={{ color: theme.text }}>
// //             TTS 대화 시뮬레이션
// //           </h2>
// //           <button
// //             onClick={onClose}
// //             aria-label="닫기"
// //             className="p-2 rounded-lg transition-colors duration-200 hover:opacity-85"
// //             style={{
// //               color: theme.sub,
// //               backgroundColor: theme.panelDark,
// //             }}
// //           >
// //             <X size={20} />
// //           </button>
// //         </div>

// //         <div className="flex-1 px-8 py-6 overflow-y-scroll flex flex-col">
// //           {/* 상단 시나리오 전환 버튼바 + 주요 액션 */}
// //           <div className="flex items-center justify-between gap-3 mb-4">
// //             <div className="flex items-center gap-3">
// //               <button
// //                 onClick={() =>
// //                   alert("다음 시나리오(다른 수법)로 이어집니다. (추후 구현)")
// //                 }
// //                 className="px-4 py-2 rounded-md text-sm font-semibold transition-colors"
// //                 style={{
// //                   backgroundColor: theme.panel,
// //                   color: theme.text,
// //                   border: `1px solid ${theme.border}`,
// //                 }}
// //               >
// //                 다음 시나리오 이어가기
// //               </button>
// //               <button
// //                 onClick={() => alert("다른 수법 #2 (추후 구현)")}
// //                 className="px-4 py-2 rounded-md text-sm font-medium transition-colors"
// //                 style={{
// //                   backgroundColor: theme.panelDark,
// //                   color: theme.sub,
// //                   border: `1px solid ${theme.border}`,
// //                 }}
// //               >
// //                 다른 수법 #2
// //               </button>
// //               <button
// //                 onClick={() => alert("다른 수법 #3 (추후 구현)")}
// //                 className="px-4 py-2 rounded-md text-sm font-medium transition-colors"
// //                 style={{
// //                   backgroundColor: theme.panelDark,
// //                   color: theme.sub,
// //                   border: `1px solid ${theme.border}`,
// //                 }}
// //               >
// //                 다른 수법 #3
// //               </button>
// //             </div>

// //             {/* 주요 액션: 대화 재생 */}
// //             <button
// //               onClick={handlePlayDialogue}
// //               disabled={loading}
// //               className="px-5 py-2.5 rounded-lg font-semibold transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-95"
// //               style={{
// //                 backgroundColor: loading ? theme.border : theme.blurple,
// //                 color: theme.white,
// //                 boxShadow: `0 8px 24px ${theme.blurple}26, 0 2px 8px ${theme.black}33`,
// //                 border: `1px solid ${theme.blurple}55`,
// //               }}
// //               aria-label="대화 재생"
// //               title="대화 재생"
// //             >
// //               {loading ? (
// //                 <div className="flex items-center gap-2">
// //                   <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
// //                   준비 중...
// //                 </div>
// //               ) : (
// //                 <div className="flex items-center gap-2">
// //                   <Mic size={16} />
// //                   대화 재생
// //                 </div>
// //               )}
// //             </button>
// //           </div>

// //           {/* 분리선 */}
// //             <div
// //             className="w-full h-px my-2"
// //             style={{
// //                 backgroundColor: theme.border,           // 테마 경계선 색상
// //                 boxShadow: `0 1px 0 ${theme.black}22`,   // 살짝 입체감(선택)
// //             }}
// //             />

// //           {/* 프로필 섹션 중앙 정렬: 위쪽 가변 여백 */}
// //           <div className="flex-1" />

// //           {/* 상단 영역: 좌(아바타) - 중앙(파형) - 우(아바타) */}
// //           <div
// //             className="grid items-center my-8"
// //             style={{
// //               gridTemplateColumns: `${WAVE_MAX_BAR + 40}px 1fr ${WAVE_MAX_BAR + 40}px`,
// //               columnGap: "24px",
// //             }}
// //           >
// //             <SpeakerAvatar
// //               speaker="offender"
// //               isActive={currentSpeaker === "offender"}
// //               isPlaying={isPlaying}
// //               COLORS={theme}
// //               size={WAVE_MAX_BAR}
// //               photoSrc={criminal}
// //               alt="피싱범"
// //             />

// //             <div className="w-full">
// //               <AudioWaveform
// //                 isActive={isPlaying}
// //                 speaker={currentSpeaker}
// //                 COLORS={theme}
// //                 heightPx={WAVE_HEIGHT}
// //                 maxBarHeight={WAVE_MAX_BAR}
// //                 gap={4}
// //               />
// //             </div>

// //             <SpeakerAvatar
// //               speaker="victim"
// //               isActive={currentSpeaker === "victim"}
// //               isPlaying={isPlaying}
// //               COLORS={theme}
// //               size={WAVE_MAX_BAR}
// //               photoSrc={victim}
// //               alt="피해자"
// //             />
// //           </div>

// //           {/* 프로필 섹션 중앙 정렬: 아래쪽 가변 여백 */}
// //           <div className="flex-1" />

// //           {/* 대화 로그 영역 */}
// //           <div
// //             className="min-h-28 p-6 rounded-lg border text-center flex items-center justify-center mb-6"
// //             style={{
// //               background: theme.bg,
// //               borderColor: theme.border,
// //               color: theme.text,
// //               boxShadow: `inset 0 1px 0 ${theme.black}30`,
// //             }}
// //           >
// //             <p className="text-xl md:text-2xl leading-relaxed" style={{ maxWidth: 980 }}>
// //               {currentText || "대화를 시작하려면 아래 버튼을 누르세요."}
// //             </p>
// //           </div>

// //           {/* 진행률 UI가 필요하면 아래 주석을 해제하세요.
// //           {dialogue.length > 0 && (
// //             <div className="mt-6">
// //               <div className="flex justify-between text-base mb-2" style={{ color: theme.sub }}>
// //                 <span>진행률</span>
// //                 <span>{idx + 1} / {dialogue.length}</span>
// //               </div>
// //               <div className="h-3 rounded-full overflow-hidden" style={{ backgroundColor: theme.border }}>
// //                 <div
// //                   className="h-3 transition-all duration-300 rounded-full"
// //                   style={{
// //                     backgroundColor: theme.blurple,
// //                     width: `${dialogue.length > 0 ? ((idx + 1) / dialogue.length) * 100 : 0}%`,
// //                     boxShadow: `0 4px 14px ${theme.blurple}40`,
// //                   }}
// //                 />
// //               </div>
// //             </div>
// //           )} */}
// //         </div>

// //         <audio ref={audioRef} className="hidden" />
// //       </div>
// //     </div>
// //   );
// // }