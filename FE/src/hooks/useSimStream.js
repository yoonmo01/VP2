// useSimStream.js
import { useRef, useState, useCallback } from "react";
import { streamReactSimulation } from "../lib/streamReactSimulation";

export function useSimStream(
  setMessages,
  {
    addSystem,
    addChat,
    setProgress,
    setSimulationState,
    getConversationBundle,
    onSessionResult,
    selectedScenario,
    selectedCharacter,
  } = {}
) {
  const [logs, setLogs] = useState([]);
  const [messages, setLocalMessages] = useState([]);

  /** ⭐ 배열로 누적되는 구조 */
  const [judgements, setJudgements] = useState([]);
  const [guidances, setGuidances] = useState([]);
  const [preventions, setPreventions] = useState([]);

  // 🔊 TTS용 원본 대화 로그 캐시 (메모리)
  const [ttsCache, setTtsCache] = useState({
    caseId: null,      // 문자열
    byRun: {},         // { [runNo: number]: { turns: [] } }
  });

  const [running, setRunning] = useState(false);

  const iterRef = useRef(null);
  const stoppedRef = useRef(false);

  const caseIdRef = useRef(null);
  const totalRoundsRef = useRef(5);
  const seenTurnsRef = useRef(new Set());

  const lastRoundRef = useRef(null);

  // 🔊 TTS용: conversation_log 순서 기반 run 번호 / case_id
  const [ttsRuns, setTtsRuns] = useState([]);
  const [ttsCaseId, setTtsCaseId] = useState(null);
  
  const stripAnsi = (s = "") => String(s).replace(/\x1B\[[0-9;]*m/g, "");
  const containsFinishedChain = (text = "") => /\bFinished chain\b/i.test(stripAnsi(text));

  function parseConversationLogContent(content) {
    if (!content || typeof content !== "string") return null;
    const idx = content.indexOf("{");
    if (idx < 0) return null;
    try {
      const obj = JSON.parse(content.slice(idx));
      const caseId = obj.case_id || obj.meta?.case_id || obj.log?.case_id || null;
      const roundNo =
        obj.meta?.round_no || obj.meta?.run_no || obj.stats?.round || obj.stats?.run || 1;
      const turns = Array.isArray(obj.turns) ? obj.turns : [];
      return { caseId, roundNo: Number(roundNo) || 1, turns };
    } catch (_) {
      return null;
    }
  }

  const hardClose = useCallback(() => {
    try {
      const it = iterRef.current;
      if (it && typeof it.return === "function") it.return();
    } catch {}
    finally {
      iterRef.current = null;
    }
  }, []);

  // ─────────────────────────────────────────────────────────────
  // START
  // ─────────────────────────────────────────────────────────────
  const start = useCallback(
    async (payload) => {
      if (running) return;
      setRunning(true);
      stoppedRef.current = false;

      // 초기화
      setLogs([]);
      setLocalMessages([]);

      /** ⭐ 누적 배열 초기화 */
      setJudgements([]);
      setGuidances([]);
      setPreventions([]);

      // 🔊 TTS 캐시도 초기화
      setTtsCache({ caseId: null, byRun: {} });

      // 🔊 TTS용 초기화
      setTtsRuns([]);
      setTtsCaseId(null);

      caseIdRef.current = null;
      seenTurnsRef.current = new Set();
      totalRoundsRef.current = payload?.round_limit ?? 5;

      hardClose();
      setSimulationState?.("PREPARE");
      setProgress?.(0);

      if (selectedScenario && selectedCharacter) {
        addSystem?.(`시뮬레이션 시작: ${selectedScenario.name} / ${selectedCharacter.name}`);
      }

      const it = streamReactSimulation(payload);
      iterRef.current = it;

      try {
        for await (const event of it) {
          if (stoppedRef.current) break;

          const evt = event?.content ?? event;
          const type = event?.type;
          const contentStr =
            typeof event?.content === "string"
              ? event.content
              : (event?.content?.message ?? "");

          console.log("📨 [SSE Event]", { type, event });

          // 종료 조건
          if (type === "run_end" || type === "run_end_local" || type === "error") {
            setSimulationState?.("FINISH");
            break;
          }
          if (type === "terminal" && containsFinishedChain(contentStr || "")) {
            setLogs((p) => [...p, contentStr]);
            setSimulationState?.("FINISH");
            break;
          }

          // ──────────────────────────────
          // 1) conversation_log
          // ──────────────────────────────
          if (type === "conversation_log") {
            console.log("🎯 conversation_log 감지!", evt);
            const logData = typeof evt === "object" ? evt : event?.content;
            const turns = logData?.turns || logData?.log?.turns || [];

            // ⭐ 현재 라운드 번호 감지 (없으면 1로)
            const roundNoRaw =
              logData?.round_no ||
              logData?.run_no ||
              logData?.meta?.round_no ||
              logData?.meta?.run_no ||
              logData?.stats?.round ||
              logData?.stats?.run ||
              1;
            const roundNo = Number(roundNoRaw) || 1;

            // 🔊 TTS용 case_id 감지
            const caseId =
              logData?.case_id ||
              logData?.caseId ||
              logData?.meta?.case_id ||
              logData?.log?.case_id ||
              caseIdRef.current ||
              null;

            if (caseId && !caseIdRef.current) {
              caseIdRef.current = caseId;
            }
            if (caseId) {
              // 한 번만 세팅 (이미 있으면 유지)
              setTtsCaseId((prev) => prev ?? caseId);
            }

            // 🔊 TTS용 run 번호 목록 갱신
            setTtsRuns((prev) => {
              if (prev.includes(roundNo)) return prev;
              return [...prev, roundNo].sort((a, b) => a - b);
            });

            // 🔊 TTS용 원본 turns 캐시에 run별로 누적
            if (caseId && Array.isArray(turns) && turns.length > 0) {
              setTtsCache((prev) => {
                const byRun = { ...(prev.byRun || {}) };
                const prevTurns = byRun[roundNo]?.turns || [];
                byRun[roundNo] = {
                  turns: [...prevTurns, ...turns],
                };
                return {
                  caseId: prev.caseId || caseId,
                  byRun,
                };
              });
            }

            // ⭐ 라운드가 바뀌었으면 라운드 박스 메시지 시스템으로 삽입
            if (roundNo !== null && lastRoundRef.current !== roundNo) {
              lastRoundRef.current = roundNo;

              const dividerMsg = {
                type: "system",
                sender: "system",
                role: "system",
                isRoundDivider: true,
                round: roundNo,
                text: "",
                content: "",
                side: "center",
                timestamp: new Date().toISOString(),
              };

              setLocalMessages(prev => [...prev, dividerMsg]);
              setMessages?.(prev => [...prev, dividerMsg]);
            }

            if (Array.isArray(turns) && turns.length > 0) {
              setSimulationState?.("RUNNING");

              turns.forEach((turn, idx) => {
                const role = (turn.role || "offender").toLowerCase();
                const key = `conv:${Date.now()}:${idx}:${role}`;

                if (seenTurnsRef.current.has(key)) return;
                seenTurnsRef.current.add(key);

                const raw = turn.text || "";
                let text = "";

                if (role === "victim") {
                  try {
                    const cleaned = raw.replace(/```(?:json)?/gi, "").trim();
                    const match = cleaned.match(/\{[\s\S]*\}/);

                    if (match) {
                      const parsed = JSON.parse(match[0]);
                      text = JSON.stringify(parsed);
                    } else {
                      text = raw;
                    }
                  } catch {
                    text = raw;
                  }
                } else {
                  text = raw;
                }

                const side = role === "offender" ? "left" : "right";
                const label =
                  role === "offender"
                    ? (selectedScenario?.name || "피싱범")
                    : (selectedCharacter?.name || "피해자");

                const newMsg = {
                  type: "chat",
                  role,
                  sender: role,
                  side,
                  text: text,
                  content: text,
                  timestamp: new Date().toISOString(),
                  turn: idx,
                };

                setLocalMessages((prev) => [...prev, newMsg]);
                setMessages?.((prev) => [...prev, newMsg]);
              });

              setProgress?.((p) => Math.min(100, (typeof p === "number" ? p : 0) + 10));
            }
            continue;
          }

          // ──────────────────────────────
          // 2) 로그 계열 (Guidance 포함)
          // ──────────────────────────────
          if (type === "log" || type === "terminal" || type === "agent_action") {
            const content = event.content ?? "";
            setLogs((p) => [...p, content]);

            // ★★★ prevention log 파싱 (로그로 들어오는 경우)
            if (typeof content === "string" && content.startsWith("[prevention]")) {
              try {
                const jsonStr = content.replace("[prevention]", "").trim();
                const parsed = JSON.parse(jsonStr);

                if (parsed.ok && parsed.personalized_prevention) {
                  console.log("🛡️ Prevention 감지 (log):", parsed.personalized_prevention);
                  
                  setPreventions((prev) => [
                    ...prev,
                    {
                      type: "prevention",
                      case_id: parsed.case_id,
                      content: parsed.personalized_prevention,
                      timestamp: new Date().toISOString(),
                      raw: parsed,
                    },
                  ]);
                }
              } catch (e) {
                console.warn("⚠ Prevention 파싱 실패:", e);
              }
            }

            // guidance log 감지
            if (typeof content === "string" && content.startsWith("[GuidanceGeneration]")) {
              try {
                const jsonStr = content.replace("[GuidanceGeneration]", "").trim();
                const parsed = JSON.parse(jsonStr);
                const g = parsed?.generated_guidance;

                if (g) {
                  setGuidances((prev) => [
                    ...prev,
                    {
                      type: "GuidanceGeneration",
                      content: g.text,
                      categories: g.categories,
                      reasoning: g.reasoning,
                      expected_effect: g.expected_effect,
                      meta: {
                        case_id: parsed.case_id,
                        round_no: parsed.round_no,
                        timestamp: parsed.timestamp,
                      },
                      raw: parsed,
                    },
                  ]);
                }
              } catch (e) {
                console.warn("⚠ GuidanceGeneration 파싱 실패:", e);
              }
            }
            continue;
          }

          // ──────────────────────────────
          // 3) case 생성
          // ──────────────────────────────
          if (type === "case_created") {
            caseIdRef.current = evt.case_id;
            addSystem?.(`케이스 생성: ${evt.case_id}`);
            continue;
          }

          // ──────────────────────────────
          // 4) judgement (라운드 판정)
          // ──────────────────────────────
          if (type === "judgement") {
            setJudgements((prev) => [...prev, event]);
            addSystem?.(
              `라운드 ${evt.round ?? "?"} 판정: ${
                evt.phishing ? "피싱 성공" : "피싱 실패"
              }`
            );
            continue;
          }

          // ──────────────────────────────
          // 5) guidance 직접 이벤트
          // ──────────────────────────────
          if (type === "guidance_generated") {
            setGuidances((prev) => [...prev, event]);
            continue;
          }

          // ──────────────────────────────
          // 6) ★★★ prevention 직접 이벤트
          // ──────────────────────────────
          if (type === "prevention" || type === "prevention_tip") {
            console.log("🛡️ Prevention 감지 (event):", evt);
            
            // evt 구조: { ok, case_id, personalized_prevention }
            const preventionData = evt.personalized_prevention || evt.content || evt;
            
            setPreventions((prev) => [
              ...prev,
              {
                type: "prevention",
                case_id: evt.case_id,
                content: preventionData,
                timestamp: new Date().toISOString(),
                raw: evt,
              },
            ]);
            
            addSystem?.("예방책 생성 완료");
            continue;
          }

          // ──────────────────────────────
          // 7) complete
          // ──────────────────────────────
          if (type === "complete") {
            setProgress?.(100);
            setSimulationState?.("IDLE");
            addSystem?.("시뮬레이션 완료!");
            continue;
          }
        }
      } catch (e) {
        console.error("SSE 실패:", e);
        addSystem?.(`실패: ${e.message}`);
      } finally {
        setRunning(false);
        hardClose();
      }
    },
    [
      running,
      setMessages,
      hardClose,
      addSystem,
      setProgress,
      setSimulationState,
      getConversationBundle,
      onSessionResult,
      selectedScenario,
      selectedCharacter,
    ]
  );

  const stop = useCallback(() => {
    stoppedRef.current = true;
    setRunning(false);
    hardClose();
  }, [hardClose]);

  return {
    logs,
    messages,
    start,
    stop,
    running,

    /** ⭐ 누적된 배열 반환 */
    judgements,
    guidances,
    preventions,
    // 🔊 TTS용 정보
    ttsRuns,
    ttsCaseId,
    ttsCache,
  };
}