// src/App.jsx
import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import LandingPage from "./LandingPage";
import SimulatorPage from "./SimulatorPage";
import ReportPage from "./ReportPage";

const COLORS = {
  bg: "#1E1F22",
  panel: "#2B2D31",
  border: "#3F4147",
  text: "#DCDDDE",
  sub: "#B5BAC1",
  blurple: "#5865F2",
  success: "#57F287",
  warn: "#FEE75C",
  danger: "#ED4245",
  black: "#0A0A0A",
  white: "#FFFFFF",
};

const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_PREFIX = "/api";
export const API_ROOT = `${API_BASE}${API_PREFIX}`;

console.log("VITE_API_URL =", import.meta.env.VITE_API_URL);
console.log("API_ROOT =", API_ROOT);

/* ================== API 헬퍼 ================== */
async function fetchWithTimeout(
  url,
  { method = "GET", headers = {}, body = null, timeout = 100000 } = {},
) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  const opts = { method, headers: { ...headers }, signal: controller.signal };
  if (body != null) {
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
    opts.headers["Content-Type"] =
      opts.headers["Content-Type"] || "application/json";
  }

  try {
    const res = await fetch(url, opts);
    clearTimeout(id);
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} ${txt}`);
    }
    const txt = await res.text();
    return txt ? JSON.parse(txt) : null;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("요청 타임아웃");
    throw err;
  } finally {
    clearTimeout(id);
  }
}

async function getOffenders() {
  return fetchWithTimeout(`${API_ROOT}/offenders/`);
}
async function getVictims() {
  return fetchWithTimeout(`${API_ROOT}/victims/`);
}
async function getConversationBundle(caseId) {
  return fetchWithTimeout(
    `${API_ROOT}/conversations/${encodeURIComponent(caseId)}`,
  );
}

// ✅ SSE 스트리밍
async function* streamReactSimulation(payload) {
  const response = await fetch(`${API_ROOT}/react-agent/simulation/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          yield data;
        } catch (e) {
          console.warn("SSE 파싱 실패:", line);
        }
      }
    }
  }
}

