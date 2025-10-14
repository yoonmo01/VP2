// // src/SimulatorPage.jsx
import { useState, useMemo, useEffect, useRef } from "react";
import HudBar from "./HudBar";
import MessageBubble from "./MessageBubble";
import SpinnerMessage from "./SpinnerMessage";
import InvestigationBoard from "./InvestigationBoard";
import TerminalLog from "./components/TerminalLog";
import TTSModal from "./components/TTSModal";
import { FileBarChart2 } from "lucide-react";

const SimulatorPage = ({
  COLORS,
  simulationState,
  messages,
  sessionResult,
  setSessionResult,
  progress,
  setProgress,
  startSimulation,
  startAgentRun,
  declineAgentRun,
  hasInitialRun,
  hasAgentRun,
  agentRunning,
  pendingAgentDecision,
  showReportPrompt,
  setShowReportPrompt,
  selectedScenario,
  setSelectedScenario,
  selectedCharacter,
  setSelectedCharacter,
  setCurrentPage,
}) => {
  /* 🧠 1. 에이전트 로그 생성 */
  const agentLogText = useMemo(() => {
    if (!sessionResult?.agentLogs) return "";
    return sessionResult.agentLogs
      .map((log) => `[${log.role}] ${log.content}`)
      .join("\n");
  }, [sessionResult?.agentLogs]);

  /* 🧮 2. 진행률 계산 */
  const countChatMessages = (msgs = []) =>
    msgs.filter((m) => (m?.type ?? m?._kind) === "chat").length;

  useEffect(() => {
    const pct = Math.min(
      100,
      Math.round((countChatMessages(messages) / 10) * 100)
    );
    setProgress(pct);
  }, [messages, setProgress]);

  /* 🧾 3. 로그 점진 출력 */
  const [displayedAgentLogText, setDisplayedAgentLogText] = useState("");
  const logIndexRef = useRef(0);
  useEffect(() => {
    const lines = agentLogText.split("\n").filter(Boolean);
    if (lines.length === 0) return;
    const timer = setInterval(() => {
      if (logIndexRef.current >= lines.length) return clearInterval(timer);
      setDisplayedAgentLogText((prev) =>
        prev
          ? `${prev}\n${lines[logIndexRef.current]}`
          : lines[logIndexRef.current]
      );
      logIndexRef.current++;
    }, 200);
    return () => clearInterval(timer);
  }, [agentLogText]);

  /* 🔄 리셋 함수 */
  const resetLogsAndResult = () => {
    setDisplayedAgentLogText("");
    logIndexRef.current = 0;
    setSessionResult(null);
    setProgress(0);
  };

  /* 🧩 4. 백엔드 로그(sessionResult.log.turns) → MessageBubble 호환 메시지 변환 */
  const parsedMessages = useMemo(() => {
    if (!sessionResult?.log?.turns) return [];

    return sessionResult.log.turns.map((t) => {
      let parsed = null;
      let content = t.text;
      let convincedPct = null;

      if (t.role === "victim") {
        try {
          parsed = JSON.parse(t.text);
          content = parsed.dialogue || t.text;
          // 🔹 is_convinced(0~10)을 퍼센트(0~100)로 변환
          if (typeof parsed.is_convinced === "number") {
            convincedPct = Math.round((parsed.is_convinced / 10) * 100);
          }
        } catch {
          content = t.text;
        }
      }

      return {
        sender: t.role, // "victim" or "offender"
        content,
        convincedPct,
        type: "chat",
        timestamp: new Date().toLocaleTimeString("ko-KR", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
    });
  }, [sessionResult]);

  /* 💬 5. 렌더링 */
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: COLORS.bg, color: COLORS.text }}
    >
      <HudBar COLORS={COLORS} />

      {/* 상단 상태/버튼 바 */}
      <div
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: COLORS.border }}
      >
        <div className="flex items-center gap-3">
          <span>{selectedScenario ? selectedScenario.name : "시나리오 미선택"}</span>
          <span>{selectedCharacter ? selectedCharacter.name : "캐릭터 미선택"}</span>
        </div>

        <div className="flex gap-2">
          {/* 시나리오 다시 선택 */}
          {selectedScenario && (
            <button
              onClick={() => {
                setSelectedScenario(null);
                resetLogsAndResult();
              }}
              className="px-3 py-2 rounded-md text-sm font-medium border"
              style={{
                backgroundColor: COLORS.panel,
                borderColor: COLORS.border,
                color: COLORS.sub,
              }}
            >
              ← 시나리오 다시 선택
            </button>
          )}

          {/* 캐릭터 다시 선택 */}
          {selectedCharacter && (
            <button
              onClick={() => {
                setSelectedCharacter(null);
                resetLogsAndResult();
              }}
              className="px-3 py-2 rounded-md text-sm font-medium border"
              style={{
                backgroundColor: COLORS.panel,
                borderColor: COLORS.border,
                color: COLORS.sub,
              }}
            >
              ← 캐릭터 다시 선택
            </button>
          )}

          {/* 리포트 보기 */}
          {progress >= 100 && (
            <button
              onClick={() => setCurrentPage("report")}
              className="px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2"
              style={{
                backgroundColor: COLORS.blurple,
                color: COLORS.white,
                boxShadow: "0 6px 12px rgba(0,0,0,.25)",
              }}
            >
              <FileBarChart2 size={18} />
              리포트 보기
            </button>
          )}
        </div>
      </div>

      {/* 본문 영역 */}
      <div className="flex flex-row h-[80vh]">
        {/* 왼쪽: 대화창 */}
        <div className="flex-1 overflow-y-auto p-6">
          {parsedMessages.length === 0 ? (
            <SpinnerMessage simulationState={simulationState} COLORS={COLORS} />
          ) : (
            parsedMessages.map((m, i) => (
              <MessageBubble
                key={i}
                message={m}
                selectedCharacter={selectedCharacter}
                victimImageUrl={selectedCharacter?.imageUrl}
                COLORS={COLORS}
              />
            ))
          )}
        </div>

        {/* 오른쪽: 로그 + 분석 */}
        <div
          className="w-[30%] border-l flex flex-col"
          style={{ borderColor: COLORS.border, backgroundColor: COLORS.panel }}
        >
          <div className="flex-1 overflow-auto p-4">
            <TerminalLog data={displayedAgentLogText} />
          </div>
          <div className="border-t p-4" style={{ borderColor: COLORS.border }}>
            {sessionResult?.insights ? (
              <InvestigationBoard COLORS={COLORS} insights={sessionResult.insights} />
            ) : (
              <div className="text-sm text-gray-400">분석 결과가 없습니다.</div>
            )}
          </div>
        </div>
      </div>

      {/* 하단 진행률 */}
      <div
        className="px-6 py-4 flex items-center justify-between border-t"
        style={{ borderColor: COLORS.border }}
      >
        <span>진행률: {progress}%</span>
        <div
          className="h-3 w-48 rounded-full overflow-hidden"
          style={{ backgroundColor: COLORS.panel }}
        >
          <div
            className="h-3 transition-all"
            style={{
              width: `${progress}%`,
              backgroundColor: COLORS.blurple,
            }}
          />
        </div>
      </div>

      <TTSModal isOpen={false} onClose={() => {}} COLORS={COLORS} />
    </div>
  );
};

