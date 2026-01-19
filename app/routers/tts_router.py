# app/routers/tts_router.py
from __future__ import annotations
import os, io, base64, re, wave
from typing import List, Optional, Literal, Union, Tuple, Set
import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from pathlib import Path

from app.db.session import get_db
from app.db import models as m
from app.services.tts_service import get_cached_dialog, cache_run_dialog

# 환경 설정
load_dotenv()
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if cred_path:
    # 상대 경로면 절대 경로로 변환
    if not os.path.isabs(cred_path):
        # VP 디렉토리 기준으로 경로 계산
        base_dir = Path(__file__).parent.parent.parent  # VP 디렉토리
        cred_path = str(base_dir / cred_path)
    
    # 파일 존재 여부 확인
    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"Google Cloud credentials file not found: {cred_path}\n"
            f"Please check GOOGLE_APPLICATION_CREDENTIALS in .env"
        )
    
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
    print(f"✅ Google Cloud credentials loaded from: {cred_path}")
else:
    print("⚠️ GOOGLE_APPLICATION_CREDENTIALS not set in .env")

# Google TTS 클라이언트
from google.cloud import texttospeech_v1 as texttospeech
tts_client = texttospeech.TextToSpeechClient()

router = APIRouter(tags=["TTS"])

# ============================================
# Pydantic 모델들
# ============================================
class WordTiming(BaseModel):
    token: str
    charCount: int
    startSec: float
    durationSec: float

class DialogueItem(BaseModel):
    run_no: Optional[int] = None
    speaker: str
    text: str
    voiceName: str
    languageCode: str
    audioContent: str
    contentType: str
    totalDurationSec: float
    charTimeSec: float
    words: List[WordTiming]

class DialogueResponse(BaseModel):
    items: List[DialogueItem]
    note: str = "Word timings are heuristic (char-proportional)."

class CaseDialogueRequest(BaseModel):
    """케이스 대화 TTS 변환 요청"""
    case_id: str
    run_no: int  # 특정 라운드의 대화를 변환
    speakingRate: float = 1.5
    pitch: float = 0.0

# ============================================
# 음성 매핑
# ============================================
VOICE_BY_SPEAKER = {
    # 피싱범: 기본은 남자 프리미엄 (성별 정보 없을 때)
    "offender": {"languageCode": "ko-KR", "voiceName": "ko-KR-Chirp3-HD-Algenib"},
    # 피해자: age_group / gender 없을 때 fallback용 프리미엄 여 보이스
    "victim":   {"languageCode": "ko-KR", "voiceName": "ko-KR-Chirp3-HD-Aoede"},
}

# 피싱범: 성별 2종 전용 보이스
OFFENDER_VOICE_BY_GENDER = {
    "male": "ko-KR-Chirp3-HD-Algenib",
    "female": "ko-KR-Chirp3-HD-Erinome",
}


VOICE_BY_AGE_GENDER = {
    ("20s", "female"): "ko-KR-Chirp3-HD-Aoede",
    ("30s", "female"): "ko-KR-Chirp3-HD-Achernar",
    ("40s", "female"): "ko-KR-Chirp3-HD-Gacrux",
    ("50s", "female"): "ko-KR-Chirp3-HD-Erinome",
    ("60s", "female"): "ko-KR-Chirp3-HD-Pulcherrima",
    ("70s+", "female"): "ko-KR-Chirp3-HD-Vindemiatrix",
    ("20s", "male"): "ko-KR-Chirp3-HD-Achird",
    ("30s", "male"): "ko-KR-Chirp3-HD-Algenib",
    ("40s", "male"): "ko-KR-Chirp3-HD-Umbriel",
    ("50s", "male"): "ko-KR-Chirp3-HD-Rasalgethi",
    ("60s", "male"): "ko-KR-Chirp3-HD-Alnilam",
    ("70s+", "male"): "ko-KR-Chirp3-HD-Sadachbia",
}

OFFENDER_ALTERNATES = [
    "ko-KR-Chirp3-HD-Umbriel",
    "ko-KR-Chirp3-HD-Rasalgethi",
]

# ============================================
# 유틸리티 함수들
# ============================================
CHAR_PATTERN = re.compile(r"[가-힣A-Za-z0-9]")

