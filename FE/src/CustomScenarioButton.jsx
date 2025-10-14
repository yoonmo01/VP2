// src/components/CustomScenarioButton.jsx
import { Plus } from "lucide-react";
import Badge from "./Badge";

export default function CustomScenarioButton({ onClick, COLORS }) {
    return (
        <button
        onClick={onClick}
            className="w-full text-left rounded-lg p-4 hover:opacity-90 flex items-start gap-3"
            style={{
                backgroundColor: COLORS.panelDark,
                border: `1px solid ${COLORS.border}`,
                color: COLORS.text,
            }}
            >
            <div
                className="flex items-center justify-center rounded-md"
                style={{
                width: 36,
                height: 36,
                backgroundColor: COLORS.panel,
                border: `1px dashed ${COLORS.border}`,
                }}
            >
                <Plus size={20} />
            </div>
            <div className="flex-1">
                <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-lg">새 시나리오 추가</span>
                {/* <span
                    className="text-xs px-2 py-1 rounded-full"
                    style={{ backgroundColor: COLORS.panel, border: `1px solid ${COLORS.border}`, color: COLORS.sub }}
                >
                    커스텀
                </span> */}
                <Badge tone="primary" COLORS={COLORS}>
                    커스텀
                </Badge>
                </div>
                <p className="text-base leading-relaxed" style={{ color: COLORS.sub }}>
                직접 만든 시나리오를 추가해 목록에 저장하고 선택할 수 있어요.
                </p>
            </div>
        </button>
    );
}