export default SimulatorPage;

// import { useState, useMemo, useEffect, useRef } from "react";
// import { Play, Clock, Check, AlertTriangle } from "lucide-react";
// import HudBar from "./HudBar";
// import Badge from "./Badge";
// import SelectedCard from "./SelectedCard";
// import Chip from "./Chip";
// import MessageBubble from "./MessageBubble";
// import SpinnerMessage from "./SpinnerMessage";

// const getVictimImage = (photoPath) => {
//   if (!photoPath) return null;
//   try {
//     const fileName = photoPath.split("/").pop();
//     if (fileName)
//       return new URL(`./assets/victims/${fileName}`, import.meta.url).href;
//   } catch (error) {
//     console.warn("이미지 로드 실패:", error);
//   }
//   return null;
// };

// const countChatMessages = (messages = []) =>
//   Array.isArray(messages)
//     ? messages.filter((m) => (m?.type ?? m?._kind) === "chat").length
//     : 0;

// const SimulatorPage = ({
//   COLORS,
//   setCurrentPage,
//   selectedScenario,
//   setSelectedScenario,
//   selectedCharacter,
//   setSelectedCharacter,
//   simulationState,
//   messages,
//   sessionResult,
//   progress,
//   setProgress, // 반드시 App에서 전달하세요
//   resetToSelection,
//   startSimulation,
//   startAgentRun,
//   declineAgentRun,
//   scenarios,
//   characters,
//   scrollContainerRef,
//   addSystem,
//   pendingAgentDecision,
//   showReportPrompt,
//   setShowReportPrompt,
//   hasInitialRun,
//   hasAgentRun,
//   agentRunning,
//   victimImageUrl,
//   agentVerbose, // ← 추가
//   setAgentVerbose, // ← 추가
// }) => {
//   const needScenario = !selectedScenario;
//   const needCharacter = !selectedCharacter;
//   const [selectedTag, setSelectedTag] = useState(null);

