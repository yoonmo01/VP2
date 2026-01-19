import React, { useEffect, useMemo, useRef, useState } from "react";

/**
 * Props
 * - isActive: 재생 중 여부
 * - speaker: "offender" | "victim"
 * - COLORS: 색상 토큰
 * - bars: number | "auto"  (기본 "auto")
 * - density: 100px 당 막대 개수 (bars="auto"일 때만 사용, 기본 8)
 * - gap: 막대 사이 간격(px, 기본 3)
 * - maxBarHeight: 막대 최대 높이(px, 기본 60)
 * - idleHeight: 비활성 시 고정 높이 비율(0~1, 기본 0.2)
 * - speedMs: 높이 갱신 주기(ms, 기본 220)
 */
export default function AudioWaveform({
  isActive,
  speaker,
  COLORS,
  bars = "auto",
  density = 10,
  gap = 4,
  maxBarHeight = 120,
  idleHeight = 0.2,
  speedMs = 200,
  heightPx = 140,
  containerClassName = "",
}) {
  const rootRef = useRef(null);

  // 실제 렌더링에 사용할 막대 수
  const [nBars, setNBars] = useState(
    typeof bars === "number" ? Math.max(5, bars) : 15
  );

  // 컨테이너 폭에 따라 자동 계산
  useEffect(() => {
    if (typeof bars === "number") {
      setNBars(Math.max(5, bars));
      return;
    }
    const el = rootRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect?.width ?? el.clientWidth ?? 0;
      // 100px 당 density개 → 전체 막대수 계산
      const calc = Math.max(5, Math.floor((width / 100) * density));
      setNBars(calc);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [bars, density]);

  // 막대 높이 상태
  const [heights, setHeights] = useState(() => Array(nBars).fill(idleHeight));
  // 막대 수가 바뀌면 길이 맞춰 리셋
  useEffect(() => {
    setHeights((prev) => {
      if (prev.length === nBars) return prev;
      const next = Array(nBars).fill(idleHeight);
      // 이전 값 일부 보존(부드러운 전환)
      for (let i = 0; i < Math.min(prev.length, nBars); i++) next[i] = prev[i];
      return next;
    });
  }, [nBars, idleHeight]);

  // 활성화 시 랜덤 파형 갱신
  useEffect(() => {
    if (!isActive) {
      setHeights(Array(nBars).fill(idleHeight));
      return;
    }
    const interval = setInterval(() => {
      setHeights(() =>
        Array(nBars)
          .fill(0)
          .map(() => idleHeight + Math.random() * (1 - idleHeight))
      );
    }, speedMs);
    return () => clearInterval(interval);
  }, [isActive, nBars, idleHeight, speedMs]);

  const barWidthPercent = useMemo(() => {
    // 전체에서 (nBars - 1) * gap 만큼 간격을 빼고, 남은 너비를 nBars로 균등 분배
    return `calc((100% - ${(nBars - 1) * gap}px) / ${nBars})`;
  }, [nBars, gap]);

  const getBarColor = () => {
    if (!isActive) return COLORS.border;
    return speaker === "offender" ? COLORS.danger : COLORS.warn;
    // 필요 시 victim 전용 색: COLORS.warn → COLORS.success 등으로 교체
  };

  return (
    <div
        ref={rootRef}
        className="flex items-end justify-between w-full"
        style={{ gap: `${gap}px`, height: `${heightPx}px` }} // ✅ 높이 적용
        aria-label="audio-waveform"
    >
      {Array.from({ length: nBars }, (_, i) => (
        <div
          key={i}
          className="transition-all duration-150 ease-out rounded-full"
          style={{
            width: barWidthPercent,
            height: `${heights[i] * maxBarHeight}px`,
            minHeight: "4px",
            backgroundColor: getBarColor(),
          }}
        />
      ))}
    </div>
  );
}


// ====================

// import React, { useEffect, useState } from "react";

// export default function AudioWaveform({ isActive, speaker, COLORS, bars = 15 }) {
//   const [heights, setHeights] = useState(Array(bars).fill(0.2));

//   useEffect(() => {
//     if (!isActive) {
//       setHeights(Array(bars).fill(0.2));
//       return;
//     }
//     const interval = setInterval(() => {
//       setHeights(() => Array(bars).fill(0).map(() => 0.2 + Math.random() * 0.8));
//     }, 150);
//     return () => clearInterval(interval);
//   }, [isActive, bars]);

//   const getBarColor = () => {
//     if (!isActive) return COLORS.border;
//     return speaker === "offender" ? COLORS.danger : COLORS.warn;
//   };

//   return (
//     <div className="flex items-end justify-center gap-1 h-20">
//       {Array.from({ length: bars }, (_, i) => (
//         <div
//           key={i}
//           className="w-1 transition-all duration-150 ease-out rounded-full"
//           style={{
//             height: `${heights[i] * 60}px`,
//             backgroundColor: getBarColor(),
//             minHeight: "4px",
//           }}
//         />
//       ))}
//     </div>
//   );
// }