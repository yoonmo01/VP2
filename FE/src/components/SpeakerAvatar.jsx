import { useMemo, useState } from "react";
import { User } from "lucide-react";

/**
 * Props
 * - speaker: "offender" | "victim"
 * - isActive, isPlaying: 재생 상태
 * - COLORS: 색상 토큰
 * - size: 아바타 지름(px, 가로/세로 동일) — 기본 80
 * - photoSrc: 아바타 이미지(번들 import 경로)
 * - alt: 이미지 대체 텍스트
 * - showIconFallback: 이미지 실패 시 아이콘 폴백 여부
 */
export default function SpeakerAvatar({
  speaker,
  isActive,
  isPlaying,
  COLORS,
  size = 80,
  photoSrc,
  alt = "avatar",
  showIconFallback = true,
}) {
  const isOffender = speaker === "offender";
  const baseColor = isOffender ? COLORS.danger : COLORS.warn;
  const activeColor = isOffender ? "#FF6B6B" : "#FFD93D";
  const isOn = isActive && isPlaying;

  // size 파생 값
  const metrics = useMemo(() => {
    const icon = Math.round(size * 0.5);
    const borderW = Math.max(2, Math.round(size * 0.06));
    const shadowR = Math.round(size * 0.22);            // 내부 글로우(약간 축소)
    const labelFont = Math.max(12, Math.round(size * 0.18));
    const labelPx = Math.max(8, Math.round(size * 0.12));
    const labelPy = Math.max(4, Math.round(size * 0.08));
    const speakingScale = 1 + Math.min(0.08, size / 1000);

    // ✅ 바깥 링 두께/오프셋
    const outerRingInset = Math.max(6, Math.round(size * 0.08));
    const outerRingBorderW = Math.max(2, Math.round(size * 0.04));
    const outerGlowInset = Math.max(10, Math.round(size * 0.12));

    return {
      icon,
      borderW,
      shadowR,
      labelFont,
      labelPx,
      labelPy,
      speakingScale,
      outerRingInset,
      outerRingBorderW,
      outerGlowInset,
    };
  }, [size]);

  const [imgErr, setImgErr] = useState(false);
  const useImage = !!photoSrc && !imgErr;

  return (
    <div className="flex flex-col items-center gap-3">
      {/* ✅ 외부 래퍼: 바깥쪽 링을 위해 overflow-visible 유지 */}
      <div className="relative" style={{ width: size, height: size }}>
        {/* ✅ 바깥쪽 링(테두리 바깥에서 확장) */}
        {/* ✅ 바깥쪽 그라데이션 글로우 + 얇은 링(선택) */}
        {isOn && (
          <>
            {/* 퍼지는 빛: 라디얼 그라데이션 */}
            <span
              className="pointer-events-none absolute rounded-full animate-ping"
              style={{
                top: -metrics.outerGlowInset,
                right: -metrics.outerGlowInset,
                bottom: -metrics.outerGlowInset,
                left: -metrics.outerGlowInset,
                // 중심에서 바깥으로 자연스럽게 소멸
                background: `radial-gradient(
                  circle,
                  ${baseColor}66 0%,
                  ${baseColor}33 45%,
                  ${baseColor}1F 65%,
                  transparent 82%
                )`,
                opacity: 0.9,
                willChange: "transform, opacity",
              }}
              aria-hidden="true"
            />
            {/* 얇은 외곽 링(선명도 부스트; 필요 없으면 제거) */}
            <span
              className="pointer-events-none absolute rounded-full animate-ping"
              style={{
                top: -metrics.outerRingInset,
                right: -metrics.outerRingInset,
                bottom: -metrics.outerRingInset,
                left: -metrics.outerRingInset,
                border: `${metrics.outerRingBorderW}px solid ${baseColor}`,
                opacity: 0.25,
                boxSizing: "border-box",
                backgroundColor: "transparent",
                willChange: "transform, opacity",
              }}
              aria-hidden="true"
            />
          </>
        )}

        {/* 아바타 본체(이미지 원형 크롭) */}
        <div
          className="rounded-full flex items-center justify-center transition-all duration-300 overflow-hidden"
          style={{
            width: size,
            height: size,
            backgroundColor: isOn ? activeColor : COLORS.panel,
            borderColor: isOn ? activeColor : COLORS.border,
            borderStyle: "solid",
            borderWidth: metrics.borderW,
            boxShadow: isOn ? `0 0 ${metrics.shadowR}px ${baseColor}40` : "none",
            transform: isOn ? `scale(${metrics.speakingScale})` : "scale(1)",
          }}
          aria-label={isOffender ? "피싱범 아바타" : "피해자 아바타"}
        >
          {useImage ? (
            <img
              src={photoSrc}
              alt={alt}
              className="w-full h-full object-cover"
              onError={() => setImgErr(true)}
              draggable={false}
            />
          ) : (
            showIconFallback && (
              <User
                size={metrics.icon}
                style={{ color: isOn ? COLORS.black : COLORS.sub }}
                aria-hidden="true"
              />
            )
          )}
        </div>
      </div>

      {/* 라벨 */}
      <div
        className="rounded-lg font-bold transition-all duration-300 border"
        style={{
          fontSize: `${metrics.labelFont}px`,
          padding: `${metrics.labelPy}px ${metrics.labelPx}px`,
          backgroundColor: isOn ? baseColor : COLORS.panel,
          color: isOn ? COLORS.white : COLORS.sub,
          borderColor: isOn ? baseColor : COLORS.border,
        }}
      >
        {isOffender ? "피싱범" : "피해자"}
      </div>
    </div>
  );
}



//===================================

// import { User } from "lucide-react";

// export default function SpeakerAvatar({ speaker, isActive, isPlaying, COLORS }) {
//   const isOffender = speaker === "offender";
//   const baseColor = isOffender ? COLORS.danger : COLORS.warn;
//   const activeColor = isOffender ? "#FF6B6B" : "#FFD93D";

//   return (
//     <div className="flex flex-col items-center gap-3">
//       <div
//         className="relative w-20 h-20 rounded-full border-2 flex items-center justify-center transition-all duration-300"
//         style={{
//           backgroundColor: isActive && isPlaying ? activeColor : COLORS.panel,
//           borderColor: isActive && isPlaying ? activeColor : COLORS.border,
//           boxShadow: isActive && isPlaying ? `0 0 20px ${baseColor}40` : "none",
//         }}
//       >
//         <User
//           size={40}
//           style={{
//             color: isActive && isPlaying ? COLORS.black : COLORS.sub,
//           }}
//         />
//         {isActive && isPlaying && (
//           <div
//             className="absolute inset-0 rounded-full animate-ping"
//             style={{
//               backgroundColor: baseColor,
//               opacity: 0.3,
//             }}
//           />
//         )}
//       </div>

//       <div
//         className="px-4 py-2 rounded-lg text-base font-medium transition-all duration-300"
//         style={{
//           backgroundColor: isActive && isPlaying ? baseColor : COLORS.panel,
//           color: isActive && isPlaying ? COLORS.white : COLORS.sub,
//           border: `1px solid ${isActive && isPlaying ? baseColor : COLORS.border}`,
//         }}
//       >
//         {isOffender ? "피싱범" : "피해자"}
//       </div>
//     </div>
//   );
// }