//   // --- 디자인 변경: 더 어두운 경찰 엠블럼 느낌 팔레트로 강제 덮어쓰기 ---
//   const THEME = {
//     ...COLORS,
//     bg: "#030617", // 더 어두운 네이비 배경 (눈 부담 감소)
//     panel: "#061329", // 더 어두운 딥 블루 패널
//     panelDark: "#04101f", // 보조 패널 (어둡게)
//     panelDarker: "#020812", // 가장 어두운 패널
//     border: "#A8862A", // 낮춘 골드(액센트)
//     text: "#FFFFFF",
//     sub: "#BFB38A", // 낮춘 연한 골드/베이지 (눈 부담 감소)
//     blurple: "#A8862A", // primary 역할 -> 어두운 골드
//     success: COLORS?.success ?? "#57F287",
//     warn: COLORS?.warn ?? "#FF4757",
//     white: "#FFFFFF",
//   };

//   const filteredScenarios = useMemo(() => {
//     if (!selectedTag) return scenarios;
//     return scenarios.filter(
//       (s) =>
//         s.type === selectedTag ||
//         (Array.isArray(s.tags) && s.tags.includes(selectedTag)),
//     );
//   }, [selectedTag, scenarios]);

//   const normalizeMessage = (m) => {
//     if (m?.type === "system" || m?.type === "analysis") {
//       return {
//         ...m,
//         _kind: m.type,
//         label: m.type === "system" ? "시스템" : "분석",
//         side: "center",
//         timestamp: m.timestamp,
//       };
//     }

//     const role = (m?.sender || m?.role || "").toLowerCase();
//     const offenderLabel =
//       m?.offender_name ||
//       (selectedScenario ? `피싱범${selectedScenario.id}` : "피싱범");
//     const victimLabel =
//       m?.victim_name ||
//       (selectedCharacter ? `피해자${selectedCharacter.id}` : "피해자");

//     const label =
//       m?.senderLabel ??
//       m?.senderName ??
//       (role === "offender"
//         ? offenderLabel
//         : role === "victim"
//           ? victimLabel
//           : "상대");

//     const side =
//       m?.side ??
//       (role === "offender" ? "left" : role === "victim" ? "right" : "left");

//     const ts =
//       typeof m?.timestamp === "string"
//         ? m.timestamp
//         : typeof m?.created_kst === "string"
//           ? new Date(m.created_kst).toLocaleTimeString()
//           : (m?.timestamp ?? null);

//     return {
//       ...m,
//       _kind: "chat",
//       role,
//       label,
//       side,
//       timestamp: ts,
//     };
//   };

//   // 버튼 비활성 조건
//   const startDisabled =
//     simulationState === "PREPARE" ||
//     simulationState === "RUNNING" ||
//     pendingAgentDecision ||
//     hasInitialRun;

//   // --- 핵심: 진행률 재계산을 위한 ref/효과들 ---
//   const initialChatCountRef = useRef(0);
//   const lastProgressRef = useRef(progress ?? 0);

//   // 1) pendingAgentDecision이 활성화(초기 실행 끝)될 때 초기 채팅 수 저장 및 진행률 보정
//   useEffect(() => {
//     if (pendingAgentDecision) {
//       const initialCount = countChatMessages(messages);
//       initialChatCountRef.current = initialCount;

//       const totalTurns = sessionResult?.totalTurns ?? initialCount;
//       const pct = Math.min(
//         100,
//         Math.round((initialCount / Math.max(1, totalTurns)) * 100),
//       );
//       if (typeof setProgress === "function") {
//         setProgress(pct);
//         lastProgressRef.current = pct;
//       }
//     }
//     // eslint-disable-next-line react-hooks/exhaustive-deps
//   }, [pendingAgentDecision]);