function extractDialogueOrPlainText(s) {
  if (!s) return s;
  // 코드펜스 제거
  const cleaned = s.replace(/```(?:json)?/gi, "").trim();
  try {
    const m = cleaned.match(/\{[\s\S]*\}/);
    if (m) {
      const obj = JSON.parse(m[0]);
      if (obj && typeof obj === "object") {
        if (typeof obj.dialogue === "string" && obj.dialogue.trim()) {
          return obj.dialogue.trim();
        }
        if (typeof obj.thoughts === "string" && obj.thoughts.trim()) {
          return obj.thoughts.trim();
        }
      }
    }
  } catch (_) {}
  // 과한 공백 정리
  return cleaned.replace(/[ \t]+/g, " ").replace(/\s*\n\s*/g, "\n").trim();
}

/* ================== App 컴포넌트 ================== */
const App = () => {
  const [currentPage, setCurrentPage] = useState("landing");

  // data
  const [scenarios, setScenarios] = useState([]);
  const [characters, setCharacters] = useState([]);
  const [defaultCaseData, setDefaultCaseData] = useState(null);

  // selection / simulation
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [selectedCharacter, setSelectedCharacter] = useState(null);
  const [simulationState, setSimulationState] = useState("IDLE"); // IDLE, PREPARE, RUNNING, FINISH
  const [messages, setMessages] = useState([]);
  const [sessionResult, setSessionResult] = useState(null);
  const [progress, setProgress] = useState(0);

  // modal / decision flags
  const [showReportPrompt, setShowReportPrompt] = useState(false);
  const [hasInitialRun, setHasInitialRun] = useState(false);

  // refs
  const scrollContainerRef = useRef(null);
  const simIntervalRef = useRef(null);

  // 중복 턴 방지용
  const seenTurnsRef = useRef(new Set());

  // UI loading/error
  const [dataLoading, setDataLoading] = useState(true);
  const [dataError, setDataError] = useState(null);
  const [currentCaseId, setCurrentCaseId] = useState(null);

  const addSystem = (content) =>
    setMessages((prev) => [
      ...prev,
      { type: "system", content, timestamp: new Date().toLocaleTimeString() },
  ]);

const addChat = (sender, content, timestamp = null, senderLabel = null, side = null, meta = null) =>
    setMessages((prev) => [
      ...prev,
      {
        type: "chat",
        sender,
        senderLabel: senderLabel ?? sender,
        side: side ?? (sender === "offender" ? "left" : "right"),
        content,
        timestamp: timestamp ?? new Date().toLocaleTimeString(),
        ...(meta || {}),
      },
    ]);

  // victim image helper
  const getVictimImage = (photoPath) => {
    if (!photoPath) return null;
    try {
      const fileName = photoPath.split("/").pop();
      if (fileName)
        return new URL(`./assets/victims/${fileName}`, import.meta.url).href;
    } catch (e) {
      console.warn("이미지 로드 실패:", e);
    }
    return null;
  };

  /* 스크롤 자동 하단 고정 */
  const stickToBottom = () => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useLayoutEffect(() => {
    stickToBottom();
  }, [
    messages,
    simulationState,
    sessionResult,
  ]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => stickToBottom());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* 초기 데이터 로드 */
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        setDataLoading(true);
        setDataError(null);
        const [offList, vicList] = await Promise.all([
          getOffenders(),
          getVictims(),
        ]);
        if (!mounted) return;
        setScenarios(Array.isArray(offList) ? offList : []);
        setCharacters(Array.isArray(vicList) ? vicList : []);
      } catch (err) {
        console.error("초기 데이터 로드 실패:", err);
        if (!mounted) return;
        setDataError(err.message || String(err));
      } finally {
        if (mounted) setDataLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  /* ✅ startSimulation - SSE 스트리밍 */
  const startSimulation = async () => {
    if (!selectedScenario || !selectedCharacter) {
      addSystem("시나리오와 캐릭터를 먼저 선택해주세요.");
      return;
    }

    setHasInitialRun(true);
    seenTurnsRef.current = new Set();   // ✅ 중복 키 초기화

    if (simIntervalRef.current) {
      clearInterval(simIntervalRef.current);
      simIntervalRef.current = null;
    }

    setSimulationState("PREPARE");
    setMessages([]);
    setProgress(0);
    setSessionResult(null);
    setCurrentCaseId(null);
    setShowReportPrompt(false);

    addSystem(`시뮬레이션 시작: ${selectedScenario.name} / ${selectedCharacter.name}`);

    try {
      const payload = {
        victim_id: selectedCharacter.id,
        offender_id: selectedScenario.id,
        use_tavily: false,
        max_turns: 15,
        round_limit: 5,
      };

      let caseId = null;
      let totalRounds = payload.round_limit;
      let currentRound = 0;

      for await (const event of streamReactSimulation(payload)) {
        console.log("[SSE Event]", event);

        if (event.type === "error") {
          throw new Error(event.message || "시뮬레이션 오류");
        }

        else if (event.type === "case_created") {
          caseId = event.case_id;
          setCurrentCaseId(caseId);
          addSystem(`케이스 생성: ${caseId}`);
        }
        
        else if (event.type === "round_start") {
          currentRound = event.round;
          addSystem(event.message);
        }
        
        else if (event.type === "simulation_progress") {
          setSimulationState("RUNNING");
          addSystem(event.message || `라운드 ${event.round} 진행 중...`);
        }
        
        else if (event.type === "conversation_logs") {
          // 진행 상황만 업데이트
          setProgress((event.round / totalRounds) * 100);

          // ✅ 누락된 턴만 보정 (서버가 한꺼번에 보내줄 수 있으므로)
          const logs = Array.isArray(event.logs) ? event.logs : [];
          const missing = logs
            .sort((a,b) => (a.turn_index ?? 0) - (b.turn_index ?? 0))
            .filter((log) => {
              const role = (log.role || "offender").toLowerCase();
              const key = `${event.round}:${log.turn_index}:${role}`;
              return !seenTurnsRef.current.has(key);
            });

          for (const log of missing) {
            const role = (log.role || "offender").toLowerCase();
            const raw = log.content || log.text || log.message || "";
            const content = extractDialogueOrPlainText(raw);

            const label =
              role === "offender"
                ? (selectedScenario?.name || "피싱범")
                : (selectedCharacter?.name || "피해자");
            const side = role === "offender" ? "left" : "right";
            const ts = log.created_kst
              ? new Date(log.created_kst).toLocaleTimeString()
              : new Date().toLocaleTimeString();

            addChat(role, content, ts, label, side, {
              run: log.run,
              turn: log.turn_index || log.turn,
            });

            const key = `${event.round}:${log.turn_index}:${role}`;
            seenTurnsRef.current.add(key);
          }

          // 안내 메시지 (선택)
          if (event.status === "no_logs") {
            addSystem(`⚠️ 라운드 ${event.round} 로그를 가져오지 못했습니다.`);
          }
          setSimulationState("RUNNING");
        }
        
        else if (event.type === "round_complete") {
          // conversation_logs에서 이미 처리했으므로 중복 방지
          addSystem(`라운드 ${event.round} 완료 (${event.total_turns}턴)`);
        }

        else if (event.type === "new_message") {
          // 중복 방지
          const role = (event.role || "offender").toLowerCase();
          const key = `${event.round}:${event.turn_index}:${event.role}`;
          if (seenTurnsRef.current.has(key)) {
            continue;
          }
          seenTurnsRef.current.add(key);

          // 내용 정리 (victim의 ```json``` 포함 케이스)
          const raw = event.content || "";
          const content = extractDialogueOrPlainText(raw);

          const label =
            role === "offender"
              ? (selectedScenario?.name || "피싱범")
              : (selectedCharacter?.name || "피해자");

          const side = role === "offender" ? "left" : "right";
          const ts = event.created_kst
            ? new Date(event.created_kst).toLocaleTimeString()
            : new Date().toLocaleTimeString();

          // 바로 대화창에 append
          addChat(role, content, ts, label, side, {
            run: event.round,
            turn: event.turn_index,
          });

          // 스피너 감추기 / 진행중 표시
          setSimulationState("RUNNING");
          setProgress((p) => Math.min(100, p + 1));
        }
        
        else if (event.type === "judgement") {
          addSystem(
            `라운드 ${event.round} 판정: ${event.phishing ? "피싱 성공" : "피싱 실패"} - ${event.reason}`
          );
        }
        
        else if (event.type === "guidance_generated") {
          addSystem(
            `라운드 ${event.round} 지침 생성: ${event.guidance?.categories?.join(", ") || "N/A"}`
          );
        }
        
        else if (event.type === "complete") {
          setProgress(100);
          setSimulationState("IDLE");
          setShowReportPrompt(true);
          addSystem("시뮬레이션 완료!");
          
          // 최종 데이터 조회
          if (caseId) {
            const bundle = await getConversationBundle(caseId);
            setDefaultCaseData(bundle);
            setSessionResult((prev) => ({
              ...(prev || {}),
              phishing: bundle.phishing,
              evidence: bundle.evidence,
              totalTurns: bundle.total_turns,
              preview: bundle.preview,
            }));
          }
        }
      }
    
      if (!caseId) {
        throw new Error("case_id를 받지 못했습니다.");
      }

    } catch (err) {
      console.error("SSE 스트리밍 실패:", err);
      addSystem(`시뮬레이션 실패: ${err.message}`);
      setSimulationState("IDLE");
    }
  };

  /* resetToSelection */
  const resetToSelection = () => {
    setSelectedScenario(null);
    setSelectedCharacter(null);
    setMessages([]);
    setSessionResult(null);
    setProgress(0);
    setSimulationState("IDLE");
    setCurrentPage("simulator");
  };

  const handleBack = () => {
    setCurrentPage("landing");
  };

  // cleanup
  useEffect(() => {
    return () => {
      if (simIntervalRef.current) {
        clearInterval(simIntervalRef.current);
        simIntervalRef.current = null;
      }
    };
  }, []);

  /* --------- pageProps 전달 --------- */
  const pageProps = {
    COLORS,
    onBack: handleBack,
    setCurrentPage,

    selectedScenario,
    setSelectedScenario,
    selectedCharacter,
    setSelectedCharacter,

    simulationState,
    setSimulationState,

    messages,
    addSystem,
    addChat,

    sessionResult,
    resetToSelection,
    startSimulation,

    scenarios,
    characters,
    scrollContainerRef,
    defaultCaseData,
    dataLoading,
    dataError,
    currentCaseId,

    showReportPrompt,
    setShowReportPrompt,
    hasInitialRun,

    progress,
    setProgress,

    victimImageUrl: selectedCharacter
      ? getVictimImage(selectedCharacter.photo_path)
      : null,
  };

  return (
    <div className="font-sans">
      {currentPage === "landing" && (
        <LandingPage setCurrentPage={setCurrentPage} />
      )}
      {currentPage === "simulator" && <SimulatorPage {...pageProps} />}
      {currentPage === "report" && (
        <ReportPage {...pageProps} defaultCaseData={defaultCaseData} />
      )}
    </div>
  );
};

export default App;
