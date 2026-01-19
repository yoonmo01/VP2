// src/components/TTSModal.jsx
import React, { useEffect, useRef, useState, useMemo } from "react";
import { X } from "lucide-react";
import AudioWaveform from "./AudioWaveForm";
import SpeakerAvatar from "./SpeakerAvatar";
import DEFAULT_COLORS from "../constants/colors";
import victim1 from "../../src/assets/victims/1.png";
import victim2 from "../../src/assets/victims/2.png";
import criminal from "../../src/assets/offender_profile_1.png";
import Wcriminal from "../../src/assets/offender_profile_2.png";

const RAW_API_BASE = (import.meta.env && import.meta.env.VITE_API_URL) || window.location.origin;
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_ROOT = `${API_BASE}/api`;

const toUrl = (b64, mime) => {
  const clean = (b64 || "").replace(/\s/g, "");
  const pad = "=".repeat((4 - (clean.length % 4)) % 4);
  const norm = clean.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const type = mime || "audio/wav";
  return `data:${type};base64,${norm}`;
};

// ★★★ 프로필 설정 훅
function useProfileConfig(
  victimGender,
  offenderGender,
  victimId,
  offenderId,
  victimImageUrl,   // 🎯 추가
) {
  const profiles = useMemo(() => {
    // ★★★ victim_id → 이미지 매핑
    const victimImageMap = {
      1: victim1,
      2: victim2,
      // 필요시 추가
    };
    // 1순위: 실제 선택된 캐릭터 이미지(victimImageUrl)
    // 2순위: 기존 victimId 기반 더미 이미지
    const victimImage = victimImageUrl || victimImageMap[victimId] || victim1;

    // ★★★ offender_id → 이미지 매핑
    const offenderImageMap = {
      1: criminal,        // offender_profile_1.png (남자)
      2: Wcriminal,       // offender_profile_2.png (여자)
    };
    const offenderImage = offenderImageMap[offenderId] || criminal;
    
    // ★★★ 성별 기반 음성 코드
    const isMaleVictim = victimGender === "남" || victimGender === "male";
    const isMaleOffender =
      offenderGender === "male" ||
      offenderGender === "남" ||
      offenderGender === "남자";

    return {
      victim: {
        image: victimImage, // ← ID 기반
        voice: isMaleVictim ? "ko-KR-Neural2-C" : "ko-KR-Neural2-A",
      },
      offender: {
        image: offenderImage,
        voice: isMaleOffender ? "ko-KR-Neural2-D" : "ko-KR-Neural2-B",
      },
    };
  }, [victimGender, offenderGender, victimId, offenderId, victimImageUrl]);

  return profiles;
}