//   // 2) 메시지 / 에이전트 상태 변화에 따라 진행률 재계산
//   useEffect(() => {
//     if (typeof setProgress !== "function") return;

//     const currentCount = countChatMessages(messages);
//     const serverTotal = sessionResult?.totalTurns;

//     if (typeof serverTotal === "number" && serverTotal > 0) {
//       const pct = Math.min(
//         100,
//         Math.round((currentCount / Math.max(1, serverTotal)) * 100),
//       );
//       setProgress(pct);
//       lastProgressRef.current = pct;
//       return;
//     }

//     if (hasAgentRun && !agentRunning) {
//       setProgress(100);
//       lastProgressRef.current = 100;
//       return;
//     }

//     const initialCount = Math.max(1, initialChatCountRef.current || 0);
//     const estimatedTotal = Math.max(
//       currentCount,
//       Math.round(initialCount + (currentCount - initialCount) * 2) ||
//         initialCount + 4,
//     );
//     const pct = Math.min(
//       100,
//       Math.round((currentCount / Math.max(1, estimatedTotal)) * 100),
//     );

//     const newPct = Math.max(lastProgressRef.current, pct);
//     setProgress(newPct);
//     lastProgressRef.current = newPct;
//   }, [messages, hasAgentRun, agentRunning, sessionResult, setProgress]);

//   return (
//     <div
//       className="min-h-screen"
//       style={{ backgroundColor: THEME.bg, color: THEME.text }}
//     >
//       <div className="container mx-auto px-6 py-12">
//         <div
//           className="w-full max-w-[1400px] mx-auto h-[calc(100vh-3rem)] rounded-3xl shadow-2xl border flex flex-col min-h-0"
//           style={{
//             borderColor: THEME.border,
//             backgroundColor: THEME.panel,
//           }}
//         >
//           <HudBar COLORS={THEME} />

//           <div
//             className="px-6 py-4 flex items-center justify-between"
//             style={{
//               backgroundColor: THEME.panel,
//               borderBottom: `1px dashed ${THEME.border}`,
//             }}
//           >
//             <div className="flex items-center gap-3">
//               <Badge
//                 tone={selectedScenario ? "primary" : "neutral"}
//                 COLORS={THEME}
//               >
//                 {selectedScenario ? selectedScenario.name : "시나리오 미선택"}
//               </Badge>
//               <Badge
//                 tone={selectedCharacter ? "success" : "neutral"}
//                 COLORS={THEME}
//               >
//                 {selectedCharacter ? selectedCharacter.name : "캐릭터 미선택"}
//               </Badge>
//             </div>

//             <div className="flex items-center gap-2">
//               {selectedScenario &&
//                 simulationState === "IDLE" &&
//                 !pendingAgentDecision && (
//                   <button
//                     onClick={() => {
//                       setSelectedScenario(null);
//                       setSelectedTag(null);
//                       addSystem("시나리오를 다시 선택하세요.");
//                     }}
//                     className="px-3 py-2 rounded-md text-sm font-medium border hover:opacity-90 transition"
//                     style={{
//                       backgroundColor: THEME.panelDark,
//                       borderColor: THEME.border,
//                       color: THEME.sub,
//                     }}
//                   >
//                     ← 시나리오 다시 선택
//                   </button>
//                 )}

//               {selectedCharacter &&
//                 simulationState === "IDLE" &&
//                 !pendingAgentDecision && (
//                   <button
//                     onClick={() => {
//                       setSelectedCharacter(null);
//                       addSystem("캐릭터를 다시 선택하세요.");
//                     }}
//                     className="px-3 py-2 rounded-md text-sm font-medium border hover:opacity-90 transition"
//                     style={{
//                       backgroundColor: THEME.panelDark,
//                       borderColor: THEME.border,
//                       color: THEME.sub,
//                     }}
//                   >
//                     ← 캐릭터 다시 선택
//                   </button>
//                 )}
//             </div>
//           </div>

