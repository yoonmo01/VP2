// src/constants/colors.js
// 기본 토큰 (필요시 확장)
const DEFAULT_COLORS = {
  // (기존 기본값 유지 — 필요 시 추가/수정)
  success: "#43B581",
  warn: "#FAA61A",
  danger: "#F04747",
};

// 사용자 제공 THEME을 명시적으로 만듭니다.
// 주의: THEME은 DEFAULT_COLORS 위에 덮어쓰기됩니다.
const THEME = {
  ...DEFAULT_COLORS,
  bg: "#030617",         // 더 어두운 네이비 배경
  panel: "#061329",      // 더 어두운 딥 블루 패널
  panelDark: "#04101f",  // 보조 패널 (어둡게)
  panelDarker: "#020812",// 가장 어두운 패널
  border: "#A8862A",     // 낮춘 골드(액센트)
  text: "#FFFFFF",
  sub: "#BFB38A",        // 낮춘 연한 골드/베이지
  blurple: "#A8862A",    // primary 역할 -> 어두운 골드(일관성 유지)
  success: DEFAULT_COLORS.success,
  warn: DEFAULT_COLORS.warn,
  white: "#FFFFFF",
};

export { DEFAULT_COLORS, THEME };
export default THEME;