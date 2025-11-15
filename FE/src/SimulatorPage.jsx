import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import {
  Play,
  Clock,
  FileBarChart2,
  Terminal,
  Lightbulb,
  Home,
} from "lucide-react";
import HudBar from "./HudBar";
import Badge from "./Badge";
import SelectedCard from "./SelectedCard";
import Chip from "./Chip";
import MessageBubble from "./MessageBubble";
import SpinnerMessage from "./SpinnerMessage";
import CustomCharacterCreate from "./CustomCharacterCreate";
import TTSModal from "./components/TTSModal";
import CustomScenarioButton from "./CustomScenarioButton";
import CustomScenarioModal from "./CustomScenarioModal";
import TerminalLog from "./components/TerminalLog";
import InvestigationBoard from "./InvestigationBoard";
//import InlinePhishingSummaryBox from "./InlinePhishingSummaryBox";
import { THEME as BASE_THEME } from "./constants/colors";
import { useSimStream } from "./hooks/useSimStream";

const SIMPLE_BOARD_MODE = false;

/* 이미지 로드 유틸 */
const getVictimImage = (photoPath) => {
  if (!photoPath) return null;
  try {
    const fileName = photoPath.split("/").pop();
    if (fileName)
      return new URL(`./assets/victims/${fileName}`, import.meta.url).href;
  } catch {
    console.warn("이미지 로드 실패");
  }
  return null;
};

const countChatMessages = (messages = []) =>
  Array.isArray(messages)
    ? messages.filter((m) => (m?.type ?? m?._kind) === "chat").length
    : 0;