//           <div
//             className="px-6 py-6 flex-1 min-h-0"
//             style={{ backgroundColor: THEME.bg }}
//           >
//             <div
//               ref={scrollContainerRef}
//               className="h-full overflow-y-auto space-y-6"
//             >
//               {!messages.some((m) => m.type === "chat") && (
//                 <SpinnerMessage
//                   simulationState={simulationState}
//                   COLORS={THEME}
//                 />
//               )}

//               {messages.map((m, index) => {
//                 const nm = normalizeMessage(m);
//                 const victimImg = selectedCharacter
//                   ? getVictimImage(selectedCharacter.photo_path)
//                   : null;
//                 return (
//                   <MessageBubble
//                     key={index}
//                     message={nm}
//                     selectedCharacter={selectedCharacter}
//                     victimImageUrl={victimImg}
//                     COLORS={THEME}
//                     label={nm.label}
//                     side={nm.side}
//                     role={nm.role}
//                   />
//                 );
//               })}

//               {/* 인라인 에이전트 결정 UI */}
//               {pendingAgentDecision &&
//                 simulationState === "IDLE" &&
//                 !hasAgentRun && (
//                   <div className="flex justify-center mt-2">
//                     <div
//                       className="w-full max-w-[820px] p-4 rounded-md border"
//                       style={{
//                         backgroundColor: THEME.panel,
//                         borderColor: THEME.border,
//                       }}
//                     >
//                       <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
//                         <p className="text-sm" style={{ color: THEME.sub }}>
//                           에이전트를 사용하여 대화를 이어보시겠습니까?
//                           <span
//                             className="ml-2 text-xs"
//                             style={{
//                               color: THEME.sub,
//                             }}
//                           >
//                             (에이전트는 추가 분석/판단을 포함합니다)
//                           </span>
//                         </p>

//                         <div className="flex items-center gap-4 justify-end">
//                           {/* ✅ verbose 토글 */}
//                           <label
//                             className="inline-flex items-center gap-2 text-sm"
//                             style={{
//                               color: THEME.sub,
//                             }}
//                           >
//                             <input
//                               type="checkbox"
//                               style={{
//                                 accentColor: THEME.blurple,
//                               }}
//                               checked={!!agentVerbose}
//                               onChange={(e) =>
//                                 setAgentVerbose(e.target.checked)
//                               }
//                             />
//                             상세근거(verbose)
//                           </label>

//                           <button
//                             onClick={declineAgentRun}
//                             className="px-4 py-2 rounded"
//                             style={{
//                               backgroundColor: THEME.panelDark,
//                               color: THEME.text,
//                             }}
//                           >
//                             아니요
//                           </button>

//                           <button
//                             onClick={startAgentRun}
//                             disabled={agentRunning || hasAgentRun}
//                             className={`px-4 py-2 rounded text-white`}
//                             style={{
//                               backgroundColor: agentRunning
//                                 ? THEME.blurple
//                                 : THEME.blurple,
//                               opacity: agentRunning ? 0.5 : 1,
//                               cursor: agentRunning ? "not-allowed" : undefined,
//                             }}
//                           >
//                             {agentRunning ? "로딩..." : "예"}
//                           </button>
//                         </div>
//                       </div>
//                     </div>
//                   </div>
//                 )}

//               {needScenario && (
//                 <div className="flex justify-start">
//                   <SelectedCard
//                     title="시나리오 선택"
//                     subtitle="유형 칩을 먼저 눌러 필터링한 뒤, 상세 시나리오를 선택하세요."
//                     COLORS={THEME}
//                   >
//                     <div className="mb-4">
//                       {["기관 사칭형", "가족·지인 사칭", "대출사기형"].map(
//                         (t) => (
//                           <Chip
//                             key={t}
//                             active={selectedTag === t}
//                             label={`${t}`}
//                             onClick={() =>
//                               setSelectedTag(selectedTag === t ? null : t)
//                             }
//                             COLORS={THEME}
//                           />
//                         ),
//                       )}
//                     </div>

