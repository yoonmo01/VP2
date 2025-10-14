// src/CustomCharacterCreate.jsx
import { useState } from "react";

/** 내부에서 API_ROOT 계산 */
const RAW_API_BASE = import.meta.env?.VITE_API_URL || window.location.origin;
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_PREFIX = "/api";
const API_ROOT = `${API_BASE}${API_PREFIX}`;

/* ========== 내부 모달 컴포넌트 ========== */
function CustomCharacterModal({ open, onClose, onSave, theme }) {
  if (!open) return null;

  const C = theme || {
    panel: "#2B2D31",
    panelDark: "#232428",
    text: "#FFFFFF",
    sub: "#B5BAC1",
    border: "#3F4147",
    blurple: "#5865F2",
  };

  // 디지털 금융 리터러시 체크리스트 항목
  const DFL_ITEMS = [
    "디지털 금융 계약 시 서면 계약서에 반드시 서명한다.",
    "온라인에서 공유하는 개인정보가 어떻게 활용되는지 확인한다.",
    "투자하는 암호화폐가 법정화폐인지 여부를 알고 있다.",
    "비밀번호를 타인과 공유하지 않고 안전하게 관리한다.",
    "온라인 금융상품 구매 시 규제 여부를 확인한다.",
    "본인의 재무정보를 온라인에 불필요하게 공유하지 않는다.",
    "웹사이트 비밀번호를 정기적으로 변경한다.",
    "공용 Wifi 환경에서 온라인 쇼핑을 피한다.",
    "온라인 거래 시 웹사이트 보안(https, 자물쇠 표시)을 확인한다.",
    "온라인 구매 시 이용약관을 꼼꼼히 확인한다.",
  ];

  const DEFAULT = {
    name: "",
    ageBucket: "",
    gender: "",
    address: "",
    education: "",
    knowledge: {
      comparative_notes: [],
      competencies: [],
      digital_finance_literacy: [], // ✅ 새 필드: 체크한 문구 배열로 저장
    },
    traits: {
      ocean: {
        openness: "낮음",
        neuroticism: "낮음",
        extraversion: "낮음",
        agreeableness: "낮음",
        conscientiousness: "낮음",
      },
      vulnerability_notes: [],
    },
    note: "사용자 입력으로 생성",
  };

  const [form, setForm] = useState(DEFAULT);
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  // OCEAN 토글 헬퍼
  const OCEAN_LABEL = {
    openness: "개방성",
    neuroticism: "신경성",
    extraversion: "외향성",
    agreeableness: "친화성",
    conscientiousness: "성실성",
  };
  const setOcean = (key, value) =>
    set({
      traits: {
        ...form.traits,
        ocean: { ...form.traits.ocean, [key]: value },
      },
    });

  // 디지털 금융 리터러시 체크 토글
  const toggleDFL = (text) => {
    const selected = new Set(form.knowledge.digital_finance_literacy || []);
    if (selected.has(text)) selected.delete(text);
    else selected.add(text);
    set({
      knowledge: {
        ...form.knowledge,
        digital_finance_literacy: Array.from(selected),
      },
    });
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.ageBucket || !form.gender || !form.address || !form.education) {
      alert("필수 항목을 모두 입력하세요.");
      return;
    }

    // 서버에 POST (부모의 onSave -> createCustomVictim 사용)
    const payloadForParent = {
      name: form.name.trim(),
      meta: {
        age: form.ageBucket,
        education: form.education,
        gender: form.gender,
        address: form.address,
      },
      knowledge: {
        comparative_notes: form.knowledge.comparative_notes || [],
        competencies: form.knowledge.competencies || [],
        digital_finance_literacy: form.knowledge.digital_finance_literacy || [], // ✅ 추가
      },
      traits: {
        ...form.traits,
        ocean: { ...form.traits.ocean }, // "높음"/"낮음"
      },
      note: form.note,
    };

    try {
      await onSave?.(payloadForParent);
      onClose();
    } catch (err) {
      // 부모에서 에러 처리(alert)함
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-full max-w-2xl rounded-lg border shadow-xl"
        style={{ backgroundColor: C.panel, borderColor: C.border, color: C.text }}
      >
        <div className="px-5 py-4 border-b" style={{ borderColor: C.border }}>
          <h2 className="text-lg font-semibold">커스텀 캐릭터 만들기</h2>
        </div>

        <form onSubmit={onSubmit}>
          <div className="max-h-[70vh] overflow-y-auto px-5 py-4 space-y-4">
            {/* 기본 정보 ---------------------------------------------------- */}
            <input
              placeholder="이름 *"
              value={form.name}
              onChange={(e) => set({ name: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            />
            <select
              value={form.ageBucket}
              onChange={(e) => set({ ageBucket: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            >
              <option value="">연령대 *</option>
              {["20대","30대","40대","50대","60대","70대"].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            <select
              value={form.gender}
              onChange={(e) => set({ gender: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            >
              <option value="">성별 *</option>
              <option value="남성">남성</option>
              <option value="여성">여성</option>
            </select>
            <input
              placeholder="거주지 *"
              value={form.address}
              onChange={(e) => set({ address: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            />
            <select
              value={form.education}
              onChange={(e) => set({ education: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            >
              <option value="">학력 *</option>
              <option value="고등학교 중퇴">고등학교 중퇴</option>
              <option value="고등학교 졸업">고등학교 졸업</option>
              <option value="대학교 졸업">대학교 졸업</option>
            </select>

            {/* 성격 (OCEAN) ------------------------------------------------ */}
            <div className="pt-2">
              <div className="mb-2 text-sm" style={{ color: C.sub }}>
                성격 특성 (OCEAN) — 각 항목을 <b>높음/낮음</b>으로 선택
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {Object.keys(OCEAN_LABEL).map((key) => {
                  const val = form.traits.ocean[key];
                  const isHigh = val === "높음";
                  return (
                    <div
                      key={key}
                      className="flex items-center justify-between p-2 rounded border"
                      style={{ backgroundColor: C.panelDark, borderColor: C.border }}
                    >
                      <span className="text-sm">{OCEAN_LABEL[key]}</span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setOcean(key, "낮음")}
                          className="px-3 py-1 rounded text-sm"
                          style={{
                            border: `1px solid ${C.border}`,
                            backgroundColor: !isHigh ? C.blurple : "transparent",
                            color: !isHigh ? "#000" : C.text,
                          }}
                        >
                          낮음
                        </button>
                        <button
                          type="button"
                          onClick={() => setOcean(key, "높음")}
                          className="px-3 py-1 rounded text-sm"
                          style={{
                            border: `1px solid ${C.border}`,
                            backgroundColor: isHigh ? C.blurple : "transparent",
                            color: isHigh ? "#000" : C.text,
                          }}
                        >
                          높음
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 디지털 금융 리터러시 ---------------------------------------- */}
            <div className="pt-2">
              <div className="mb-2 text-sm" style={{ color: C.sub }}>
                디지털 금융 리터러시 (해당되는 항목을 체크)
              </div>
              <div className="space-y-2">
                {DFL_ITEMS.map((item) => {
                  const checked = (form.knowledge.digital_finance_literacy || []).includes(item);
                  return (
                    <label
                      key={item}
                      className="flex items-start gap-2 p-2 rounded border cursor-pointer"
                      style={{ backgroundColor: C.panelDark, borderColor: C.border }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleDFL(item)}
                        style={{ accentColor: C.blurple, marginTop: 4 }}
                      />
                      <span className="text-sm" style={{ color: C.text }}>{item}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            {/* 비고 -------------------------------------------------------- */}
            <textarea
              rows={3}
              placeholder="비고(선택)"
              value={form.note}
              onChange={(e) => set({ note: e.target.value })}
              className="w-full p-2 rounded outline-none"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            />
          </div>

          <div className="px-5 py-4 border-t flex justify-end gap-3" style={{ borderColor: C.border }}>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded"
              style={{ backgroundColor: C.panelDark, color: C.text }}
            >
              취소
            </button>
            <button
              type="submit"
              className="px-4 py-2 rounded text-white"
              style={{ backgroundColor: C.blurple }}
            >
              저장
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ========== 외부에 노출되는 “생성 버튼/타일” 컴포넌트 ========== */

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`);
  }
  return res.json();
}

/** 서버에 커스텀 피해자 생성 */
async function createCustomVictim(newCharFromModal) {
  const payload = {
    name: newCharFromModal.name,
    meta: newCharFromModal.meta || {},
    knowledge: {
      ...(newCharFromModal.knowledge || {}),
      // 서버가 모를 가능성에 대비해 빈 배열 보장
      digital_finance_literacy:
        newCharFromModal.knowledge?.digital_finance_literacy || [],
    },
    traits: newCharFromModal.traits || {},
    note: newCharFromModal.note || "사용자 입력으로 생성",
  };
  return postJson(`${API_ROOT}/make/victims/`, payload);
}

/**
 * Props:
 * - theme: { panel, panelDark, panelDarker, border, text, sub, blurple }
 * - onCreated?: (createdVictim) => void   // 저장 성공 시 부모에게 전달
 */
export default function CustomCharacterCreate({ theme, onCreated }) {
  const C = theme || {
    panel: "#061329",
    panelDark: "#04101f",
    panelDarker: "#020812",
    border: "#A8862A",
    text: "#FFFFFF",
    sub: "#B5BAC1",
    blurple: "#A8862A",
  };

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState(null);

  const handleSave = async (newCharFromModal) => {
    try {
      setSaving(true);
      const res = await createCustomVictim(newCharFromModal);
      const createdVictim = { ...res, isCustom: true }; // 프론트 표식
      setCreated(createdVictim);
      setOpen(false);
      onCreated && onCreated(createdVictim);
    } catch (e) {
      alert(`저장 실패: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="w-full">
      {/* 트리거 타일 */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full text-left rounded-2xl overflow-hidden border-2 border-dashed hover:opacity-90 transition"
        style={{
          backgroundColor: C.panelDark,
          borderColor: C.border,
          height: 320,
        }}
      >
        <div
          className="h-44 flex items-center justify-center text-5xl"
          style={{ backgroundColor: C.panelDarker }}
        >
          ➕
        </div>
        <div className="p-4">
          <div className="font-semibold text-lg" style={{ color: C.text }}>
            커스텀 캐릭터
          </div>
          <p className="mt-1 text-sm" style={{ color: C.sub }}>
            나이/성별/거주지/학력과 성격(OCEAN), 디지털 금융 리터러시를 입력하여 저장
          </p>
        </div>
      </button>

      {/* 방금 만든 커스텀 미리보기 */}
      {created && (
        <div
          className="mt-4 rounded-xl border p-4"
          style={{ borderColor: C.border, backgroundColor: C.panelDark }}
        >
          <div className="flex items-center justify-between mb-2">
            <div style={{ color: C.text }} className="font-semibold text-lg">
              {created.name}
              <span
                className="ml-2 text-xs px-2 py-1 rounded-md"
                style={{
                  color: C.blurple,
                  backgroundColor: "rgba(168,134,42,.08)",
                  border: `1px solid rgba(168,134,42,.18)`,
                }}
              >
                저장 완료 (id: {created.id})
              </span>
            </div>
          </div>

          <div style={{ color: C.sub }} className="text-sm space-y-1">
            <div>나이: <span style={{ color: C.text }}>{created.meta?.age ?? "-"}</span></div>
            <div>성별: <span style={{ color: C.text }}>{created.meta?.gender ?? "-"}</span></div>
            <div>거주지: <span style={{ color: C.text }}>{created.meta?.address ?? "-"}</span></div>
            <div>학력: <span style={{ color: C.text }}>{created.meta?.education ?? "-"}</span></div>
          </div>
        </div>
      )}

      {/* 입력 모달 */}
      {open && (
        <CustomCharacterModal
          open={open}
          onClose={() => !saving && setOpen(false)}
          onSave={handleSave}
          theme={C}
        />
      )}
    </div>
  );
}
