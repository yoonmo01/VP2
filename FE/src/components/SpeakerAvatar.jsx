// src/components/SpeakerAvatar.jsx
import React from "react";

export default function SpeakerAvatar({
  speaker,      // "offender" | "victim"
  isActive,
  isPlaying,
  COLORS,
  size = 120,
  photoSrc,
  alt,
}) {
  const theme = COLORS ?? {
    bg: "#020617",
    panel: "#0f172a",
    border: "#334155",
    text: "#e5e7eb",
    sub: "#94a3b8",
    danger: "#ef4444",
    warn: "#eab308",
  };

  const ringColor =
    speaker === "offender" ? theme.danger : theme.warn;

  const borderColor = isActive && isPlaying ? ringColor : theme.border;
  const glow = isActive && isPlaying ? `0 0 20px ${ringColor}88` : "none";

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="rounded-full border flex items-center justify-center overflow-hidden transition-all duration-200"
        style={{
          width: size,
          height: size,
          borderColor,
          boxShadow: glow,
          backgroundColor: theme.panel,
        }}
      >
        <img
          src={photoSrc}
          alt={alt || speaker}
          className="w-[88%] h-[88%] object-cover rounded-full"
        />
      </div>
      <span
        className="text-xs font-medium"
        style={{ color: theme.sub }}
      >
        {speaker === "offender" ? "피싱범" : "피해자"}
      </span>
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

//   // 전체 로딩/데이터
//   const [loading, setLoading] = useState(false);
//   const [allItems, setAllItems] = useState([]); // 전체 TTS 응답 아이템
//   const [allUrls, setAllUrls] = useState([]); // 전체 url

//   // run별 분리 데이터 (동적)
//   const [runGroups, setRunGroups] = useState({}); // {1: [...], 2: [...], 3: [...]}
//   const [runUrls, setRunUrls] = useState({}); // {1: [...], 2: [...]}

//   // 현재 재생 중 상태
//   const [dialogue, setDialogue] = useState([]); // 현재 재생중인 아이템 리스트
//   const [urls, setUrls] = useState([]); // 현재 재생중인 url 리스트
//   const [idx, setIdx] = useState(-1);
//   const [currentText, setCurrentText] = useState("");
//   const [isPlaying, setIsPlaying] = useState(false);

//   const audioRef = useRef(null);

//   // --- utils: 응답 아이템 정규화
//   const normalizeItems = (items) =>
//     (items || []).map((it) => ({
//       ...it,
//       totalDurationSec: Number(it.totalDurationSec) || 0,
//       charTimeSec: Number(it.charTimeSec) || 0,
//     }));

//   // --- run_no 기반 동적 그룹 분리
//   const splitByRunDynamic = (items) => {
//     const groups = {};
//     items.forEach((it) => {
//       const run = it.run_no ?? it.runNo ?? it.run ?? 1;
//       if (!groups[run]) groups[run] = [];
//       groups[run].push(it);
//     });
//     return groups;
//   };

//   // --- fetch 한 번 해서 전부 받아오고 run별 세팅
//   const ensureFetched = async () => {
//     if (allItems.length > 0) return; // 이미 받아왔으면 스킵
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
//       const urlsLocal = items.map((it) => toUrl(it.audioContent, it.contentType));

//       setAllItems(items);
//       setAllUrls(urlsLocal);

//       // ✅ 동적 run 그룹 구성
//       const groups = splitByRunDynamic(items);
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

//   // --- 공통 재생 로직
//   const playAt = async (i, sources, itemsArr) => {
//     const a = audioRef.current;
//     if (!a) return;
//     if (!sources[i] || !itemsArr[i]) return;

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

//   // --- run 선택하여 재생
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

//     // 첫 컷 재생
//     playAt(0, selUrls, selItems);
//   };

//   // --- 오디오 이벤트
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
//     const onPlay = () => setIsPlaying(true);
//     const onPause = () => setIsPlaying(false);
//     const onError = () => setIsPlaying(false);

//     a.addEventListener("ended", onEnded);
//     a.addEventListener("play", onPlay);
//     a.addEventListener("pause", onPause);
//     a.addEventListener("error", onError);

//     return () => {
//       a.removeEventListener("ended", onEnded);
//       a.removeEventListener("play", onPlay);
//       a.removeEventListener("pause", onPause);
//       a.removeEventListener("error", onError);
//     };
//   }, [idx, urls, dialogue]);

//   if (!isOpen) return null;

//   const current = idx >= 0 ? dialogue[idx] : null;
//   const currentSpeaker = current?.speaker;

//   const modalShadow = `0 8px 30px ${theme.black}80, 0 2px 8px ${theme.accent}20`;
//   const WAVE_HEIGHT = 140;
//   const WAVE_MAX_BAR = 120;

//   return (
//     <div className="fixed inset-0 z-50 flex items-center justify-center">
//       <div
//         className="absolute inset-0"
//         style={{ backgroundColor: `${theme.black}CC` }}
//         aria-hidden="true"
//       />

//       <div
//         className="relative w-[900px] mx-4 rounded-3xl border overflow-hidden flex flex-col"
//         style={{
//           height: "760px",
//           background: `linear-gradient(180deg, ${theme.panel} 0%, ${theme.panelDark} 100%)`,
//           borderColor: theme.border,
//           boxShadow: modalShadow,
//           backdropFilter: "saturate(1.05) blur(6px)",
//         }}
//         role="dialog"
//         aria-modal="true"
//       >
//         <div
//           className="flex items-center justify-between px-6 py-4 border-b rounded-t-3xl"
//           style={{
//             borderColor: theme.border,
//             backgroundColor: theme.panel,
//           }}
//         >
//           <h2 className="text-2xl font-bold" style={{ color: theme.text }}>
//             음성 대화 시뮬레이션
//           </h2>
//           <button
//             onClick={onClose}
//             aria-label="닫기"
//             className="p-2 rounded-lg transition-colors duration-200 hover:opacity-85"
//             style={{
//               color: theme.sub,
//               backgroundColor: theme.panelDark,
//             }}
//           >
//             <X size={20} />
//           </button>
//         </div>

//         <div className="flex-1 px-8 py-6 flex flex-col overflow-hidden">
//           {/* 상단 버튼바: run_no 개수만큼 자동 생성 */}
//           <div className="flex items-center justify-between gap-3 mb-4">
//             <div className="flex items-center gap-3 flex-wrap">
//               {Object.keys(runGroups).length > 0 ? (
//                 Object.keys(runGroups)
//                   .sort((a, b) => Number(a) - Number(b))
//                   .map((runKey) => (
//                     <button
//                       key={runKey}
//                       onClick={() => playRun(Number(runKey))}
//                       disabled={loading}
//                       className="px-4 py-2 rounded-md text-sm font-semibold transition-colors"
//                       style={{
//                         backgroundColor: theme.panel,
//                         color: theme.text,
//                         border: `1px solid ${theme.border}`,
//                       }}
//                     >
//                       {runKey}번째 대화
//                     </button>
//                   ))
//               ) : (
//                 <>
//                   <button
//                     onClick={() => playRun(1)}
//                     disabled={loading}
//                     className="px-4 py-2 rounded-md text-sm font-semibold transition-colors"
//                     style={{
//                       backgroundColor: theme.panel,
//                       color: theme.text,
//                       border: `1px solid ${theme.border}`,
//                     }}
//                   >
//                     첫 번째 대화
//                   </button>
//                 </>
//               )}
//             </div>

//             {/* 데이터 미리 불러오기 버튼 */}
//             <button
//               onClick={ensureFetched}
//               disabled={loading}
//               className="px-5 py-2.5 rounded-lg font-semibold transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-95"
//               style={{
//                 backgroundColor: loading ? theme.border : theme.blurple,
//                 color: theme.white,
//                 boxShadow: `0 8px 24px ${theme.blurple}26, 0 2px 8px ${theme.black}33`,
//                 border: `1px solid ${theme.blurple}55`,
//               }}
//               aria-label="데이터 미리 불러오기"
//               title="데이터 미리 불러오기"
//             >
//               {loading ? (
//                 <div className="flex items-center gap-2">
//                   <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
//                   준비 중...
//                 </div>
//               ) : (
//                 <div className="flex items-center gap-2">
//                   <Mic size={16} />
//                   데이터 불러오기
//                 </div>
//               )}
//             </button>
//           </div>

//           <div
//             className="w-full h-px my-2"
//             style={{
//               backgroundColor: theme.border,
//               boxShadow: `0 1px 0 ${theme.black}22`,
//             }}
//           />

//           <div className="flex-1" />

//           {/* 프로필 + 파형 */}
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
//               alt="피싱범"
//             />

//             <div className="w-full">
//               <AudioWaveform
//                 isActive={isPlaying}
//                 speaker={currentSpeaker}
//                 COLORS={theme}
//                 heightPx={140}
//                 maxBarHeight={WAVE_MAX_BAR}
//                 gap={4}
//               />
//             </div>

//             <SpeakerAvatar
//               speaker="victim"
//               isActive={currentSpeaker === "victim"}
//               isPlaying={isPlaying}
//               COLORS={theme}
//               size={WAVE_MAX_BAR}
//               photoSrc={victim}
//               alt="피해자"
//             />
//           </div>

//           <div className="flex-1" />

//           {/* 대화 텍스트 표시 */}
//           <div
//             className="min-h-24 p-5 rounded-lg border text-center flex items-center justify-center"
//             style={{
//               background: theme.bg,
//               borderColor: theme.border,
//               color: theme.text,
//               boxShadow: `inset 0 1px 0 ${theme.black}30`,
//             }}
//           >
//             <p className="text-lg leading-relaxed" style={{ maxWidth: 980 }}>
//               {currentText || "‘n번째 대화’ 버튼을 눌러 재생하세요."}
//             </p>
//           </div>
//         </div>

//         <audio ref={audioRef} className="hidden" />
//       </div>
//     </div>
//   );
// }

// // import { useMemo, useState } from "react";
// // import { User } from "lucide-react";

// // /**
// //  * Props
// //  * - speaker: "offender" | "victim"
// //  * - isActive, isPlaying: 재생 상태
// //  * - COLORS: 색상 토큰
// //  * - size: 아바타 지름(px, 가로/세로 동일) — 기본 80
// //  * - photoSrc: 아바타 이미지(번들 import 경로)
// //  * - alt: 이미지 대체 텍스트
// //  * - showIconFallback: 이미지 실패 시 아이콘 폴백 여부
// //  */
// // export default function SpeakerAvatar({
// //   speaker,
// //   isActive,
// //   isPlaying,
// //   COLORS,
// //   size = 80,
// //   photoSrc,
// //   alt = "avatar",
// //   showIconFallback = true,
// // }) {
// //   const isOffender = speaker === "offender";
// //   const baseColor = isOffender ? COLORS.danger : COLORS.warn;
// //   const activeColor = isOffender ? "#FF6B6B" : "#FFD93D";
// //   const isOn = isActive && isPlaying;

// //   // size 파생 값
// //   const metrics = useMemo(() => {
// //     const icon = Math.round(size * 0.5);
// //     const borderW = Math.max(2, Math.round(size * 0.06));
// //     const shadowR = Math.round(size * 0.22);            // 내부 글로우(약간 축소)
// //     const labelFont = Math.max(12, Math.round(size * 0.18));
// //     const labelPx = Math.max(8, Math.round(size * 0.12));
// //     const labelPy = Math.max(4, Math.round(size * 0.08));
// //     const speakingScale = 1 + Math.min(0.08, size / 1000);

// //     // ✅ 바깥 링 두께/오프셋
// //     const outerRingInset = Math.max(6, Math.round(size * 0.08));
// //     const outerRingBorderW = Math.max(2, Math.round(size * 0.04));
// //     const outerGlowInset = Math.max(10, Math.round(size * 0.12));

// //     return {
// //       icon,
// //       borderW,
// //       shadowR,
// //       labelFont,
// //       labelPx,
// //       labelPy,
// //       speakingScale,
// //       outerRingInset,
// //       outerRingBorderW,
// //       outerGlowInset,
// //     };
// //   }, [size]);

// //   const [imgErr, setImgErr] = useState(false);
// //   const useImage = !!photoSrc && !imgErr;

// //   return (
// //     <div className="flex flex-col items-center gap-3">
// //       {/* ✅ 외부 래퍼: 바깥쪽 링을 위해 overflow-visible 유지 */}
// //       <div className="relative" style={{ width: size, height: size }}>
// //         {/* ✅ 바깥쪽 링(테두리 바깥에서 확장) */}
// //         {/* ✅ 바깥쪽 그라데이션 글로우 + 얇은 링(선택) */}
// //         {isOn && (
// //           <>
// //             {/* 퍼지는 빛: 라디얼 그라데이션 */}
// //             <span
// //               className="pointer-events-none absolute rounded-full animate-ping"
// //               style={{
// //                 top: -metrics.outerGlowInset,
// //                 right: -metrics.outerGlowInset,
// //                 bottom: -metrics.outerGlowInset,
// //                 left: -metrics.outerGlowInset,
// //                 // 중심에서 바깥으로 자연스럽게 소멸
// //                 background: `radial-gradient(
// //                   circle,
// //                   ${baseColor}66 0%,
// //                   ${baseColor}33 45%,
// //                   ${baseColor}1F 65%,
// //                   transparent 82%
// //                 )`,
// //                 opacity: 0.9,
// //                 willChange: "transform, opacity",
// //               }}
// //               aria-hidden="true"
// //             />
// //             {/* 얇은 외곽 링(선명도 부스트; 필요 없으면 제거) */}
// //             <span
// //               className="pointer-events-none absolute rounded-full animate-ping"
// //               style={{
// //                 top: -metrics.outerRingInset,
// //                 right: -metrics.outerRingInset,
// //                 bottom: -metrics.outerRingInset,
// //                 left: -metrics.outerRingInset,
// //                 border: `${metrics.outerRingBorderW}px solid ${baseColor}`,
// //                 opacity: 0.25,
// //                 boxSizing: "border-box",
// //                 backgroundColor: "transparent",
// //                 willChange: "transform, opacity",
// //               }}
// //               aria-hidden="true"
// //             />
// //           </>
// //         )}

// //         {/* 아바타 본체(이미지 원형 크롭) */}
// //         <div
// //           className="rounded-full flex items-center justify-center transition-all duration-300 overflow-hidden"
// //           style={{
// //             width: size,
// //             height: size,
// //             backgroundColor: isOn ? activeColor : COLORS.panel,
// //             borderColor: isOn ? activeColor : COLORS.border,
// //             borderStyle: "solid",
// //             borderWidth: metrics.borderW,
// //             boxShadow: isOn ? `0 0 ${metrics.shadowR}px ${baseColor}40` : "none",
// //             transform: isOn ? `scale(${metrics.speakingScale})` : "scale(1)",
// //           }}
// //           aria-label={isOffender ? "피싱범 아바타" : "피해자 아바타"}
// //         >
// //           {useImage ? (
// //             <img
// //               src={photoSrc}
// //               alt={alt}
// //               className="w-full h-full object-cover"
// //               onError={() => setImgErr(true)}
// //               draggable={false}
// //             />
// //           ) : (
// //             showIconFallback && (
// //               <User
// //                 size={metrics.icon}
// //                 style={{ color: isOn ? COLORS.black : COLORS.sub }}
// //                 aria-hidden="true"
// //               />
// //             )
// //           )}
// //         </div>
// //       </div>

// //       {/* 라벨 */}
// //       <div
// //         className="rounded-lg font-bold transition-all duration-300 border"
// //         style={{
// //           fontSize: `${metrics.labelFont}px`,
// //           padding: `${metrics.labelPy}px ${metrics.labelPx}px`,
// //           backgroundColor: isOn ? baseColor : COLORS.panel,
// //           color: isOn ? COLORS.white : COLORS.sub,
// //           borderColor: isOn ? baseColor : COLORS.border,
// //         }}
// //       >
// //         {isOffender ? "피싱범" : "피해자"}
// //       </div>
// //     </div>
// //   );
// // }



// //===================================

// // import { User } from "lucide-react";

// // export default function SpeakerAvatar({ speaker, isActive, isPlaying, COLORS }) {
// //   const isOffender = speaker === "offender";
// //   const baseColor = isOffender ? COLORS.danger : COLORS.warn;
// //   const activeColor = isOffender ? "#FF6B6B" : "#FFD93D";

// //   return (
// //     <div className="flex flex-col items-center gap-3">
// //       <div
// //         className="relative w-20 h-20 rounded-full border-2 flex items-center justify-center transition-all duration-300"
// //         style={{
// //           backgroundColor: isActive && isPlaying ? activeColor : COLORS.panel,
// //           borderColor: isActive && isPlaying ? activeColor : COLORS.border,
// //           boxShadow: isActive && isPlaying ? `0 0 20px ${baseColor}40` : "none",
// //         }}
// //       >
// //         <User
// //           size={40}
// //           style={{
// //             color: isActive && isPlaying ? COLORS.black : COLORS.sub,
// //           }}
// //         />
// //         {isActive && isPlaying && (
// //           <div
// //             className="absolute inset-0 rounded-full animate-ping"
// //             style={{
// //               backgroundColor: baseColor,
// //               opacity: 0.3,
// //             }}
// //           />
// //         )}
// //       </div>

// //       <div
// //         className="px-4 py-2 rounded-lg text-base font-medium transition-all duration-300"
// //         style={{
// //           backgroundColor: isActive && isPlaying ? baseColor : COLORS.panel,
// //           color: isActive && isPlaying ? COLORS.white : COLORS.sub,
// //           border: `1px solid ${isActive && isPlaying ? baseColor : COLORS.border}`,
// //         }}
// //       >
// //         {isOffender ? "피싱범" : "피해자"}
// //       </div>
// //     </div>
// //   );
// // }