//                     <div
//                       className="flex-1 min-h-0 space-y-4 overflow-y-auto pr-1"
//                       style={{ maxHeight: "100%" }}
//                     >
//                       {filteredScenarios.map((s) => (
//                         <button
//                           key={s.id}
//                           onClick={() => setSelectedScenario(s)}
//                           className="w-full text-left rounded-lg p-4 hover:opacity-90"
//                           style={{
//                             backgroundColor: THEME.panelDark,
//                             border: `1px solid ${THEME.border}`,
//                             color: THEME.text,
//                           }}
//                         >
//                           <div className="flex items-center justify-between mb-2">
//                             <span className="font-semibold text-lg">
//                               {s.name}
//                             </span>
//                             <Badge tone="primary" COLORS={THEME}>
//                               {s.type}
//                             </Badge>
//                           </div>
//                           <p
//                             className="text-base leading-relaxed"
//                             style={{
//                               color: THEME.sub,
//                             }}
//                           >
//                             {s.profile?.purpose ?? ""}
//                           </p>
//                         </button>
//                       ))}
//                     </div>
//                   </SelectedCard>
//                 </div>
//               )}

//               {!needScenario && needCharacter && (
//                 <div
//                   className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 flex-1 min-h-0 overflow-y-auto pr-1"
//                   style={{ maxHeight: "100%" }}
//                 >
//                   {characters.map((c) => (
//                     <button key={c.id} onClick={() => setSelectedCharacter(c)}>
//                       <div
//                         className="flex flex-col h-full rounded-2xl overflow-hidden border hover:border-[rgba(168,134,42,.25)] transition-colors"
//                         style={{
//                           backgroundColor: THEME.panelDark,
//                           borderColor: THEME.border,
//                         }}
//                       >
//                         {getVictimImage(c.photo_path) ? (
//                           <div
//                             className="w-full h-44 bg-cover bg-center"
//                             style={{
//                               backgroundImage: `url(${getVictimImage(c.photo_path)})`,
//                             }}
//                           />
//                         ) : (
//                           <div
//                             className="w-full h-44 flex items-center justify-center text-6xl"
//                             style={{
//                               backgroundColor: THEME.panelDarker,
//                             }}
//                           >
//                             {c.avatar ?? "👤"}
//                           </div>
//                         )}
//                         <div className="p-4 flex flex-col gap-3">
//                           <div className="flex items-center justify-between">
//                             <span
//                               className="font-semibold text-lg"
//                               style={{
//                                 color: THEME.text,
//                               }}
//                             >
//                               {c.name}
//                             </span>
//                             <span
//                               className="text-xs px-2 py-1 rounded-md"
//                               style={{
//                                 color: THEME.blurple,
//                                 backgroundColor: "rgba(168,134,42,.08)",
//                                 border: `1px solid rgba(168,134,42,.18)`,
//                               }}
//                             >
//                               프로필
//                             </span>
//                           </div>

//                           <div
//                             className="space-y-2 text-sm"
//                             style={{
//                               color: THEME.sub,
//                             }}
//                           >
//                             <div className="flex justify-between items-center">
//                               <span className="text-[12px] opacity-70">
//                                 나이
//                               </span>
//                               <span
//                                 className="font-medium"
//                                 style={{
//                                   color: THEME.text,
//                                 }}
//                               >
//                                 {c.meta.age}
//                               </span>
//                             </div>
//                             <div className="flex justify-between items-center">
//                               <span className="text-[12px] opacity-70">
//                                 성별
//                               </span>
//                               <span
//                                 className="font-medium"
//                                 style={{
//                                   color: THEME.text,
//                                 }}
//                               >
//                                 {c.meta.gender}
//                               </span>
//                             </div>
//                             <div className="flex justify-between items-center">
//                               <span className="text-[12px] opacity-70">
//                                 거주지
//                               </span>
//                               <span
//                                 className="font-medium truncate ml-2"
//                                 style={{
//                                   color: THEME.text,
//                                 }}
//                               >
//                                 {c.meta.address}
//                               </span>
//                             </div>
//                             <div className="flex justify-between items-center">
//                               <span className="text-[12px] opacity-70">
//                                 학력
//                               </span>
//                               <span
//                                 className="font-medium truncate ml-2"
//                                 style={{
//                                   color: THEME.text,
//                                 }}
//                               >
//                                 {c.meta.education}
//                               </span>
//                             </div>
//                           </div>

