function getRiskColors(pct) {
  const v = Math.max(0, Math.min(100, Number(pct) || 0));
  if (v >= 70) {
    // High risk - Red (70% 이상)
    return {
      border: "rgba(239,68,68,0.75)",  // red-500
      bg:     "rgba(239,68,68,0.10)",
      text:   "#EF4444",
      tagBg:  "rgba(239,68,68,0.12)",
    };
  } else if (v >= 41) {
    // Medium - Amber/Orange (41~69%)
    return {
      border: "rgba(245,158,11,0.75)", // amber-500
      bg:     "rgba(245,158,11,0.10)",
      text:   "#F59E0B",
      tagBg:  "rgba(245,158,11,0.12)",
    };
  }
  // Low - Emerald/Green (0~40%)
  return {
    border: "rgba(16,185,129,0.75)",   // emerald-500
    bg:     "rgba(16,185,129,0.10)",
    text:   "#10B981",
    tagBg:  "rgba(16,185,129,0.12)",
  };
}

const MessageBubble = ({ message, selectedCharacter, victimImageUrl, COLORS }) => {
  const isVictim   = message.sender === "victim";
  const isScammer  = message.sender === "offender";
  const isSystem   = message.type === "system";
  const isAnalysis = message.type === "analysis";
  const isSpinner  = isSystem && String(message.content || "").includes("🔄");

  // 합쳐진 카드 여부 및 텍스트 분리
  const isCombined  = message.variant === "combined" || !!message.thoughtText;
  const thoughtText = message.thoughtText || (message.variant === "thought" ? message.content : null);
  const speechText  =
    message.speechText ??
    (message.variant === "speech" ? message.content : (!isCombined ? message.content : ""));

  // 설득도(%)
  const convincedPct =
    typeof message?.convincedPct === "number"
      ? Math.max(0, Math.min(100, message.convincedPct))
      : null;

  // ===== 버블 배경/글자색 규칙 =====
  const bubbleBg = isSystem
    ? "rgba(88,101,242,.12)"
    : isAnalysis
    ? "rgba(254,231,92,.12)"
    : (isVictim ? COLORS.white : "#313338");

  const bubbleTextColor = isSystem
    ? COLORS.text
    : isAnalysis
    ? COLORS.warn
    : (isVictim ? COLORS.black : "#FFFFFF");

  const bubbleBorder = isSystem
    ? "rgba(88,101,242,.35)"
    : isAnalysis
    ? "rgba(254,231,92,.35)"
    : COLORS.border;

  // 속마음(내부 박스) 색상(설득도 기반)
  const risk = getRiskColors(convincedPct ?? 0);
  const innerBoxStyle = {
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: risk.border,
    backgroundColor: risk.bg,
    borderRadius: "12px",
    padding: "12px",
  };
  const innerTextStyle = { color: risk.text };

  return (
    <div className={`flex ${isVictim ? "justify-end" : "justify-start"}`}>
      <div
        className={[
          "max-w-md lg:max-w-lg px-5 py-3 rounded-2xl border",
          isSystem ? "mx-auto text-center" : "",
          isSpinner ? "w-80 h-32 flex flex-col items-center justify-center" : "",
        ].join(" ")}
        style={{
          backgroundColor: bubbleBg,
          color: bubbleTextColor,
          border: `1px solid ${bubbleBorder}`,
        }}
      >
        {/* 스피너 애니메이션 */}
        {isSpinner && (
          <div className="flex space-x-1 mb-4">
            {[0, 0.1, 0.2, 0.3, 0.4].map((d, i) => (
              <div
                key={i}
                className="w-1 h-8 bg-[#5865F2] animate-pulse"
                style={{ animationDelay: `${d}s` }}
              />
            ))}
          </div>
        )}

        {/* 공격자 헤더 */}
        {isScammer && (
          <div className="flex items-center mb-2" style={{ color: COLORS.warn }}>
            <span className="mr-2">
              <img
                src={new URL("./assets/offender_profile.png", import.meta.url).href}
                alt="피싱범"
                className="w-8 h-8 rounded-full object-cover"
              />
            </span>
            <span className="text-sm font-medium" style={{ color: COLORS.sub }}>
              피싱범
            </span>
          </div>
        )}

        {/* 피해자 헤더(프로필 + 설득도 바) */}
        {isVictim && selectedCharacter && (
          <div className="flex items-center mb-2">
            <span className="mr-2 text-lg">
              {victimImageUrl ? (
                <img
                  src={victimImageUrl}
                  alt={selectedCharacter.name}
                  className="w-8 h-8 rounded-full object-cover"
                />
              ) : (
                `👤${selectedCharacter.avatar || ""}`
              )}
            </span>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: isVictim ? "#687078" : COLORS.sub }}>
                {selectedCharacter.name}
              </span>
              {typeof convincedPct === "number" && (
                <div className="flex items-center gap-1 min-w-[140px] max-w-[220px]">
                  <div className="flex-1 h-2 bg-[#e5e7eb] rounded overflow-hidden">
                    <div
                      className="h-full transition-all"
                      style={{
                        width: `${convincedPct}%`,
                        backgroundColor:
                          convincedPct >= 70 ? "#EF4444" : convincedPct >= 41 ? "#F59E0B" : "#10B981",
                      }}
                      title={`설득도 ${convincedPct}%`}
                    />
                  </div>
                  <span className="text-[10px] w-8 text-right" style={{ color: "#9ca3af" }}>
                    {convincedPct}%
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ===== 본문 ===== */}
        {!isCombined ? (
          thoughtText ? (
            <div style={innerBoxStyle} className="mb-1.5">
              <p className="whitespace-pre-line text-base leading-relaxed" style={innerTextStyle}>
                {thoughtText}
              </p>
              <div
                className="inline-block mt-1 px-1.5 py-0.5 text-[11px] rounded"
                style={{ color: innerTextStyle.color, backgroundColor: risk.tagBg }}
              >
                속마음
              </div>
            </div>
          ) : (
            <p className="whitespace-pre-line text-base leading-relaxed">
              {isSpinner ? String(speechText || "").replace("🔄 ", "") : speechText}
            </p>
          )
        ) : (
          <>
            {thoughtText && (
              <div style={innerBoxStyle} className="mb-3">
                <p className="whitespace-pre-line text-base leading-relaxed" style={innerTextStyle}>
                  {thoughtText}
                </p>
                <div
                  className="inline-block mt-1 px-1.5 py-0.5 text-[11px] rounded"
                  style={{ color: innerTextStyle.color, backgroundColor: risk.tagBg }}
                >
                  속마음
                </div>
              </div>
            )}
            {speechText && (
              <p className="whitespace-pre-line text-base leading-relaxed">
                {speechText}
              </p>
            )}
          </>
        )}

        {/* 타임스탬프 */}
        <div className="text-xs mt-2 opacity-70" style={{ color: COLORS.sub }}>
          {message.timestamp}
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;
