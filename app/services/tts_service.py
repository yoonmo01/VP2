# app/services/tts_service.py
from __future__ import annotations
from typing import List, Dict, Any
import base64
import json
import threading



from app.core.logging import get_logger
from app.services.tts_cache import TTS_CACHE, TTSItem

logger = get_logger(__name__)

from openai import OpenAI

client = OpenAI()  # OPENAI_API_KEY 환경변수 필요


def _clean_offender_text(text: str) -> str:
    """
    공격자 발화에서 INTENT 줄 제거:
      "대사 ...\\nINTENT: 신뢰형성"
    → "대사 ..."
    """
    lines = str(text).splitlines()
    kept: List[str] = []
    for ln in lines:
        if ln.strip().startswith("INTENT:"):
            # 의도 라벨 줄은 TTS에서 제외
            continue
        if ln.strip():
            kept.append(ln.strip())
    # 문장 사이를 공백 하나로 이어서 한 덩어리로 만든다.
    return " ".join(kept).strip()


def _extract_victim_dialogue(text: str) -> str:
    """
    피해자 텍스트가 JSON이면 dialogue 필드만 사용.
    아니면 전체 텍스트 사용.
    """
    cleaned = str(text).strip()
    # JSON처럼 생겼을 때만 파싱 시도
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            obj = json.loads(cleaned)
            dlg = obj.get("dialogue")
            if isinstance(dlg, str) and dlg.strip():
                return dlg.strip()
            # dialogue가 없으면 그냥 원문 반환
            return cleaned
        except Exception:
            # 파싱 실패 시 그냥 원문 사용
            return cleaned
    return cleaned


def _extract_dialogue_turns(raw_turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    MCP simulator의 turns 리스트 → TTS용으로 정리.

    raw_turns 예:
      [
        {"role": "offender", "text": "저희 저금리 대출은 ...\\nINTENT: 신뢰형성"},
        {"role": "victim",   "text": "{ \\"is_convinced\\":..., \\"dialogue\\": \\"실제 대사...\\" }"},
        ...
      ]
    - 공격자: INTENT 줄 제거 + 나머지 문장만 사용
    - 피해자: JSON이면 dialogue 필드만 사용
    """
    result: List[Dict[str, Any]] = []

    for idx, t in enumerate(raw_turns):
        role = t.get("role") or t.get("speaker") or "offender"
        text = t.get("text", "")

        if role == "victim":
            text_for_tts = _extract_victim_dialogue(text)
        else:
            text_for_tts = _clean_offender_text(text)

        if not text_for_tts:
            continue

        result.append(
            {
                "turn_index": idx,
                "speaker": role,
                "text": text_for_tts,
            }
        )

    return result



def _generate_tts_for_run(case_id: str, run_no: int, raw_turns: List[Dict[str, Any]]) -> None:
    """
    실제 TTS 생성 로직 (백그라운드 쓰레드에서 실행).
    - 실패해도 orchestrator 흐름에는 영향을 주지 않음 (로그만 남김).
    """
    try:
        logger.info(f"[TTS] 시작 - case_id={case_id}, run_no={run_no}, turns={len(raw_turns)}")
        turns = _extract_dialogue_turns(raw_turns)
        logger.info(f"[TTS] 정제된 턴 수={len(turns)}")

        items: List[TTSItem] = []

        for t in turns:
            speaker = t["speaker"]
            text = t["text"]
            turn_index = t["turn_index"]

            # 간단한 보이스 전략: offender / victim 다른 목소리
            # (원하면 voice 이름을 config로 뺄 수 있음)
            voice_name = "alloy" if speaker == "offender" else "verse"

            try:
                resp = client.audio.speech.create(
                    model="gpt-4o-mini-tts",  # 또는 "tts-1", "tts-1-hd"
                    voice=voice_name,
                    format="wav",
                    input=text,
                )

                # 최신 SDK에서는 resp.read()로 바이너리 바이트 가져옴
                audio_bytes = resp.read()
            except Exception as e:
                logger.warning(
                    f"[TTS] OpenAI TTS 호출 실패(case_id={case_id}, run_no={run_no}, turn={turn_index}): {e}"
                )
                continue

            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            # 대략적인 길이 추정 (문자수 기반) – 프론트에서 파형/애니메이션에만 사용
            char_time_sec = max(len(text) / 8.0, 0.8)
            total_duration_sec = char_time_sec

            items.append(
                TTSItem(
                    case_id=str(case_id),
                    run_no=int(run_no),
                    turn_index=turn_index,
                    speaker=speaker,
                    text=text,
                    audio_b64=audio_b64,
                    total_duration_sec=total_duration_sec,
                    char_time_sec=char_time_sec,
                )
            )

        if not items:
            logger.warning(f"[TTS] 생성된 항목이 없습니다. case_id={case_id}, run_no={run_no}")
        else:
            TTS_CACHE.set_items(case_id, run_no, items)
            logger.info(
                f"[TTS] 완료 & 캐시 반영 - case_id={case_id}, run_no={run_no}, items={len(items)}"
            )

    except Exception as e:
        logger.error(f"[TTS] _generate_tts_for_run error: {e}", exc_info=True)


def start_tts_for_run_background(case_id: str, run_no: int, turns: List[Dict[str, Any]]) -> None:
    """
    orchestrator_react.py에서 호출하는 진입점.

    - DB 의존 없음.
    - 이미 같은 (case_id, run_no)에 대해 생성 중이거나 생성된 경우 중복 실행 방지.
    - 별도 daemon thread에서 TTS 생성.
    """
    if not case_id or not isinstance(run_no, int):
        logger.warning(f"[TTS] 잘못된 인자: case_id={case_id}, run_no={run_no}")
        return

    if not turns:
        logger.info(f"[TTS] turns 비어있음: case_id={case_id}, run_no={run_no}")
        return

    # 이미 캐시에 있거나 생성 중이면 스킵
    if TTS_CACHE.get_items(case_id, run_no) is not None:
        logger.info(f"[TTS] 이미 캐시에 존재: case_id={case_id}, run_no={run_no} → skip")
        return

    if TTS_CACHE.is_running(case_id, run_no):
        logger.info(f"[TTS] 이미 백그라운드 생성 중: case_id={case_id}, run_no={run_no} → skip")
        return

    TTS_CACHE.mark_running(case_id, run_no)

    def _worker():
        try:
            _generate_tts_for_run(case_id, run_no, turns)
        except Exception as e:
            logger.error(f"[TTS] worker thread error: {e}", exc_info=True)

    th = threading.Thread(
        target=_worker,
        name=f"tts-run-{case_id}-{run_no}",
        daemon=True,
    )
    th.start()
    logger.info(f"[TTS] 백그라운드 스레드 시작: case_id={case_id}, run_no={run_no}")