//                           <div>
//                             <span
//                               className="block text-[12px] opacity-70 mb-2"
//                               style={{
//                                 color: THEME.sub,
//                               }}
//                             >
//                               지식
//                             </span>
//                             <div className="space-y-1">
//                               {Array.isArray(c?.knowledge?.comparative_notes) &&
//                               c.knowledge.comparative_notes.length > 0 ? (
//                                 c.knowledge.comparative_notes.map(
//                                   (note, idx) => (
//                                     <div
//                                       key={idx}
//                                       className="text-sm font-medium leading-relaxed"
//                                       style={{
//                                         color: THEME.text,
//                                       }}
//                                     >
//                                       • {note}
//                                     </div>
//                                   ),
//                                 )
//                               ) : (
//                                 <div
//                                   className="text-sm"
//                                   style={{
//                                     color: THEME.sub,
//                                   }}
//                                 >
//                                   비고 없음
//                                 </div>
//                               )}
//                             </div>
//                           </div>

//                           <div>
//                             <span
//                               className="block text-[12px] opacity-70 mb-2"
//                               style={{
//                                 color: THEME.sub,
//                               }}
//                             >
//                               성격
//                             </span>
//                             <div className="space-y-1">
//                               {c?.traits?.ocean &&
//                               typeof c.traits.ocean === "object" ? (
//                                 Object.entries(c.traits.ocean).map(
//                                   ([key, val]) => {
//                                     const labelMap = {
//                                       openness: "개방성",
//                                       neuroticism: "신경성",
//                                       extraversion: "외향성",
//                                       agreeableness: "친화성",
//                                       conscientiousness: "성실성",
//                                     };
//                                     const label = labelMap[key] ?? key;
//                                     return (
//                                       <div
//                                         key={key}
//                                         className="flex justify-between items-center"
//                                       >
//                                         <span
//                                           className="text-[12px] opacity-70"
//                                           style={{
//                                             color: THEME.sub,
//                                           }}
//                                         >
//                                           {label}
//                                         </span>
//                                         <span
//                                           className="text-sm font-medium"
//                                           style={{
//                                             color: THEME.text,
//                                           }}
//                                         >
//                                           {val}
//                                         </span>
//                                       </div>
//                                     );
//                                   },
//                                 )
//                               ) : (
//                                 <div
//                                   className="text-sm"
//                                   style={{
//                                     color: THEME.sub,
//                                   }}
//                                 >
//                                   성격 정보 없음
//                                 </div>
//                               )}
//                             </div>
//                           </div>
//                         </div>
//                       </div>
//                     </button>
//                   ))}
//                 </div>
//               )}

//               {/* 시작 버튼: 초기 실행을 이미 했으면 숨김 */}
//               {selectedScenario &&
//                 selectedCharacter &&
//                 simulationState === "IDLE" &&
//                 !pendingAgentDecision &&
//                 !showReportPrompt &&
//                 !hasInitialRun && (
//                   <div className="flex justify-center">
//                     <button
//                       onClick={startSimulation}
//                       disabled={startDisabled}
//                       className={`px-8 py-3 rounded-lg font-semibold text-lg ${
//                         startDisabled ? "opacity-60 cursor-not-allowed" : ""
//                       }`}
//                       style={{
//                         backgroundColor: THEME.blurple,
//                         color: THEME.white,
//                         boxShadow: "0 10px 24px rgba(0,0,0,.35)",
//                       }}
//                     >
//                       <Play className="inline mr-3" size={20} /> 시뮬레이션 시작
//                     </button>
//                   </div>
//                 )}
//             </div>
//           </div>

//           <div
//             className="px-6 py-4 flex items-center justify-between rounded-bl-3xl rounded-br-3xl"
//             style={{
//               backgroundColor: THEME.panel,
//               borderTop: `1px solid ${THEME.border}`,
//             }}
//           >
//             <div className="flex items-center gap-4">
//               <Clock size={18} color={THEME.sub} />
//               <span
//                 className="text-base font-medium"
//                 style={{ color: THEME.sub }}
//               >
//                 진행률: {Math.round(progress)}%
//               </span>
//               <div
//                 className="w-48 h-3 rounded-full overflow-hidden"
//                 style={{ backgroundColor: THEME.panelDark }}
//               >
//                 <div
//                   className="h-3 rounded-full transition-all duration-300"
//                   style={{
//                     width: `${progress}%`,
//                     backgroundColor: THEME.blurple,
//                   }}
//                 />
//               </div>
//             </div>
//             <div className="flex items-center gap-3">
//               <span
//                 className="text-base font-medium"
//                 style={{ color: THEME.sub }}
//               >
//                 상태: {simulationState}
//               </span>
//               {simulationState === "FINISH" && (
//                 <button
//                   onClick={resetToSelection}
//                   className="px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200"
//                   style={{
//                     backgroundColor: THEME.blurple,
//                     color: THEME.white,
//                     boxShadow: "0 6px 12px rgba(0,0,0,.25)",
//                   }}
//                 >
//                   다시 선택하기
//                 </button>
//               )}
//             </div>
//           </div>
//         </div>
//       </div>

