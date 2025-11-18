// src/components/InvestigationBoard.jsx
import React from "react";
import { Shield, Target, Lightbulb, TrendingUp, ShieldX } from "lucide-react";

/*== 색상 토큰 ==*/
const DEFAULT_THEME = {
  bg: "#030617",
  panel: "#061329",
  panelDark: "#04101f",
  border: "#A8862A",
  text: "#FFFFFF",
  sub: "#BFB38A",
  blurple: "#A8862A",
  success: "#10B981",
  warn: "#F59E0B",
  danger: "#EF4444",
  purple: "#A855F7",
  cyan: "#06B6D4",
};

/* ============================================================
   1) 🔵 핵심: 모든 judgement/guidance/prevention 구조를 통일
===============================================================*/
function normalizeRound(obj) {
  if (!obj) return null;

  const content = obj.content ?? obj.event?.content ?? {};
  const meta = obj.meta ?? obj.raw ?? {};

  const round_no =
    content.run_no ??
    meta.round_no ??
    obj.run_no ??
    obj.round ??
    obj.meta?.round_no ??
    null;

  return {
    ...obj,
    ...meta,
    ...content,
    round_no,
  };
}

/*== 위험도 스타일 ==*/
const getRiskStyle = (level) => {
  const lv = String(level || "").toLowerCase();
  if (lv === "critical") return { color: "#EF4444", label: "치명적", bg: "#EF444420" };
  if (lv === "high") return { color: "#F59E0B", label: "높음", bg: "#F59E0B20" };
  if (lv === "medium") return { color: "#06B6D4", label: "보통", bg: "#06B6D420" };
  if (lv === "low") return { color: "#10B981", label: "낮음", bg: "#10B98120" };
  return { color: "#6B7280", label: "알 수 없음", bg: "#6B728020" };
};

/*== 섹션 카드 ==*/
function Section({ icon: Icon, title, color, children, badge }) {
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={18} color={color} />
          <h3 className="text-sm font-semibold" style={{ color: "#FFFFFF" }}>
            {title}
          </h3>
        </div>
        {badge}
      </div>
      {children}
    </div>
  );
}