export default function TTSModal({
  isOpen,
  onClose,
  COLORS,
  caseId,
  availableRuns = [],
  victimGender,
  offenderGender = "male",
  victimId = 1,
  offenderId = 1,
  victimImageUrl,
}) {
  const theme = COLORS ?? DEFAULT_COLORS;
  const profiles = useProfileConfig(
    victimGender,
    offenderGender,
    victimId,
    offenderId,
    victimImageUrl,
  );

  const [loading, setLoading] = useState(false);
  const [activeRun, setActiveRun] = useState(null);

  // run_no → { items, urls }
  const [runCache, setRunCache] = useState({});

  // 현재 재생 중인 턴
  const [currentRunItems, setCurrentRunItems] = useState([]);
  const [currentRunUrls, setCurrentRunUrls] = useState([]);
  const [currentIdx, setCurrentIdx] = useState(-1);
  const [currentText, setCurrentText] = useState("");
  const [currentSpeaker, setCurrentSpeaker] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const audioRef = useRef(null);

  // 🔥 모달 열림/닫힘 + caseId 변경 시 상태 초기화
  useEffect(() => {
    const a = audioRef.current;

    if (!isOpen) {
      if (a) {
        try {
          a.pause();
          a.removeAttribute("src");
          a.load();
        } catch (e) {
          console.warn("[TTSModal] audio reset error:", e);
        }
      }
      setActiveRun(null);
      setCurrentRunItems([]);
      setCurrentRunUrls([]);
      setCurrentIdx(-1);
      setCurrentText("");
      setCurrentSpeaker(null);
      setIsPlaying(false);
      return;
    }

    setRunCache({});
    setActiveRun(null);
  }, [isOpen, caseId]);

  // 🔥 run_no 기준으로 TTS 생성/조회
  const fetchRunTTS = async (runNo) => {
    if (!caseId) {
      alert("case_id가 없어 TTS를 생성할 수 없습니다.");
      return null;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_ROOT}/tts/case-dialogue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          case_id: caseId,
          run_no: runNo,
          speakingRate: 1.5,
          pitch: 0.0
        })
      });

      if (!res.ok) {
        const msg = await res.text();
        throw new Error(`HTTP ${res.status} : ${msg}`);
      }

      const data = await res.json();
      const items = data.items || [];

      if (items.length === 0) {
        throw new Error("대화 내용이 없습니다.");
      }

      const urls = items.map(item => toUrl(item.audioContent, item.contentType));

      return { items, urls };
    } catch (e) {
      console.error(e);
      alert(`TTS 생성/조회 중 오류: ${e.message}`);
      return null;
    } finally {
      setLoading(false);
    }
  };

  // 🔥 특정 인덱스의 턴 재생
  const playAtIndex = async (idx, items, urls) => {
    const a = audioRef.current;
    if (!a || !urls[idx] || !items[idx]) return;

    const item = items[idx];
    setCurrentIdx(idx);
    setCurrentText(item.text || "");
    setCurrentSpeaker(item.speaker || "unknown");
    setIsPlaying(true);

    // ★★★ 동적 음성 코드 사용
    const voiceCode = item.speaker === "victim" 
      ? profiles.victim.voice 
      : profiles.offender.voice;

    try {
      a.pause();
      a.src = urls[idx];
      a.load();

      await new Promise((resolve, reject) => {
        a.addEventListener("loadedmetadata", resolve, { once: true });
        a.addEventListener("error", reject, { once: true });
        setTimeout(() => reject(new Error("timeout")), 6000);
      });

      await a.play();
    } catch (err) {
      console.warn("[playAtIndex] error:", err);
      setIsPlaying(false);
    }
  };

  // 🔥 특정 run_no 대화 전체 재생
  const playRun = async (runNo) => {
    let cached = runCache[runNo];

    if (!cached) {
      const fetched = await fetchRunTTS(runNo);
      if (!fetched) return;
      cached = fetched;
      setRunCache((prev) => ({ ...prev, [runNo]: fetched }));
    }

    const { items, urls } = cached;

    if (!items || items.length === 0) {
      alert(`${runNo}번째 대화가 비어 있습니다.`);
      return;
    }

    setActiveRun(runNo);
    setCurrentRunItems(items);
    setCurrentRunUrls(urls);
    setCurrentIdx(-1);
    setCurrentText("");
    setCurrentSpeaker(null);
    setIsPlaying(false);

    await playAtIndex(0, items, urls);
  };

  // 오디오 끝나면 다음 턴 자동 재생
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;

    const onEnded = () => {
      const next = currentIdx + 1;
      if (next < currentRunItems.length) {
        playAtIndex(next, currentRunItems, currentRunUrls);
      } else {
        setCurrentIdx(-1);
        setCurrentText("");
        setCurrentSpeaker(null);
        setIsPlaying(false);
      }
    };

    a.addEventListener("ended", onEnded);
    return () => a.removeEventListener("ended", onEnded);
  }, [currentIdx, currentRunItems, currentRunUrls]);

  // 재생 상태 이벤트
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;

    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onError = () => setIsPlaying(false);

    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("error", onError);

    return () => {
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("error", onError);
    };
  }, []);

  if (!isOpen) return null;

  const runKeys =
    availableRuns && availableRuns.length > 0
      ? availableRuns
      : Object.keys(runCache).map((k) => Number(k));

  const WAVE_HEIGHT = 140;
  const WAVE_MAX_BAR = 120;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0"
        style={{ backgroundColor: "#00000080" }}
        aria-hidden="true"
      />

      <div
        className="relative mx-4 rounded-3xl border overflow-hidden flex flex-col"
        style={{
          width: 900,
          height: 760,
          backgroundColor: "#020617",
          borderColor: "#334155",
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-xl font-bold text-white">음성 대화 시뮬레이션</h2>
          <button
            onClick={onClose}
            className="p-1 text-slate-300 hover:text-white"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 px-8 py-6 flex flex-col overflow-hidden gap-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              {(runKeys.length > 0 ? runKeys : [1])
                .sort((a, b) => Number(a) - Number(b))
                .map((runKey) => (
                  <button
                    key={runKey}
                    onClick={() => playRun(Number(runKey))}
                    disabled={loading}
                    className={`px-4 py-2 text-sm rounded-md border text-slate-100 ${
                      Number(runKey) === activeRun
                        ? "border-amber-400 bg-amber-500/20"
                        : "border-slate-600"
                    }`}
                  >
                    {runKey}번째 대화
                  </button>
                ))}
            </div>

            <button
              onClick={() =>
                alert("각 라운드 버튼을 눌러 TTS를 생성/재생하세요.")
              }
              disabled={loading}
              className="px-4 py-2 rounded-md text-sm font-semibold bg-amber-500 text-black disabled:opacity-60"
            >
              {loading ? "TTS 생성 중..." : "도움말"}
            </button>
          </div>

          <div
            className="grid items-center"
            style={{
              gridTemplateColumns: `${WAVE_MAX_BAR + 40}px 1fr ${
                WAVE_MAX_BAR + 40
              }px`,
              columnGap: 24,
            }}
          >
            <SpeakerAvatar
              speaker="offender"
              isActive={currentSpeaker === "offender"}
              isPlaying={isPlaying}
              COLORS={theme}
              size={WAVE_MAX_BAR}
              photoSrc={profiles.offender.image}
            />

            <AudioWaveform
              isActive={isPlaying}
              speaker={currentSpeaker}
              COLORS={theme}
              heightPx={WAVE_HEIGHT}
              maxBarHeight={WAVE_MAX_BAR}
            />

            <SpeakerAvatar
              speaker="victim"
              isActive={currentSpeaker === "victim"}
              isPlaying={isPlaying}
              COLORS={theme}
              size={WAVE_MAX_BAR}
              photoSrc={profiles.victim.image}
            />
          </div>

          <div className="min-h-20 p-4 rounded-md border border-slate-700 text-center text-slate-100 flex items-center justify-center">
            {currentText ||
              "위의 라운드 버튼을 눌러 해당 라운드의 음성 대화를 재생하세요."}
          </div>

          {/* 🔥 진행률 표시 (선택사항) */}
          {currentRunItems.length > 0 && (
            <div className="flex justify-between text-sm text-slate-400">
              <span>
                {currentIdx + 1} / {currentRunItems.length} 턴
              </span>
              <span>
                {currentSpeaker === "offender" ? "피싱범" : "피해자"} 발화 중
              </span>
            </div>
          )}
        </div>

        <audio ref={audioRef} className="hidden" />
      </div>
    </div>
  );
}