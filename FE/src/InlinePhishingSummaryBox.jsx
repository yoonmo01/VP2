// src/InlinePhishingSummaryBox.jsx

function mapOutcomeToKorean(outcome) {
  switch (outcome) {
    case "attacker_fail":
      return "공격자 실패";
    case "attacker_success":
      return "공격자 성공";
    case "inconclusive":
      return "판단 불가";
    default:
      return outcome || "-";
  }
}

function toArrayReasons(reason, reasons) {
  if (Array.isArray(reasons) && reasons.length) return reasons;
  if (Array.isArray(reason)) return reason;
  if (typeof reason === "string" && reason.trim()) return [reason];
  return [];
}

function InlinePhishingSummaryBox({ preview }) {
  if (!preview) return null;
  
  const outcome = mapOutcomeToKorean(preview.outcome);
  const reasons = toArrayReasons(preview.reason, preview.reasons);
  const guidanceTitle = preview?.guidance?.title || "-";

  return (
    <div className="max-w-3xl mx-auto my-4">
      <div className="rounded-2xl border border-gray-200 bg-white/60 shadow-sm backdrop-blur p-4 md:p-5">
        <h3 className="text-base md:text-lg font-semibold mb-3">
          요약(대화 1차 분석)
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-gray-500 mb-1">피싱여부</div>
            <div className="text-sm md:text-base text-gray-900">{outcome}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">적용 지침</div>
            <div className="text-sm md:text-base text-gray-900 line-clamp-2">
              {guidanceTitle}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">피싱여부 근거</div>
            {reasons.length === 0 ? (
              <div className="text-sm text-gray-500">-</div>
            ) : (
              <ul className="list-disc pl-5 space-y-1">
                {reasons.map((r, i) => (
                  <li key={i} className="text-sm leading-6">
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default InlinePhishingSummaryBox;