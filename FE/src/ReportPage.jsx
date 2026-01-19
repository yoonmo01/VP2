// src/ReportPage.jsx
import {
  User,
  Bot,
  ExternalLink,
  Shield,
  AlertTriangle,
} from "lucide-react";
import { useMemo } from "react";
import Badge from "./Badge";

const ReportPage = ({
  COLORS,
  setCurrentPage,
  sessionResult,
  scenarios,
  defaultCaseData,
  selectedScenario,
  selectedCharacter,
  victimImageUrl,
  // 🔴 SSE에서 바로 오는 데이터들
  preventions = null,   // 마지막 prevention 이벤트 or 배열
  judgements = null,    // (선택) judgement SSE 이벤트
  streamLogs = [],   // ✅ 추가

  // 🔹 아래 네 개는 있으면 쓰고, 없으면 무시하도록 기본값 no-op
  setSelectedScenario = () => {},
  setSelectedCharacter = () => {},
  setMessages = () => {},
  setProgress = () => {},
}) => {
  const THEME = {
    ...COLORS,
    bg: "#030617",
    panel: "#061329",
    panelDark: "#04101f",
    panelDarker: "#020812",
    border: "#A8862A",
    text: "#FFFFFF",
    sub: "#BFB38A",
    blurple: "#A8862A",
    success: COLORS?.success ?? "#57F287",
    warn: COLORS?.warn ?? "#FF4757",
    white: "#FFFFFF",
    black: "#000000",
    danger: COLORS?.danger ?? "#ED4245",
  };

  // 🔍 SSE 로그에서 Final Answer / 최종 예방 요약 텍스트 추출
  const finalAnswerText = useMemo(() => {
    if (!Array.isArray(streamLogs) || streamLogs.length === 0) return null;

    // 여러 줄 로그를 하나로 합치고 ANSI 코드 제거
    const joined = streamLogs.join("\n");
    const cleaned = joined.replace(/\x1B\[[0-9;]*m/g, "");

    // 1) "Final Answer:" 부터 잘라서 사용
    const faIdx = cleaned.indexOf("Final Answer:");
    if (faIdx >= 0) {
      return cleaned.slice(faIdx).trim();
    }

    // 2) 아니면 "최종 예방 요약:" 부터라도 사용
    const sumIdx = cleaned.indexOf("최종 예방 요약:");
    if (sumIdx >= 0) {
      return cleaned.slice(sumIdx).trim();
    }

    // 3) 그래도 없으면 전체 로그라도 반환 (없으면 null)
    const trimmed = cleaned.trim();
    return trimmed.length > 0 ? trimmed : null;
  }, [streamLogs]);
  // 🎨 Final Answer 파싱: case_id, 총 라운드, 라운드별 판정, 최종 예방 요약
  const parsedFinalAnswer = useMemo(() => {
    if (!finalAnswerText) return null;

    const result = {
      caseId: null,
      totalRounds: 0,
      rounds: [],
      summary: null
    };

    // CASE_ID 추출
    const caseIdMatch = finalAnswerText.match(/CASE_ID:\s*([a-f0-9\-]+)/i);
    if (caseIdMatch) result.caseId = caseIdMatch[1];

    // 총 라운드 수 추출
    const totalRoundsMatch = finalAnswerText.match(/총 라운드 수:\s*(\d+)/);
    if (totalRoundsMatch) result.totalRounds = parseInt(totalRoundsMatch[1]);

    // 라운드별 판정 추출
    const roundRegex = /Round (\d+):\s*phishing=(true|false),\s*risk\.level="([^"]+)",\s*요약=([^\.]+\.)(?=\s*-\s*Round|\s*최종 예방 요약|$)/gs;
    let roundMatch;
    while ((roundMatch = roundRegex.exec(finalAnswerText)) !== null) {
      result.rounds.push({
        round: parseInt(roundMatch[1]),
        phishing: roundMatch[2] === 'true',
        riskLevel: roundMatch[3],
        summary: roundMatch[4].trim().replace(/\s*-\s*$/, '')
      });
    }

    // 최종 예방 요약 추출
    const summaryMatch = finalAnswerText.match(/최종 예방 요약:\s*(.+?)(?=\s*>\s*Finished chain\.|$)/s);
    if (summaryMatch) {
      result.summary = summaryMatch[1]
        .trim()
        .replace(/\s*>\s*Finished chain\.\s*$/g, '')
        .trim();
    }

    return result;
  }, [finalAnswerText]);



  // 🧠 1) judgement SSE 정규화
  const normalizedJudgement = useMemo(() => {
    if (!judgements) return null;

    const ev = judgements?.event ?? judgements;
    const raw = ev?.content ?? ev;
    if (!raw || typeof raw !== "object") return null;

    return {
      case_id: raw.case_id,
      run_no: raw.run_no,
      phishing: raw.phishing,
      risk: raw.risk,                 // { score, level, rationale }
      evidence: raw.evidence,         // string
      victim_vulnerabilities: raw.victim_vulnerabilities, // string[]
      ok: raw.ok,
      persisted: raw.persisted,
    };
  }, [judgements]);


  // 🧠 3) 피싱 근거 계산 (judgement → defaultCaseData → sessionResult)
  const caseEvidence = useMemo(() => {
    return (
      normalizedJudgement?.evidence ??
      defaultCaseData?.case?.evidence ??
      sessionResult?.case?.evidence ??
      sessionResult?.evidence ??
      ""
    );
  }, [normalizedJudgement, defaultCaseData, sessionResult]);

  // 🧠 4) SSE 이벤트 / 배열 형태 모두 지원하는 개인화 예방법 정규화
  const latestPrevention = useMemo(() => {
    if (!preventions) return null;

    // 1) SSE 단일 이벤트 객체 형태
    //    ex) { type: "prevention", event: { content: { ... }, meta: { ... } } }
    if (!Array.isArray(preventions)) {
      const ev = preventions?.event ?? preventions;
      if (!ev) return null;

      if (ev.content) return ev;      // { content: {...}, meta: ... }
      return { content: ev };         // content 없이 바로 들어온 경우
    }

    // 2) 배열인 경우 (마지막 원소 사용)
    if (preventions.length === 0) return null;
    const last = preventions[preventions.length - 1];
    if (!last) return null;

    if (last.content) return last;
    return { content: last };
  }, [preventions]);

  // 🧠 5) 피해자 정보 구성 (selectedCharacter → sessionResult → 기본값)
  const victimFromSession = sessionResult
    ? {
        name: sessionResult.victimName ?? "알 수 없음",
        meta: {
          age: sessionResult.victimAge ?? "-",
          gender: sessionResult.victimGender ?? "-",
          address: sessionResult.victimAddress ?? "-",
          education: sessionResult.victimEducation ?? "-",
          job: sessionResult.victimJob ?? "-",
        },
        traits: { ocean: undefined, list: sessionResult.victimTraits ?? [] },
        knowledge: {
          comparative_notes: Array.isArray(sessionResult?.victimKnowledge)
            ? sessionResult.victimKnowledge
            : Array.isArray(sessionResult?.victimComparativeNotes)
              ? sessionResult.victimComparativeNotes
              : Array.isArray(sessionResult?.knowledge?.comparative_notes)
                ? sessionResult.knowledge.comparative_notes
                : [],
        },
      }
    : null;

  const victim =
    selectedCharacter ??
    victimFromSession ?? {
      name: "알 수 없음",
      meta: { age: "-", gender: "-", address: "-", education: "-", job: "-" },
      traits: { ocean: undefined, list: [] },
      knowledge: { comparative_notes: [] },
    };

  const oceanLabelMap = {
    openness: "개방성",
    neuroticism: "신경성",
    extraversion: "외향성",
    agreeableness: "친화성",
    conscientiousness: "성실성",
  };

  const oceanEntries =
    victim?.traits?.ocean && typeof victim.traits.ocean === "object"
      ? Object.entries(victim.traits.ocean).map(([k, v]) => ({
          label: oceanLabelMap[k] ?? k,
          value: v,
        }))
      : [];

  const traitList = Array.isArray(victim?.traits?.list)
    ? victim.traits.list
    : [];

  const phishingTypeText =
    selectedScenario?.type ??
    (Array.isArray(scenarios)
      ? scenarios[0]?.type ?? "피싱 유형"
      : "피싱 유형");

  // 📌 피싱 시나리오 이름 (offender.name)
  const scenarioName =
    selectedScenario?.name ??
    (Array.isArray(scenarios)
      ? scenarios[0]?.name ?? "피싱 시나리오"
      : "피싱 시나리오");

  // 📌 피싱 시나리오 단계 (offender.profile.steps)
  const scenarioSteps =
    selectedScenario?.profile?.steps ??
    (Array.isArray(scenarios) ? scenarios[0]?.profile?.steps : null) ??
    defaultCaseData?.case?.steps ??
    [];

  // 🔹 InvestigationBoard와 동일한 위험도 매핑
  function getRiskTokens(levelRaw) {
    const lv = String(levelRaw || "").toLowerCase();

    if (lv === "critical") {
      return { label: "치명적", color: "#EF4444", bg: "#EF444420" };
    }
    if (lv === "high") {
      return { label: "높음", color: "#F59E0B", bg: "#F59E0B20" };
    }
    if (lv === "medium") {
      return { label: "보통", color: "#06B6D4", bg: "#06B6D420" };
    }
    if (lv === "low") {
      return { label: "낮음", color: "#10B981", bg: "#10B98120" };
    }

    // 예외 값 처리
    return {
      label: levelRaw ?? "-",
      color: THEME.sub,
      bg: THEME.panelDark,
    };
  }

  // 🔹 위험도 뱃지 (개인화 예방법 상단)
  function RiskBadge({ level }) {
    const { label, color, bg } = getRiskTokens(level);

    return (
      <span
        className="text-xs px-3 py-1 rounded font-semibold"
        style={{ backgroundColor: bg, color }}
      >
        위험도: {label}
      </span>
    );
  }

  const hasAnyData = !!sessionResult || !!latestPrevention;

  return (
    <div
      style={{ backgroundColor: THEME.bg, color: THEME.text }}
      className="min-h-screen"
    >
      <div className="mx-auto min-h-screen p-6 md:p-10 xl:p-12 flex flex-col">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-10">
          <h1 className="text-4xl font-bold">시뮬레이션 리포트</h1>
          <div className="flex gap-3">
            <button
              onClick={() => setCurrentPage("simulator")}
              className="px-6 py-3 rounded-lg text-lg font-medium"
              style={{
                backgroundColor: THEME.panelDark,
                color: THEME.text,
                border: `1px solid ${THEME.border}`,
              }}
            >
              대화 보기
            </button>
            <button
              onClick={() => {
                // 🔹 상위에서 props를 안 넘겨줬어도 에러 안 나게 no-op 기본값 지정해 둠
                setSelectedScenario(null);
                setSelectedCharacter(null);
                setMessages([]);
                setProgress(0);
                setCurrentPage("simulator");
              }}
              className="px-6 py-3 rounded-lg text-lg font-medium"
              style={{ backgroundColor: THEME.blurple, color: THEME.white }}
            >
              새 시뮬레이션
            </button>
          </div>
        </div>

        {hasAnyData ? (
          <div className="flex gap-10 flex-1 overflow-hidden">
            {/* 왼쪽 패널: 유형 / 피해자 / 에이전트 */}
            <div
              className="w-full lg:w-1/3 flex-shrink-0 space-y-8 pr-6"
              style={{ borderRight: `1px solid ${THEME.border}` }}
            >
              {/* 피싱 유형 / 시나리오 */}
              <div
                className="rounded-2xl p-8"
                style={{
                  backgroundColor: THEME.panel,
                  border: `1px solid ${THEME.border}`,
                }}
              >
                <h2
                  className="text-2xl font-semibold mb-5 flex items-center"
                  style={{ color: THEME.text }}
                >
                  <Shield className="mr-3" size={26} />
                  피싱 정보
                </h2>
                {/* 🔹 피싱 유형 (type) */}
                <div className="mb-3">
                  <span
                    className="inline-flex items-center text-xs px-3 py-1 rounded-full font-semibold"
                    style={{
                      backgroundColor: THEME.bg,
                      color: THEME.sub,
                      border: `1px solid ${THEME.border}`,
                    }}
                  >
                    유형:{" "}
                    <span className="ml-1" style={{ color: THEME.white }}>
                      {phishingTypeText}
                    </span>
                  </span>
                </div>

                {/* 🔹 피싱 이름 (name) */}
                <div
                  className="text-xl font-semibold mb-4"
                  style={{ color: THEME.blurple }}
                >
                  {scenarioName}
                </div>

                {/* 🔹 피싱 단계 (profile.steps) */}
                {Array.isArray(scenarioSteps) && scenarioSteps.length > 0 ? (
                  <ol className="space-y-2 text-sm leading-relaxed">
                    {scenarioSteps.map((step, idx) => (
                      <li
                        key={idx}
                        className="flex items-start gap-2"
                        style={{ color: THEME.sub }}
                      >
                        <span
                          className="mt-[2px] text-xs px-2 py-1 rounded-full font-semibold"
                          style={{
                            backgroundColor: THEME.bg,
                            color: THEME.text,
                            border: `1px solid ${THEME.border}`,
                          }}
                        >
                          {idx + 1}
                        </span>
                        <span>{step}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="text-sm" style={{ color: THEME.sub }}>
                    시나리오 단계 정보가 없습니다.
                  </div>
                )}
              </div>

              {/* 피해자 정보 */}
              <div
                className="rounded-2xl p-8"
                style={{
                  backgroundColor: THEME.panel,
                  border: `1px solid ${THEME.border}`,
                }}
              >
                <h2
                  className="text-2xl font-semibold mb-5 flex items-center"
                  style={{ color: THEME.text }}
                >
                  <User className="mr-3" size={26} />
                  피해자 정보
                </h2>

                <div className="space-y-5">
                  <div className="flex justify-center">
                    {victimImageUrl ? (
                      <img
                        src={victimImageUrl}
                        alt={victim.name}
                        className="w-24 h-24 rounded-full object-cover"
                      />
                    ) : (
                      <div
                        className="w-24 h-24 rounded-full flex items-center justify-center"
                        style={{ backgroundColor: THEME.border }}
                      >
                        <User size={48} color={THEME.text} />
                      </div>
                    )}
                  </div>

                  <div className="text-center">
                    <div
                      className="font-semibold text-xl mb-3"
                      style={{ color: THEME.text }}
                    >
                      {victim?.name}
                    </div>
                    <div
                      className="text-base space-y-2"
                      style={{ color: THEME.sub }}
                    >
                      <div>나이: {victim?.meta?.age}</div>
                      <div>성별: {victim?.meta?.gender}</div>
                      <div>거주지: {victim?.meta?.address}</div>
                      <div>학력: {victim?.meta?.education}</div>
                      {victim?.meta?.job && <div>직업: {victim.meta.job}</div>}
                    </div>
                  </div>

                  <div>
                    <h3
                      className="font-semibold text-lg mb-3"
                      style={{ color: THEME.text }}
                    >
                      성격 특성 (OCEAN)
                    </h3>

                    <div className="flex flex-wrap gap-3 mb-3">
                      {oceanEntries.length > 0 ? (
                        oceanEntries.map((e, idx) => (
                          <span
                            key={idx}
                            className="px-3 py-2 rounded-full text-sm font-medium"
                            style={{
                              backgroundColor: THEME.border,
                              color: THEME.black,
                            }}
                          >
                            {e.label}: {e.value}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm" style={{ color: THEME.sub }}>
                          OCEAN 정보 없음
                        </span>
                      )}
                    </div>

                    {traitList?.length > 0 && (
                      <div className="flex flex-wrap gap-3">
                        {traitList.map((t, i) => (
                          <span
                            key={i}
                            className="px-4 py-2 rounded-full text-sm font-medium"
                            style={{
                              backgroundColor: THEME.border,
                              color: THEME.black,
                            }}
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mt-6">
                    <h3
                      className="font-semibold text-lg mb-3"
                      style={{ color: THEME.text }}
                    >
                      지식
                    </h3>
                    <div className="space-y-1">
                      {Array.isArray(victim?.knowledge?.comparative_notes) &&
                      victim.knowledge.comparative_notes.length > 0 ? (
                        victim.knowledge.comparative_notes.map((note, idx) => (
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
                </div>
              </div>


            {/* 오른쪽: 판정 결과 / 예방법 / 출처 */}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto space-y-8 pr-2">
              {/* 피싱 판정 결과 */}
              <div
                className="rounded-2xl p-8"
                style={{
                  backgroundColor: THEME.panel,
                  border: `1px solid ${THEME.border}`,
                }}
              >
                <div className="flex items-center justify-between mb-5">
                  <h2
                    className="text-2xl font-semibold flex items-center"
                    style={{ color: THEME.text }}
                  >
                    <AlertTriangle className="mr-3" size={26} />
                    피싱 판정 결과
                  </h2>
                  {parsedFinalAnswer?.caseId && (
                    <div
                      className="px-3 py-1 rounded text-xs font-mono"
                      style={{
                        backgroundColor: THEME.panelDark,
                        border: `1px solid ${THEME.border}`,
                        color: THEME.sub,
                      }}
                    >
                      ID: {parsedFinalAnswer.caseId}
                    </div>
                  )}
                </div>
                {parsedFinalAnswer ? (
                  <div className="space-y-6">
                    {/* 총 라운드 수 */}
                    {parsedFinalAnswer.totalRounds > 0 && (
                      <div
                        className="p-4 rounded-lg"
                        style={{
                          backgroundColor: THEME.bg,
                          border: `1px solid ${THEME.border}`,
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="font-semibold text-base"
                            style={{ color: THEME.text }}
                          >
                            총 라운드 수:
                          </span>
                          <span
                            className="text-2xl font-bold"
                            style={{ color: THEME.blurple }}
                          >
                            {parsedFinalAnswer.totalRounds}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* 라운드별 판정 */}
                    {parsedFinalAnswer.rounds.length > 0 && (
                      <div>
                        <h4
                          className="font-semibold text-lg mb-3"
                          style={{ color: THEME.text }}
                        >
                          라운드별 판정
                        </h4>
                        <div className="space-y-3">
                          {parsedFinalAnswer.rounds.map((round) => {
                            const {
                              label: riskLabel,
                              color: riskColor,
                              bg: riskBg,
                            } = getRiskTokens(round.riskLevel);

                            return (
                              <div
                                key={round.round}
                                className="p-4 rounded-lg"
                                style={{
                                  backgroundColor: THEME.bg,
                                  border: `1px solid ${THEME.border}`,
                                }}
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <span
                                    className="font-semibold text-base"
                                    style={{ color: THEME.text }}
                                  >
                                    Round {round.round}
                                  </span>
                                  <div className="flex items-center gap-2">
                                    <span
                                      className="px-3 py-1 rounded text-xs font-semibold"
                                      style={{
                                        backgroundColor: round.phishing
                                          ? THEME.danger
                                          : THEME.success,
                                        color: THEME.white,
                                      }}
                                    >
                                      {round.phishing ? "피싱성공" : "피싱실패"}
                                    </span>
                                    <span
                                      className="px-3 py-1 rounded text-xs font-semibold"
                                      style={{
                                        backgroundColor: riskBg,
                                        color: riskColor,
                                      }}
                                    >
                                      {riskLabel}
                                    </span>
                                  </div>
                                </div>
                                <p
                                  className="text-sm leading-relaxed"
                                  style={{ color: THEME.sub }}
                                >
                                  {round.summary}
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* 최종 예방 요약 */}
                    {parsedFinalAnswer.summary && (
                      <div
                        className="p-4 rounded-lg"
                        style={{
                          backgroundColor: THEME.bg,
                          border: `1px solid ${THEME.border}`,
                        }}
                      >
                        <h4
                          className="font-semibold text-base mb-3"
                          style={{ color: THEME.text }}
                        >
                          최종 예방 요약
                        </h4>
                        <p
                          className="text-sm leading-relaxed whitespace-pre-wrap"
                          style={{ color: THEME.sub }}
                        >
                          {parsedFinalAnswer.summary}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    className="mt-2 p-4 rounded"
                    style={{
                      backgroundColor: THEME.bg,
                      border: `1px solid ${THEME.border}`,
                      color: THEME.text,
                    }}
                  >
                    <h4 className="font-semibold mb-2">
                      시뮬레이션 판정 요약
                    </h4>
                    <p
                      className="text-sm leading-relaxed whitespace-pre-wrap"
                      style={{ color: THEME.sub }}
                    >
                      {finalAnswerText || caseEvidence || "근거 정보가 없습니다."}
                    </p>
                  </div>
                )}
              </div>

              {/* 개인화 예방법 */}
              <div
                className="rounded-2xl p-8"
                style={{
                  backgroundColor: THEME.panel,
                  border: `1px solid ${THEME.border}`,
                }}
              >
                <div className="flex items-center justify-between mb-5">
                  <h2
                    className="text-2xl font-semibold flex items-center"
                    style={{ color: THEME.text }}
                  >
                    <Shield className="mr-3" size={26} />
                    개인화 예방법
                  </h2>
                  {latestPrevention?.content?.analysis?.risk_level && (
                    <RiskBadge
                      level={latestPrevention.content.analysis.risk_level}
                    />
                  )}
                </div>

                {!latestPrevention ? (
                  <div className="text-sm" style={{ color: THEME.sub }}>
                    예방법 정보가 없습니다.
                  </div>
                ) : (
                  <>
                    <div
                      className="p-4 rounded mb-6"
                      style={{
                        backgroundColor: THEME.bg,
                        border: `1px solid ${THEME.border}`,
                        color: THEME.text,
                      }}
                    >
                      <h3 className="font-semibold mb-2">요약</h3>
                      <p
                        className="text-sm leading-relaxed whitespace-pre-wrap"
                        style={{ color: THEME.sub }}
                      >
                        {latestPrevention.content?.summary ??
                          "요약 정보가 없습니다."}
                      </p>
                    </div>

                    <div className="mb-6">
                      <h3
                        className="font-semibold mb-3"
                        style={{ color: THEME.text }}
                      >
                        실천 단계
                      </h3>
                      {Array.isArray(latestPrevention.content?.steps) &&
                      latestPrevention.content.steps.length > 0 ? (
                        <ul
                          className="list-disc pl-6 space-y-1 text-sm"
                          style={{ color: THEME.sub }}
                        >
                          {latestPrevention.content.steps.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      ) : (
                        <div className="text-sm" style={{ color: THEME.sub }}>
                          단계 정보 없음
                        </div>
                      )}
                    </div>

                    <div className="mb-6">
                      <h3
                        className="font-semibold mb-3"
                        style={{ color: THEME.text }}
                      >
                        핵심 팁
                      </h3>
                      {Array.isArray(latestPrevention.content?.tips) &&
                      latestPrevention.content.tips.length > 0 ? (
                        <ul
                          className="list-disc pl-6 space-y-1 text-sm"
                          style={{ color: THEME.sub }}
                        >
                          {latestPrevention.content.tips.map((t, i) => (
                            <li key={i}>{t}</li>
                          ))}
                        </ul>
                      ) : (
                        <div className="text-sm" style={{ color: THEME.sub }}>
                          팁 정보 없음
                        </div>
                      )}
                    </div>

                    <div>
                      <h3
                        className="font-semibold mb-3"
                        style={{ color: THEME.text }}
                      >
                        판단 근거
                      </h3>
                      {Array.isArray(
                        latestPrevention.content?.analysis?.reasons
                      ) &&
                      latestPrevention.content.analysis.reasons.length > 0 ? (
                        <ul
                          className="list-disc pl-6 space-y-1 text-sm"
                          style={{ color: THEME.sub }}
                        >
                          {latestPrevention.content.analysis.reasons.map(
                            (r, i) => (
                              <li key={i}>{r}</li>
                            )
                          )}
                        </ul>
                      ) : (
                        <div className="text-sm" style={{ color: THEME.sub }}>
                          판단 근거 없음
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>

              {/* 사례 출처 및 참고자료 */}
              <div
                className="rounded-2xl p-8"
                style={{
                  backgroundColor: THEME.panel,
                  border: `1px solid ${THEME.border}`,
                }}
              >
                <h2
                  className="text-2xl font-semibold mb-5 flex items-center"
                  style={{ color: THEME.text }}
                >
                  <ExternalLink className="mr-3" size={26} />
                  사례 출처 및 참고자료
                </h2>

                <div className="space-y-5">
                  {(() => {
                    const src =
                      selectedScenario?.source ??
                      (Array.isArray(scenarios)
                        ? scenarios[0]?.source
                        : null) ??
                      defaultCaseData?.case?.source ??
                      null;

                    if (!src) {
                      return (
                        <div
                          className="p-5 rounded-lg"
                          style={{
                            backgroundColor: THEME.bg,
                            color: THEME.sub,
                          }}
                        >
                          <h3
                            className="font-semibold text-lg mb-3"
                            style={{ color: THEME.text }}
                          >
                            참고 사례
                          </h3>
                          <p className="text-base mb-4 leading-relaxed">
                            출처 정보가 없습니다.
                          </p>
                        </div>
                      );
                    }

                    const { title, page, url } = src;

                    return (
                      <div
                        className="p-5 rounded-lg"
                        style={{ backgroundColor: THEME.bg, color: THEME.sub }}
                      >
                        <h3
                          className="font-semibold text-lg mb-3"
                          style={{ color: THEME.text }}
                        >
                          {title ?? "참고 사례"}
                        </h3>
                        {page && (
                          <div
                            className="text-base mb-2"
                            style={{ color: THEME.sub }}
                          >
                            페이지: {page}
                          </div>
                        )}
                        <p
                          className="text-base mb-4 leading-relaxed"
                          style={{ color: THEME.sub }}
                        >
                          {sessionResult?.caseSource ??
                            "본 시뮬레이션은 실제 보이스피싱 사례를 바탕으로 제작되었습니다."}
                        </p>
                        <div className="space-y-3">
                          <div className="flex items-center gap-3">
                            <span
                              className="text-base font-medium"
                              style={{ color: THEME.text }}
                            >
                              출처:
                            </span>
                            {url ? (
                              <a
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-base underline"
                                aria-label="참고자료 링크 열기"
                                style={{ color: THEME.blurple }}
                              >
                                {url}
                              </a>
                            ) : (
                              <span
                                className="text-base"
                                style={{ color: THEME.sub }}
                              >
                                {sessionResult?.source ?? "-"}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div
            className="rounded-2xl p-8"
            style={{
              backgroundColor: THEME.panel,
              border: `1px solid ${THEME.border}`,
            }}
          >
            <p className="text-base" style={{ color: THEME.sub }}>
              세션 결과가 없습니다. 시뮬레이션을 먼저 실행해주세요.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
