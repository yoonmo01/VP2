// src/components/CustomScenarioModal.jsx
import { useState, useMemo } from "react";
import { X } from "lucide-react";

export default function CustomScenarioModal({
  open,
  onClose,
  onSave,
  COLORS,
  selectedTag, // 부모에서 현재 칩 선택값 전달(있으면 기본 값)
}) {
  if (!open) return null;

  // --- 폼 상태 ---
  const TYPE_OPTIONS = ["기관 사칭형", "가족·지인 사칭", "대출사기형"];
  const [type, setType] = useState(
    TYPE_OPTIONS.includes(selectedTag) ? selectedTag : "대출사기형"
  );
  const [purpose, setPurpose] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const canSubmit = purpose.trim().length > 0 && TYPE_OPTIONS.includes(type);


  // --- API POST ---
  async function createScenario() {
    if (!canSubmit || submitting) return;
    setSubmitting(true);

    const payload = {
      name: `${type} (커스텀)`, // 필요 시 규칙 바꿔도 됨
      type,                     // 버튼에서 고른 값 그대로 텍스트 전송
      profile: {
        purpose: purpose.trim(),
        steps: [],           // ← 백엔드가 LLM으로 4~7개 생성
      },
    };

    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 15000);

      const res = await fetch("/api/make/offenders/auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });

      clearTimeout(timer);

      // 백엔드가 생성된 row를 돌려준다고 가정
      let data = null;
      try {
        const txt = await res.text();
        data = txt ? JSON.parse(txt) : null;
      } catch {
        data = null;
      }

      if (!res.ok) {
        // 실패 시에도 프론트 카드 추가는 막고 에러만 띄움
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }

      // 응답을 프론트 카드에 맞게 정규화(백엔드 스키마에 맞춰 필요한 필드 사용)
      const normalized = {
        id: data?.id ?? `custom-${Date.now()}`, // 응답에 id 없으면 임시 id
        name: data?.name ?? payload.name,
        type: data?.type ?? payload.type,
        profile: data?.profile ?? payload.profile,
        source: data?.source ?? payload.source,
      };

      // 부모에 전달 → 목록 맨 뒤에 추가
      onSave(normalized);
    } catch (e) {
      alert(`시나리오 생성 실패: ${e.message || e}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
    >
      <div
        className="w-full max-w-xl rounded-xl p-6 relative"
        style={{ backgroundColor: COLORS.panelDark, border: `1px solid ${COLORS.border}`, color: COLORS.text }}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-semibold">커스텀 시나리오 만들기</h3>
          <button
            aria-label="닫기"
            onClick={onClose}
            className="p-1 rounded hover:opacity-80"
            style={{ color: COLORS.sub }}
            disabled={submitting}
          >
            <X size={20} />
          </button>
        </div>

        {/* 폼 */}
        <div className="space-y-5">
          {/* 유형 선택 */}
          <div>
            <div className="mb-2 text-sm" style={{ color: COLORS.sub }}>유형 선택</div>
            <div className="flex flex-wrap gap-2">
              {TYPE_OPTIONS.map((opt) => {
                const active = type === opt;
                return (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setType(opt)}
                    className="px-3 py-2 rounded-3xl text-sm"
                    style={{
                      border: `1px solid ${COLORS.border}`,
                      backgroundColor: active ? COLORS.blurple : COLORS.panel,
                      color: active ? COLORS.black : COLORS.text,
                    }}
                    disabled={submitting}
                  >
                    {opt}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 목적 입력 */}
          <div>
            <div className="mb-2 text-sm" style={{ color: COLORS.sub }}>목적 (purpose)</div>
            <textarea
              rows={3}
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              className="w-full rounded-md p-3 text-sm outline-none"
              placeholder="예) 저금리 대출유도 후 기존 대출기관 사칭으로 대출금 편취"
              style={{
                backgroundColor: COLORS.panel,
                border: `1px solid ${COLORS.border}`,
                color: COLORS.text,
                resize: "vertical",
              }}
              disabled={submitting}
            />
          </div>
        </div>

        {/* 푸터 */}
        <div className="mt-6 flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-md"
            style={{ backgroundColor: COLORS.panel, border: `1px solid ${COLORS.border}`, color: COLORS.text }}
            disabled={submitting}
          >
            닫기
          </button>
          <button
            onClick={createScenario}
            className="px-4 py-2 rounded-md"
            style={{ backgroundColor: canSubmit ? (COLORS.accent ?? COLORS.border) : COLORS.panel, color: canSubmit ? "#000" : COLORS.sub, border: `1px solid ${COLORS.border}`, opacity: submitting ? 0.6 : 1 }}
            disabled={!canSubmit || submitting}
          >
            {submitting ? "생성 중..." : "생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