const SimulatorPage = ({
  COLORS,
  setCurrentPage,
  selectedScenario,
  setSelectedScenario,
  selectedCharacter,
  setSelectedCharacter,
  simulationState,
  //messages,
  setMessages, // ✅ 추가: 외부에서 messages state 관리 중
  sessionResult,
  progress,
  setProgress,
  //startSimulation,
  startAgentRun,
  declineAgentRun,
  scenarios,
  characters,
  scrollContainerRef: injectedScrollContainerRef,
  addSystem,
  pendingAgentDecision,
  showReportPrompt,
  setShowReportPrompt,
  hasInitialRun,
  hasAgentRun,
  agentRunning,
  agentVerbose,
  setAgentVerbose,
  boardDelaySec = 3,
  intermissionSec = 3,
  logTickMs = 200,
  victimImageUrl,
}) => {
  //SSE 이벤트 실행 트리거
  const {
    logs, messages, start, running, judgements, guidances, preventions
  } = useSimStream(setMessages, {
    // 필요 시 넣을 수 있는 콜백/상태 전달 (옵션)
    addSystem,                 // 있으면 전달
    setProgress,               // 있으면 전달
    // 🔴 필수: 선택된 값 전달
    selectedScenario,
    selectedCharacter,
  });  
  
  // ----------------------------------------------------------
  // 🧩 메시지 정규화 유틸 (백엔드 turn → MessageBubble 형태로)
  // ----------------------------------------------------------
  // const convertTurnToMessage = (turn) => {
  //   if (!turn) return null;

  //   const sender =
  //     turn.sender ||
  //     turn.role ||
  //     (turn.meta?.sender ?? "").toLowerCase() ||
  //     "system";

  //   let content = turn.text || turn.content || "";

  //   // 🔥 피해자 메시지는 JSON일 수 있음 → 파싱 시도
  //   if (sender === "victim") {
  //     try {
  //       const parsed = JSON.parse(content);
  //       content = {
  //         dialogue: parsed.dialogue ?? "",
  //         thoughts: parsed.thoughts ?? null,
  //         is_convinced: parsed.is_convinced ?? null,
  //       };
  //     } catch {
  //       // JSON이 아닐 경우 text 그대로
  //       content = { dialogue: content };
  //     }
  //   } else {
  //     // 공격자/시스템 발화는 문자열로 처리
  //     content = { dialogue: content };
  //   }

  //   return {
  //     sender,
  //     content,
  //     timestamp: new Date().toISOString(),
  //     type: "chat",
  //     _kind: "chat",
  //   };
  // };

  /* ----------------------------------------------------------
   🧩 상태
  ---------------------------------------------------------- */
  const needScenario = !selectedScenario;
  const needCharacter = !selectedCharacter;

  // ✅ [1] 시뮬레이션 버튼 표시 여부 제어용 상태 추가
  const [showStartButton, setShowStartButton] = useState(true);

  const [selectedTag, setSelectedTag] = useState(null);
  const [showCustomModal, setShowCustomModal] = useState(false);
  const [customScenarios, setCustomScenarios] = useState([]);
  const [customVictims, setCustomVictims] = useState([]);
  const [openTTS, setOpenTTS] = useState(false);

  // guidance / prevention 도 동일 패턴으로 가드
  const normalizedGuidance = useMemo(() => {
    const ev = guidances?.event ?? guidances;
    return ev?.content ?? ev ?? null;
  }, [guidances]);

  const normalizedPrevention = useMemo(() => {
    const ev = preventions?.event ?? preventions;
    return ev?.content ?? ev ?? null;
  }, [preventions]);

  // 🎯 스크롤/탭/보드 상태
  const localScrollContainerRef = useRef(null);
  const scrollRef = injectedScrollContainerRef ?? localScrollContainerRef;
  const [activeAgentTab, setActiveAgentTab] = useState("log");
  const [showBoardContent, setShowBoardContent] = useState(false);

  // 1️⃣ 분석 데이터 준비 여부 체크
  const hasJudgement = judgements.length > 0;
  const hasGuidance = guidances.length > 0;
  const hasPrevention = preventions.length > 0;
  const hasAnyAgentData = hasJudgement || hasGuidance || hasPrevention;

  // 2️⃣ 데이터가 오면 자동으로 보드 활성화
  useEffect(() => {
    if (hasAnyAgentData && !showBoardContent) {
      setShowBoardContent(true);
    }
  }, [hasAnyAgentData, showBoardContent]);

  // ✅ SSE 스트림 실행 + handleStartStream 실행 시 버튼 숨김 처리 추가
  const handleStartStream = useCallback(() => {
  try {
    // 1) 존재 검증
    if (!selectedScenario || !selectedScenario.id) {
      console.error("❌ 시나리오 미선택/ID 없음:", selectedScenario);
      return;
    }
    if (!selectedCharacter || !selectedCharacter.id) {
      console.error("❌ 캐릭터 미선택/ID 없음:", selectedCharacter);
      return;
    }

    // 2) 숫자 보정(백엔드가 int 기대 시)
    const scenarioId = Number(selectedScenario.id);
    const victimId   = Number(selectedCharacter.id);
    if (!Number.isFinite(scenarioId) || !Number.isFinite(victimId)) {
      console.error("❌ ID 타입이 숫자가 아님:", { scenarioId, victimId });
      return;
    }

    setShowStartButton(false);

    // 3) 절대 임의 기본값(1) 사용 금지: 정확한 JSON만 전송
    start({
      offender_id: 1,
      victim_id: victimId,
      scenario_id: scenarioId,
    });
  } catch (err) {
    console.error("SimulatorPage 실행 중 오류:", err);
  }
}, [start, selectedScenario, selectedCharacter]);


  /* ✅ 새 메시지 들어올 때 자동 스크롤 유지 */
  // useEffect(() => {
  //   const el = scrollRef.current;
  //   if (!el) return;
  //   // 🎯 시나리오/캐릭터 선택 중에는 항상 맨 위로
  //   if (needScenario || needCharacter) {
  //     el.scrollTop = 0;
  //     return;
  //   }
  //   // 🎯 시뮬레이션 대화 중에는 맨 아래로 자동 이동
  //   el.scrollTop = el.scrollHeight;
  // }, [messages, needScenario, needCharacter]);

  // 자동 스크롤 (간단 버전)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // 🎯 시나리오/캐릭터 선택 중에는 항상 맨 위로 고정
    if (needScenario || needCharacter) {
      el.scrollTop = 0;
      return;
    }

    // 🎯 대화 중일 때만 아래로 자동 스크롤
    el.scrollTop = el.scrollHeight;
  }, [messages, needScenario, needCharacter]);

  // json 출력
  const JsonBlock = ({ title = "", obj, theme }) => {
    if (!obj) return null;
    return (
      <div
        className="mt-4 p-3 rounded-lg border text-xs overflow-auto"
        style={{
          borderColor: theme.border,
          backgroundColor: theme.panelDarker,
          color: theme.text,
          maxHeight: 300,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {title && (
          <div
            className="font-semibold mb-2"
            style={{ color: theme.sub }}
          >
            {title}
          </div>
        )}
        <pre>{JSON.stringify(obj, null, 2)}</pre>
      </div>
    );
  };
  // judgement 구조가 {type:'judgement', event:{...}} 일 수도/아닐 수도 있으니 통합
  const normalizedJudgement = useMemo(() => {
    const ev = judgements?.event ?? judgements;
    const raw = ev?.content ?? ev;
    if (!raw || typeof raw !== "object") return null;
    return {
      case_id: raw.case_id,
      run_no: raw.run_no,
      phishing: raw.phishing,
      risk: raw.risk,                 // { score, level, rationale }
      continue: raw["continue"],         // { recommendation, reason }
      evidence: raw.evidence,         // string
      victim_vulnerabilities: raw.victim_vulnerabilities, // string[]
      ok: raw.ok,
      persisted: raw.persisted,
    };
  }, [judgements]);

  // ✅ applied_guidance 추출
  const appliedGuidance = useMemo(() => {
    return (
      judgements?.meta?.scenario?.enhancement_info?.applied_guidance ??
      "지침 데이터 없음"
    );
  }, [judgements]);

  // 진행률 계산에 쓰는 로컬 카운터(선언을 hasChatLog보다 위에 둠)
  const countChatMessagesLocal = (msgs = []) =>
    msgs.filter((m) => (m?.type ?? m?._kind) === "chat").length;

  // 🧩 SimulatorPage 내부에 넣을 normalizeMessage (완성형)
const normalizeMessage = (m) => {
  if (!m) return null;

  // 1) role 통일
  const role = (m.role || "").toLowerCase();

  // 2) timestamp 보정
  const timestamp = m.timestamp ?? new Date().toISOString();

  // 3) raw text는 backend 구조 상 반드시 m.text
  const raw = typeof m.text === "string" ? m.text : "";

  let content = raw;

  // 4) 피해자 메시지(JSON 문자열 처리)
  if (role === "victim") {
    const trimmed = raw.trim();

    // JSON 여러 줄 대응 → 앞뒤 {}로만 체크
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        const p = JSON.parse(trimmed);
        content = {
          dialogue: p.dialogue ?? "",
          thoughts: p.thoughts ?? null,
          is_convinced: p.is_convinced ?? null,
        };
      } catch (err) {
        console.warn("⚠ victim JSON parsing failed:", trimmed);
        // 실패 시 그냥 문자열로 처리
        content = raw;
      }
    }
  }

  return {
    id: crypto.randomUUID(),
    role,
    sender: role,
    timestamp,
    _kind: "chat",

    // UI가 사용하는 통일된 content 값
    content,

    side: role === "victim" ? "right" : role === "offender" ? "left" : "center",
    label: role === "victim" ? "피해자" : role === "offender" ? "피싱범" : "시스템",
  };
};




  const hasChatLog = useMemo(
    () => countChatMessagesLocal(messages) > 0,
    [messages]
  );

  /* ----------------------------------------------------------
   🎨 테마
  ---------------------------------------------------------- */
  const THEME = {
    ...(COLORS ?? BASE_THEME),
    bg: "#030617",
    panel: "#061329",
    panelDark: "#04101f",
    panelDarker: "#020812",
    border: "#A8862A",
    text: "#FFFFFF",
    sub: "#BFB38A",
    blurple: "#A8862A",
    danger: "#ff4d4f",
    warn: "#facc15",
  };

  // 진행률 계산
  useEffect(() => {
    if (typeof setProgress !== "function") return;
    const pct = Math.min(
      100,
      Math.round((countChatMessagesLocal(messages) / 10) * 100)
    );
    setProgress(pct);
  }, [messages, setProgress]);

  // 보드 표시 지연
  useEffect(() => {
    const timer = setTimeout(() => setShowBoardContent(true), 3000);
    return () => clearTimeout(timer);
  }, []);

  /* ----------------------------------------------------------
   🏠 홈버튼 (초기화)
  ---------------------------------------------------------- */
  const handleGoHome = () => {
    setSelectedScenario(null);
    setSelectedCharacter(null);
    setProgress(0);
    setCurrentPage("landing");
  };

  /* ----------------------------------------------------------
   🎯 시나리오 필터링 + 커스텀 통합
  ---------------------------------------------------------- */
  const filteredScenarios = useMemo(() => {
    if (!selectedTag) return scenarios;
    return scenarios.filter(
      (s) =>
        s.type === selectedTag ||
        (Array.isArray(s.tags) && s.tags.includes(selectedTag))
    );
  }, [selectedTag, scenarios]);

  const combinedScenarios = useMemo(() => {
    const base = filteredScenarios ?? [];
    const custom = selectedTag
      ? customScenarios.filter((c) => c.type === selectedTag)
      : customScenarios;
    return [...base, ...custom];
  }, [filteredScenarios, customScenarios, selectedTag]);

  const handleSaveCustomScenario = (scenario) => {
    setCustomScenarios((prev) => [...prev, scenario]);
    setShowCustomModal(false);
  };

  /* ----------------------------------------------------------
   🧠 에이전트 로그 (점진 표시)
  ---------------------------------------------------------- */
  const computedAgentLogText = useMemo(() => {
    if (!sessionResult?.agentLogs) return "";
    return sessionResult.agentLogs
      .map((log) => `[${log.role}] ${log.content}`)
      .join("\n");
  }, [sessionResult?.agentLogs]);

  const agentLogLines = useMemo(
    () =>
      computedAgentLogText
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean),
    [computedAgentLogText]
  );
  const [displayedAgentLogText, setDisplayedAgentLogText] = useState("");
  const logIndexRef = useRef(0);

  useEffect(() => {
    if (!agentLogLines.length) return;
    const timer = setInterval(() => {
      if (logIndexRef.current >= agentLogLines.length) return clearInterval(timer);
      setDisplayedAgentLogText((prev) =>
        prev
          ? `${prev}\n${agentLogLines[logIndexRef.current]}`
          : agentLogLines[logIndexRef.current]
      );
      logIndexRef.current++;
    }, logTickMs);
    return () => clearInterval(timer);
  }, [agentLogLines, logTickMs]);

  /* ----------------------------------------------------------
   ⏳ 분석 보드 지연 표시
  ---------------------------------------------------------- */
  useEffect(() => {
    if (!hasChatLog) return setShowBoardContent(false);
    const t = setTimeout(() => setShowBoardContent(true), boardDelaySec * 1000);
    return () => clearTimeout(t);
  }, [hasChatLog, boardDelaySec]);

  /* ----------------------------------------------------------
   🧩 렌더링
  ---------------------------------------------------------- */
  return (
    <div className="min-h-screen" style={{ backgroundColor: THEME.bg }}>
      <div className="container mx-auto px-6 py-12">
        <div
          className="w-full max-w-[1400px] mx-auto h-[calc(100vh-3rem)] rounded-3xl shadow-2xl border flex flex-col"
          style={{ borderColor: THEME.border, backgroundColor: THEME.panel }}
        >
          {/* 상단 HUD */}
          <HudBar COLORS={THEME} />

          {/* 상단 상태 + 홈버튼 */}
          <div
            className="px-6 py-4 flex items-center justify-between border-b"
            style={{ borderColor: THEME.border }}
          >
            <div className="flex items-center gap-3">
              <Badge tone={selectedScenario ? "primary" : "neutral"} COLORS={THEME}>
                {selectedScenario ? selectedScenario.name : "시나리오 미선택"}
              </Badge>
              <Badge tone={selectedCharacter ? "success" : "neutral"} COLORS={THEME}>
                {selectedCharacter ? selectedCharacter.name : "캐릭터 미선택"}
              </Badge>
            </div>

            {/* <button
              onClick={handleGoHome}
              className="px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 border"
              style={{
                backgroundColor: THEME.panelDark,
                borderColor: THEME.border,
                color: THEME.sub,
              }}
            >
              <Home size={16} />
              홈으로
            </button> */}
          </div>

          {/* 메인 */}
          <div
            className="flex-1 flex min-h-0"
            style={{ backgroundColor: THEME.bg }}
          >
            {/* 왼쪽: 시나리오 / 캐릭터 / 대화 */}
            <div className="flex flex-col flex-1 overflow-y-auto" ref={scrollRef}>
              {/* 1️⃣ 시나리오 선택 */}
              {needScenario && (
                <SelectedCard
                  title="시나리오 선택"
                  subtitle="유형 칩을 눌러 필터링한 뒤, 상세 시나리오를 선택하세요."
                  COLORS={THEME}
                >
                  <div className="mb-4 flex gap-2">
                    {["기관 사칭형", "가족·지인 사칭", "대출사기형"].map((t) => (
                      <Chip
                        key={t}
                        active={selectedTag === t}
                        label={t}
                        onClick={() =>
                          setSelectedTag(selectedTag === t ? null : t)
                        }
                        COLORS={THEME}
                      />
                    ))}
                  </div>

                  <CustomScenarioButton
                    onClick={() => setShowCustomModal(true)}
                    COLORS={THEME}
                  />

                  <div className="space-y-4 mt-4">
                    {combinedScenarios.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => setSelectedScenario(s)}
                        className="w-full text-left rounded-lg p-4 hover:opacity-90"
                        style={{
                          backgroundColor: THEME.panelDark,
                          border: `1px solid ${THEME.border}`,
                          color: THEME.text,
                        }}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-semibold text-lg">{s.name}</span>
                          <Badge
                            tone={s.type === "커스텀" ? "secondary" : "primary"}
                            COLORS={THEME}
                          >
                            {s.type}
                          </Badge>
                        </div>
                        <p style={{ color: THEME.sub }}>
                          {s.profile?.purpose ?? "설명 없음"}
                        </p>
                      </button>
                    ))}
                  </div>
                </SelectedCard>
              )}

              {/* 2️⃣ 캐릭터 선택 */}
              {!needScenario && needCharacter && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 flex-1 min-h-0 overflow-y-auto pr-1">
                  <CustomCharacterCreate
                    theme={THEME}
                    onCreated={(v) => {
                      setCustomVictims((p) => [...p, v]);
                      setSelectedCharacter(v);
                      addSystem(`커스텀 캐릭터 생성: ${v.name}`);
                    }}
                  />

                  {[...characters, ...customVictims].map((c) => (
                    <button key={c.id} onClick={() => setSelectedCharacter(c)}>
                      <div
                        className="flex flex-col h-full rounded-2xl overflow-hidden border hover:border-[rgba(168,134,42,.25)] transition-colors"
                        style={{
                          backgroundColor: THEME.panelDark,
                          borderColor: THEME.border,
                        }}
                      >
                        {/* 프로필 이미지 */}
                        {getVictimImage(c.photo_path) ? (
                          <div
                            className="w-full h-44 bg-cover bg-center"
                            style={{
                              backgroundImage: `url(${getVictimImage(
                                c.photo_path
                              )})`,
                            }}
                          />
                        ) : (
                          <div
                            className="w-full h-44 flex items-center justify-center text-6xl"
                            style={{ backgroundColor: THEME.panelDarker }}
                          >
                            {c.avatar ?? "👤"}
                          </div>
                        )}

                        {/* 피해자 상세정보 */}
                        <div className="p-4 flex flex-col gap-3">
                          <div className="flex items-center justify-between">
                            <span
                              className="font-semibold text-lg"
                              style={{ color: THEME.text }}
                            >
                              {c.name}
                            </span>
                            <span
                              className="text-xs px-2 py-1 rounded-md"
                              style={{
                                color: THEME.blurple,
                                backgroundColor: "rgba(168,134,42,.08)",
                                border: `1px solid rgba(168,134,42,.18)`,
                              }}
                            >
                              프로필
                            </span>
                          </div>

                          {/* 기본 정보 */}
                          <div
                            className="space-y-2 text-sm"
                            style={{ color: THEME.sub }}
                          >
                            <div className="flex justify-between items-center">
                              <span className="text-[12px] opacity-70">나이</span>
                              <span
                                className="font-medium"
                                style={{ color: THEME.text }}
                              >
                                {c.meta.age}
                              </span>
                            </div>
                            <div className="flex justify-between items-center">
                              <span className="text-[12px] opacity-70">성별</span>
                              <span
                                className="font-medium"
                                style={{ color: THEME.text }}
                              >
                                {c.meta.gender}
                              </span>
                            </div>
                            <div className="flex justify-between items-center">
                              <span className="text-[12px] opacity-70">거주지</span>
                              <span
                                className="font-medium truncate ml-2"
                                style={{ color: THEME.text }}
                              >
                                {c.meta.address}
                              </span>
                            </div>
                            <div className="flex justify-between items-center">
                              <span className="text-[12px] opacity-70">학력</span>
                              <span
                                className="font-medium truncate ml-2"
                                style={{ color: THEME.text }}
                              >
                                {c.meta.education}
                              </span>
                            </div>
                          </div>

                          {/* 지식 */}
                          <div>
                            <span
                              className="block text-[12px] opacity-70 mb-2"
                              style={{ color: THEME.sub }}
                            >
                              지식
                            </span>
                            <div className="space-y-1">
                              {Array.isArray(
                                c?.knowledge?.comparative_notes
                              ) && c.knowledge.comparative_notes.length > 0 ? (
                                c.knowledge.comparative_notes.map((note, idx) => (
                                  <div
                                    key={idx}
                                    className="text-sm font-medium leading-relaxed"
                                    style={{ color: THEME.text }}
                                  >
                                    • {note}
                                  </div>
                                ))
                              ) : (
                                <div className="text-sm" style={{ color: THEME.sub }}>
                                  비고 없음
                                </div>
                              )}
                            </div>
                          </div>

                          {/* 성격 */}
                          <div>
                            <span
                              className="block text-[12px] opacity-70 mb-2"
                              style={{ color: THEME.sub }}
                            >
                              성격
                            </span>
                            <div className="space-y-1">
                              {c?.traits?.ocean && typeof c.traits.ocean === "object" ? (
                                Object.entries(c.traits.ocean).map(([key, val]) => {
                                  const labelMap = {
                                    openness: "개방성",
                                    neuroticism: "신경성",
                                    extraversion: "외향성",
                                    agreeableness: "친화성",
                                    conscientiousness: "성실성",
                                  };
                                  const label = labelMap[key] ?? key;
                                  return (
                                    <div
                                      key={key}
                                      className="flex justify-between items-center"
                                    >
                                      <span
                                        className="text-[12px] opacity-70"
                                        style={{ color: THEME.sub }}
                                      >
                                        {label}
                                      </span>
                                      <span
                                        className="text-sm font-medium"
                                        style={{ color: THEME.text }}
                                      >
                                        {val}
                                      </span>
                                    </div>
                                  );
                                })
                              ) : (
                                <div className="text-sm" style={{ color: THEME.sub }}>
                                  성격 정보 없음
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {/* 3️⃣ 대화 + 로그/분석 */}
              {!needScenario && !needCharacter && (
                <>
                  <div className="flex flex-1 min-h-0">
                    {/* 왼쪽: 대화 */}
                    <div className="flex-1 p-6 overflow-y-auto" ref={scrollRef}>
                      {/* ✅ 시뮬레이션 시작 버튼 (중앙 상단) */}
                      {showStartButton ? (
                        <div className="flex justify-center mt-6">
                          <button
                            onClick={handleStartStream}
                            disabled={running}
                            className="px-8 py-3 rounded-lg font-semibold text-lg"
                            style={{
                              backgroundColor: THEME.blurple,
                              color: THEME.white,
                              boxShadow: "0 10px 24px rgba(0,0,0,.35)",
                            }}
                          >
                            <Play className="inline mr-3" size={20} />
                            {running ? "시뮬레이션 진행 중..." : "시뮬레이션 시작"}
                          </button>
                        </div>
                      ) : (
                        // ✅ 버튼이 사라지고, 대화가 아직 안 나왔을 때만 Spinner 표시
                        !messages?.length && (
                          <SpinnerMessage simulationState="RUNNING" COLORS={THEME} />
                        )
                      )}

                      {/* 대화 렌더링 */}
                      {!messages?.length && (
                        <SpinnerMessage
                          simulationState={simulationState}
                          COLORS={THEME}
                        />
                      )}
                      {messages
                        ?.filter((m) => {
                          const msgType = m?.type || m?._kind;
                          return msgType === "chat" || msgType === "message";
                        })
                        .map((m, idx) => {
                          const nm = normalizeMessage(m);
                          
                          return (
                            <MessageBubble
                              key={`${nm.role ?? "unknown"}-${nm.timestamp ?? Date.now()}-${idx}`}
                              message={nm}
                              label={nm.label}
                              side={nm.side}
                              role={nm.role}
                              selectedCharacter={selectedCharacter}
                              victimImageUrl={victimImageUrl}
                              COLORS={THEME}
                            />
                          );
                        })}
                    </div>

                    {/* 오른쪽: 로그 / 분석 */}
                    <div
                      className="flex flex-col w-[30%] border-l"
                      style={{
                        borderColor: THEME.border,
                        backgroundColor: THEME.panelDark,
                      }}
                    >
                      <div
                        className="px-3 py-3 border-b"
                        style={{ borderColor: THEME.border }}
                      >
                        <div className="flex gap-4">
                          <button
                            className={`flex items-center gap-2 text-sm font-semibold ${
                              activeAgentTab === "log" ? "opacity-100" : "opacity-60"
                            }`}
                            onClick={() => setActiveAgentTab("log")}
                            style={{ color: THEME.text }}
                          >
                            <Terminal size={16} /> 에이전트 로그
                          </button>
                          <button
                            className={`flex items-center gap-2 text-sm font-semibold ${
                              activeAgentTab === "insight"
                                ? "opacity-100"
                                : "opacity-60"
                            }`}
                            onClick={() => setActiveAgentTab("insight")}
                            style={{ color: THEME.text }}
                          >
                            <Lightbulb size={16} /> 에이전트 분석
                          </button>
                        </div>
                      </div>

                      <div className="flex-1 overflow-auto p-4">
                        {activeAgentTab === "log" ? (
                          <TerminalLog logs={logs} COLORS={THEME} />
                        ) : showBoardContent && (hasJudgement || hasGuidance || hasPrevention) ? (
                          <div className="flex flex-col gap-4">
                            {/* ✅ InvestigationBoard 단일 호출 */}
                            <InvestigationBoard
                              COLORS={THEME}
                              judgements={judgements}
                              guidances={guidances}
                              preventions={preventions}
                            />

                            {/* (선택) 원본 데이터 확인용 JSON 블록 */}
                            {judgements && (
                              <JsonBlock title="[SSE Event] judgements (raw)" obj={judgements} theme={THEME} />
                            )}
                            {guidances && (
                              <JsonBlock title="[SSE Event] guidances (raw)" obj={guidances} theme={THEME} />
                            )}
                            {preventions && (
                              <JsonBlock title="[SSE Event] preventions (raw)" obj={preventions} theme={THEME} />
                            )}
                          </div>
                        ) : (
                          <div
                            className="p-4 text-sm opacity-70"
                            style={{ color: THEME.sub }}
                          >
                            분석 데이터를 불러오는 중입니다...
                          </div>
                        )}
                    </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* 하단 진행률 */}
          <div
            className="px-6 py-4 flex items-center justify-between border-t rounded-3xl"
            style={{ borderColor: THEME.border, backgroundColor: THEME.panel }}
          >
            <div className="flex items-center gap-3">
              <Clock size={18} color={THEME.sub} />
              <span style={{ color: THEME.sub }}>
                진행률: {Math.round(progress)}%
              </span>
            </div>
            {progress >= 100 && (
              <button
                onClick={() => setCurrentPage("report")}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{
                  backgroundColor: THEME.blurple,
                  color: THEME.white,
                  boxShadow: "0 6px 12px rgba(0,0,0,.25)",
                }}
              >
                <FileBarChart2 size={18} className="inline mr-2" />
                리포트 보기
              </button>
            )}

            {progress >= 100 && (
              <button
                onClick={() => setOpenTTS(true)}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{
                  backgroundColor: THEME.blurple,
                  color: THEME.white,
                }}
              >
                음성 듣기
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 모달 */}
      <TTSModal
        isOpen={openTTS}
        onClose={() => setOpenTTS(false)}
        COLORS={THEME}
      />

      {/* <CustomScenarioModal
        open={showCustomModal}
        onClose={() => setShowCustomModal(false)}
        onSave={handleSaveCustomScenario}
        COLORS={THEME}
        selectedTag={selectedTag}
      /> */}
    </div>
  );
};

export default SimulatorPage;