/*== RoundBlock ==*/
function RoundBlock({ conv, theme }) {
  if (!conv) return null;

  const {
    run_no,
    phishing,
    evidence,
    risk,
    victim_vulnerabilities: directVulns,
  } = conv;

  // ✅ 라운드마다 judgement 안에 있는 다양한 위치에서 취약점 추출
  const victim_vulnerabilities =
    (Array.isArray(directVulns) && directVulns.length > 0
      ? directVulns
      : Array.isArray(conv?.analysis_context?.vulnerabilities)
      ? conv.analysis_context.vulnerabilities
      : Array.isArray(conv?.raw?.analysis_context?.vulnerabilities)
      ? conv.raw.analysis_context.vulnerabilities
      : []);

  const riskStyle = getRiskStyle(risk?.level);
  const riskScore = risk?.score ?? 0;

  return (
    <div
      className="rounded-xl p-6 mb-6"
      style={{ backgroundColor: theme.panel, border: `1px solid ${theme.border}` }}
    >
      {/* 헤더 */}
      <div
        className="flex items-center justify-between mb-6 pb-4"
        style={{ borderBottom: `1px solid ${theme.border}40` }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold"
            style={{ backgroundColor: theme.blurple, color: "#000" }}
          >
            {run_no}
          </div>
          <span className="font-semibold" style={{ color: theme.text }}>
            라운드 {run_no}
          </span>
        </div>

        <div
          className="px-4 py-1.5 rounded-full text-xs font-bold"
          style={{
            backgroundColor: phishing ? "#EF444420" : "#10B98120",
            color: phishing ? "#EF4444" : "#10B981",
            border: `1px solid ${phishing ? "#EF4444" : "#10B981"}`,
          }}
        >
          {phishing ? "피싱 성공" : "피싱 실패"}
        </div>
      </div>

      {/* 피싱 판정 */}
      <Section icon={Shield} title="피싱 판정 결과" color={theme.blurple}>
        <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
          {evidence || "근거 없음"}
        </p>
      </Section>

      {/* 위험도 */}
      {risk && (
        <Section
          icon={TrendingUp}
          title="위험도"
          color={riskStyle.color}
          badge={
            <div className="flex items-center gap-2">
              <span
                className="px-3 py-1 rounded-full text-xs font-bold"
                style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
              >
                {riskStyle.label}
              </span>
              <span
                className="px-3 py-1 rounded-full text-xs font-mono font-bold"
                style={{ backgroundColor: riskStyle.bg, color: riskStyle.color }}
              >
                {riskScore}점
              </span>
            </div>
          }
        >
          <div className="space-y-3">
            <div
              className="w-full h-2 rounded-full overflow-hidden"
              style={{ backgroundColor: theme.panelDark }}
            >
              <div
                className="h-2 transition-all duration-1000"
                style={{ width: `${riskScore}%`, backgroundColor: riskStyle.color }}
              />
            </div>
            <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
              {risk?.rationale}
            </p>
          </div>
        </Section>
      )}
     {/* 피해자 취약점 */}
     {Array.isArray(victim_vulnerabilities) &&
       victim_vulnerabilities.length > 0 && (
         <Section
           icon={ShieldX}
           title="피해자 취약점"
           color={theme.warn}
         >
           <ul className="space-y-2 text-sm" style={{ color: theme.sub }}>
             {victim_vulnerabilities.map((v, idx) => (
               <li key={idx} className="flex gap-2">
                 <span className="mt-[2px]">•</span>
                 <span>{v}</span>
               </li>
             ))}
           </ul>
         </Section>
       )}
    </div>
  );
}

/*== GuidanceBlock ==*/
function GuidanceBlock({ guidance, theme }) {
  if (!guidance) return null;

  const text = guidance.text ?? guidance.content;
  const categories = guidance.categories ?? [];
  const reasoning = guidance.reasoning;
  const expected_effect = guidance.expected_effect;

  const TOOLTIP_MAP = {
     A: "어휘/어조 조절 - 피해자 수준에 맞는 언어 사용",
    B: "긴급성 강조 - 시간 압박을 통한 판단력 흐림",
    C: "감정적 접근 - 두려움, 책임감, 걱정 자극",
    D: "전문성 연출 - 용어, 절차, 공식성 강조",
    E: "점진적 요구 - 단계별 정보 수집 전략",
    F: "의심 무마 - 보안 우려 해소, 정당성 강조",
    G: "사칭 다변화 - 인물/기관 변경으로 신뢰성 증대",
    H: "수법 복합화 - 여러 피싱 기법 조합 활용",
    I: "심리적 압박 - 위협, 강제성 조성",
    J: "격리 및 통제 - 외부 접촉 차단, 고립 유도",

    K: "카드배송-검사사칭 연계형 - 가짜 기사 → 고객센터 사칭 → 원격제어 앱 → 검사청 확대",
    L: "납치빙자형 극단적 공포 - 가족 음성 모방 + 협박으로 즉시 송금 유도",
    M: "홈캠 해킹 협박형 - 영상·개인정보 노출 위협",
    N: "공신력 기관 사칭 - 공적 명분 + 선입금 요구",
    O: "가족사칭 정보수집 - 비밀번호 등 민감정보 수집",
    P: "허위계약서 작성유도 - 검사 사칭 후 개인정보·계좌 동시 탈취",
    Q: "국세청 사칭 세무협박 - 세금 불이행 위협",
    R: "격리형 장기통제 - 고립 → 새폰 개통 → 원격제어",
    S: "권위 편향 활용 - 정부/금융기관 권위로 설득",
    T: "손실 회피 심리 - 금리 인하·혜택 강조",
    U: "희소성 효과 - ‘오늘만 가능’ 등 시간 압박",
    V: "휴리스틱 의존 악용 - 익숙한 절차로 속임",
    W: "2차 피해 암시 - 협조 거부 시 추가 문제 암시",
  };

  return (
    <div
      className="rounded-xl p-6 mb-10"
      style={{ backgroundColor: theme.panelDark, border: `1px solid ${theme.border}` }}
    >
      <Section icon={Lightbulb} title="공격 지침 (Guidance)" color={theme.purple}>
        <div className="space-y-3">
          {categories.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {categories.map((cat, i) => (
                <span
                  key={i}
                  className="relative group px-2 py-1 rounded text-xs font-mono font-bold cursor-help"
                  style={{
                    backgroundColor: "#A855F720",
                    color: theme.purple,
                    border: `1px solid #A855F740`,
                  }}
                >
                  {cat}

                  {/* Tooltip */}
                  <div
                    className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 rounded-lg text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition bg-black bg-opacity-80 text-white z-50"
                  >
                    {TOOLTIP_MAP[cat] || "설명 없음"}
                  </div>
                </span>
              ))}
            </div>
          )}

          <p className="text-sm leading-relaxed" style={{ color: theme.sub }}>
            {text}
          </p>

          {reasoning && (
            <div
              className="p-3 rounded-lg"
              style={{
                backgroundColor: theme.panel,
                borderLeft: `2px solid ${theme.cyan}`,
              }}
            >
              <div className="text-xs mb-1" style={{ color: theme.cyan }}>
                추론 과정
              </div>
              <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
                {reasoning}
              </p>
            </div>
          )}

          {expected_effect && (
            <div
              className="p-3 rounded-lg"
              style={{
                backgroundColor: theme.panel,
                borderLeft: `2px solid ${theme.success}`,
              }}
            >
              <div className="text-xs mb-1" style={{ color: theme.success }}>
                예상 효과
              </div>
              <p className="text-xs leading-relaxed" style={{ color: theme.sub }}>
                {expected_effect}
              </p>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

/* ============================================================
   ⭐ 메인 InvestigationBoard
===============================================================*/
export default function InvestigationBoard({
  COLORS,
  judgements = [],
  guidances = [],
  preventions = [],
}) {
  const theme = { ...DEFAULT_THEME, ...(COLORS || {}) };

  // 🔵 모든 raw 데이터를 normalize(라운드 번호 통일)
  const J = judgements.map(normalizeRound);
  // ✅ case_id가 없거나 "unknown"인 guidance는 화면에서 숨김
  const G = guidances
    .map(normalizeRound)
    .filter((g) => {
      if (!g) return false;
      const cid = g.case_id;   // normalizeRound에서 meta.case_id가 여기로 올라옴
      return !!cid && cid !== "unknown";
    });
  const P = preventions.map(normalizeRound);

  const rounds = [];

  J.forEach((j) => {
    if (!j.round_no) return;

    rounds.push({
      round_no: j.round_no,
      judgement: j,
      guidance: G.find((g) => g.round_no === j.round_no),
      prevention: P.find((p) => p.round_no === j.round_no),
    });
  });

  rounds.sort((a, b) => a.round_no - b.round_no);

  return (
    <div className="h-full overflow-y-auto p-6" style={{ backgroundColor: theme.bg }}>
      {rounds.map((r, idx) => (
        <div key={`round-${idx}`}>
          <RoundBlock conv={r.judgement} theme={theme} />
          {r.guidance && (
            <GuidanceBlock guidance={r.guidance} theme={theme} />
          )}
        </div>
      ))}
    </div>
  );
}