def normalize_gender(g: Optional[str]) -> Optional[str]:
    if not g:
        return None
    s = str(g).strip().lower()
    if s in ("남", "남자", "m", "male"):
        return "male"
    if s in ("여", "여자", "f", "female"):
        return "female"
    return None

def count_chars(token: str) -> int:
    return len(CHAR_PATTERN.findall(token))

def wav_duration_sec(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / float(w.getframerate())

def wrap_pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, 
                    channels: int = 1, sampwidth: int = 2) -> bytes:
    """raw PCM (linear16) bytes → WAV 파일 bytes"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()

def synthesize_wav_and_timings(
    text: str,
    languageCode: str,
    voiceName: str,
    speakingRate: float = 1.5,
    pitch: float = 0.0,
    sample_rate_hz: int = 24000,
) -> Tuple[bytes, float, float, List[WordTiming]]:
    """Google TTS 호출 → WAV bytes 확보 + 타이밍 반환"""
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=languageCode, 
        name=voiceName
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        speaking_rate=speakingRate,
        pitch=pitch,
        sample_rate_hertz=sample_rate_hz,
    )

    resp = tts_client.synthesize_speech(
        input=synthesis_input, 
        voice=voice, 
        audio_config=audio_config
    )
    audio_bytes = resp.audio_content or b""

    # 이미 WAV인지 확인
    if len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        wav_bytes = audio_bytes
    else:
        wav_bytes = wrap_pcm_to_wav(audio_bytes, sample_rate=sample_rate_hz)

    total_sec = wav_duration_sec(wav_bytes)

    # 토큰화
    tokens = [tk for tk in re.split(r"\s+", text.strip()) if tk]
    counts = [count_chars(tk) for tk in tokens]
    total_chars = sum(counts)
    words: List[WordTiming] = []

    if total_chars <= 0 or not tokens:
        per = total_sec / max(len(tokens), 1) if tokens else 0.0
        acc = 0.0
        for tk in tokens:
            words.append(WordTiming(
                token=tk, charCount=0, 
                startSec=round(acc, 6), 
                durationSec=round(per, 6)
            ))
            acc += per
        return wav_bytes, total_sec, 0.0, words

    # 글자 비례 계산
    char_time = total_sec / total_chars
    acc = 0.0
    for tk, cc in zip(tokens, counts):
        dur = cc * char_time
        words.append(WordTiming(
            token=tk, charCount=cc, 
            startSec=acc, durationSec=dur
        ))
        acc += dur

    # 보정
    if words:
        last = words[-1]
        last_end = last.startSec + last.durationSec
        if total_sec - last_end > 1e-6:
            last.durationSec += (total_sec - last_end)

    for w in words:
        w.startSec = round(w.startSec, 6)
        w.durationSec = round(w.durationSec, 6)

    return wav_bytes, total_sec, round(char_time, 9), words

def choose_voice_name(
    speaker: str,
    age_group: Optional[str] = None,
    gender: Optional[str] = None,
    taken_voices: Optional[Set[str]] = None
) -> str:
    """화자/연령/성별 기반 음성 선택"""
    # 0. 피싱범: 성별만 보고 2개 중 하나 선택
    if speaker == "offender" and gender:
        base_candidate = OFFENDER_VOICE_BY_GENDER.get(gender)
        if base_candidate:
            # 피해자 음성과 겹치면 대체 후보 사용
            if taken_voices and base_candidate in taken_voices:
                for alt in OFFENDER_ALTERNATES:
                    if alt not in taken_voices:
                        return alt
            return base_candidate

    # 1. 피해자: 연령성별 프리미엄 매핑
    if age_group and gender:
        candidate = VOICE_BY_AGE_GENDER.get((age_group, gender))
        if candidate:
            return candidate

    # 2. 기본 fallback: speaker 기반
    base = VOICE_BY_SPEAKER.get(speaker, VOICE_BY_SPEAKER["victim"])
    candidate = base["voiceName"]

    return candidate

# ============================================
# ★★★ 핵심: 케이스 대화 TTS 변환 엔드포인트
# ============================================
@router.post("/case-dialogue", response_model=DialogueResponse)
def synthesize_case_dialogue(
    req: CaseDialogueRequest,
    db: Session = Depends(get_db)
):
    """
    케이스의 특정 라운드 대화를 TTS로 변환
    
    흐름:
    1. 캐시에서 대화 찾기
    2. 없으면 DB에서 로드
    3. TTS 변환
    """
    case_id = req.case_id
    run_no = req.run_no
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 1: 캐시에서 찾기
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    cached_turns = get_cached_dialog(case_id, run_no)
    
    if cached_turns:
        turns = cached_turns
        source = "cache"
    else:
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Step 2: DB에서 로드
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        round_row = (
            db.query(m.ConversationRound)
            .filter(
                m.ConversationRound.case_id == case_id,
                m.ConversationRound.run == run_no
            )
            .first()
        )
        
        if not round_row:
            raise HTTPException(
                status_code=404,
                detail=f"case_id={case_id}, run_no={run_no} 대화를 찾을 수 없습니다"
            )
        
        turns = round_row.turns or []
        source = "db"
        

    
    if not turns:
        raise HTTPException(
            status_code=404,
            detail=f"대화 내용이 비어있습니다 (source={source})"
        )
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 3: 피해자 음성 미리 수집 (충돌 방지)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    victim_voices: Set[str] = set()
    for turn in turns:
        role = turn.get("role", "")
        if role == "victim":
            age = turn.get("age_group")
            gender = normalize_gender(turn.get("gender"))
            v = choose_voice_name("victim", age, gender)
            victim_voices.add(v)
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 4: TTS 변환
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    items: List[DialogueItem] = []
    
    for turn in turns:
        role = turn.get("role", "unknown")
        text = turn.get("text", "")
        
        if not text:
            continue
        # ★★★ victim JSON 응답 처리
        if role == "victim" and text.strip().startswith("{"):
            try:
                victim_json = json.loads(text)
                text = victim_json.get("dialogue", text)
            except:
                pass
        # 음성 선택
        age = turn.get("age_group")
        gender = normalize_gender(turn.get("gender"))
        
        if role == "offender":
            vname = choose_voice_name("offender", age, gender, victim_voices)
        else:
            vname = choose_voice_name("victim", age, gender)
        
        lang = VOICE_BY_SPEAKER.get(role, VOICE_BY_SPEAKER["victim"])["languageCode"]
        
        try:
            wav_bytes, total_sec, char_time, words = synthesize_wav_and_timings(
                text=text,
                languageCode=lang,
                voiceName=vname,
                speakingRate=req.speakingRate,
                pitch=req.pitch,
                sample_rate_hz=24000
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"TTS 변환 실패: {e}"
            )
        
        items.append(DialogueItem(
            run_no=run_no,
            speaker=role,
            text=text,
            voiceName=vname,
            languageCode=lang,
            audioContent=base64.b64encode(wav_bytes).decode("utf-8"),
            contentType="audio/wav",
            totalDurationSec=round(total_sec, 3),
            charTimeSec=round(char_time, 6),
            words=words,
        ))
    
    return DialogueResponse(
        items=items,
        note=f"Loaded from {source}. Word timings are heuristic."
    )

# ============================================
# 기존 헬스체크 엔드포인트들
# ============================================
@router.get("/voices")
def list_voices():
    """사용 가능한 TTS 음성 목록 반환"""
    try:
        voices = tts_client.list_voices()
        korean_voices = [
            {
                "name": voice.name,
                "language_code": voice.language_codes[0],
                "ssml_gender": voice.ssml_gender.name,
                "natural_sample_rate": voice.natural_sample_rate_hertz
            }
            for voice in voices.voices
            if "ko-KR" in voice.language_codes[0]
        ]
        return {"voices": korean_voices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음성 목록 조회 실패: {e}")

@router.get("/health")
def tts_health():
    """TTS 서비스 헬스체크"""
    try:
        synthesis_input = texttospeech.SynthesisInput(text="테스트")
        voice = texttospeech.VoiceSelectionParams(
            language_code="ko-KR",
            name="ko-KR-Standard-A"
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16
        )
        
        tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return {"status": "healthy", "service": "google-tts"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}