//       {/* 완료 배너: pendingAgentDecision 동안 리포트 버튼 비활성 */}
//       {sessionResult && progress >= 100 && (
//         <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50">
//           <div
//             className="px-8 py-4 rounded-xl"
//             style={{
//               backgroundColor: THEME.panel,
//               border: `1px solid ${THEME.border}`,
//               boxShadow: "0 10px 24px rgba(0,0,0,.35)",
//               color: THEME.text,
//             }}
//           >
//             <div className="flex items-center gap-5">
//               <div className="flex items-center gap-3">
//                 {sessionResult.isPhishing ? (
//                   <AlertTriangle size={24} color={THEME.warn} />
//                 ) : (
//                   <Check size={24} color={THEME.success} />
//                 )}
//                 <span
//                   className="font-semibold text-lg"
//                   style={{
//                     color: sessionResult.isPhishing
//                       ? THEME.warn
//                       : THEME.success,
//                   }}
//                 >
//                   {sessionResult.isPhishing ? "피싱 감지" : "정상 대화"}
//                 </span>
//               </div>
//               <button
//                 onClick={() => setCurrentPage("report")}
//                 disabled={pendingAgentDecision}
//                 aria-disabled={pendingAgentDecision}
//                 title={
//                   pendingAgentDecision
//                     ? "에이전트 사용 여부 결정 후에 리포트를 보실 수 있습니다."
//                     : "리포트 보기"
//                 }
//                 className={`px-6 py-2 rounded-md text-base font-medium transition-all duration-150`}
//                 style={{
//                   backgroundColor: THEME.blurple,
//                   color: THEME.white,
//                   pointerEvents: pendingAgentDecision ? "none" : undefined,
//                   opacity: pendingAgentDecision ? 0.5 : 1,
//                 }}
//               >
//                 리포트 보기
//               </button>
//             </div>
//           </div>
//         </div>
//       )}

//       {/* 리포트 안내 모달 */}
//       {showReportPrompt && (
//         <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 z-50">
//           <div
//             className="p-6 rounded-lg border"
//             style={{
//               borderColor: THEME.border,
//               backgroundColor: THEME.panel,
//             }}
//           >
//             <h3
//               className="text-xl font-semibold mb-3"
//               style={{ color: THEME.text }}
//             >
//               시뮬레이션이 완료되었습니다
//             </h3>
//             <p
//               className="text-sm"
//               style={{ color: THEME.sub, marginBottom: 16 }}
//             >
//               결과 리포트를 확인하시겠습니까?
//             </p>
//             <div className="flex justify-end gap-4">
//               <button
//                 onClick={() => setShowReportPrompt(false)}
//                 className="px-4 py-2 rounded"
//                 style={{
//                   backgroundColor: THEME.panelDark,
//                   color: THEME.text,
//                 }}
//               >
//                 닫기
//               </button>
//               <button
//                 onClick={() => setCurrentPage("report")}
//                 disabled={pendingAgentDecision}
//                 aria-disabled={pendingAgentDecision}
//                 title={
//                   pendingAgentDecision
//                     ? "에이전트 사용 여부 결정 후에 리포트를 보실 수 있습니다."
//                     : "리포트 보기"
//                 }
//                 className={`px-4 py-2 rounded`}
//                 style={{
//                   backgroundColor: THEME.blurple,
//                   color: THEME.white,
//                   pointerEvents: pendingAgentDecision ? "none" : undefined,
//                   opacity: pendingAgentDecision ? 0.5 : 1,
//                 }}
//               >
//                 리포트 보기
//               </button>
//             </div>
//           </div>
//         </div>
//       )}
//     </div>
//   );
// };

// export default SimulatorPage;
