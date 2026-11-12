"""Voice in both directions, free of charge.

Text-to-speech: Microsoft Edge neural voices via ``edge-tts`` (natural Hebrew,
no key), then Google Translate TTS via ``gTTS`` as a fallback. If both fail the
browser's own speech synthesis takes over inside the avatar component.

Speech-to-text: Whisper on Groq's free tier, with guards against the phrases
Whisper invents when it is handed silence.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import wave

import requests

from .config import PROVIDERS, STT_MODELS

log = logging.getLogger("interviewmirror.speech")

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
_working_stt: list[str] = []

# What Whisper tends to "hear" in silence or noise (Hebrew + English).
_HALLUCINATIONS = {
    "תודה", "תודה רבה", "תודה רבה לכם", "תודה שצפיתם", "תודה על הצפייה", "כתוביות", "תרגום",
    "כתוביות בעברית", "להתראות", "ביי", "שלום", "you", "thank you", "thanks for watching", "bye",
}


class SpeechError(RuntimeError):
    pass


def speakable(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = re.sub(r"[*_#`~|<>\[\]{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


async def _edge(text: str, voice: dict) -> bytes:
    import edge_tts

    com = edge_tts.Communicate(text, voice.get("name", "he-IL-AvriNeural"),
                               rate=voice.get("rate", "+0%"), pitch=voice.get("pitch", "+0Hz"))
    buf = bytearray()
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def _run(coro, timeout: float = 15.0):
    """Run a coroutine from sync code, whether or not a loop already exists."""
    box: dict = {}

    def worker():
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001 - reported to the caller below
            box["error"] = exc

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError("text-to-speech timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def synthesize(text: str, voice: dict) -> tuple[bytes, str] | None:
    """Return (audio bytes, mime type), or None when no server-side voice works."""
    text = speakable(text)
    if not text:
        return None
    try:
        audio = _run(_edge(text, voice))
        if audio and len(audio) > 400:
            return audio, "audio/mpeg"
    except Exception as exc:  # noqa: BLE001
        log.warning("edge-tts failed: %s: %s", type(exc).__name__, exc)
    try:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(text=text, lang="iw").write_to_fp(buf)
        if buf.tell() > 400:
            return buf.getvalue(), "audio/mpeg"
    except Exception as exc:  # noqa: BLE001
        log.warning("gTTS failed: %s: %s", type(exc).__name__, exc)
    return None


def wav_seconds(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:  # noqa: BLE001 - not a plain WAV; let the API decide
        return None


def transcribe(audio: bytes, *, hint: str = "") -> str:
    """Hebrew speech -> text. Returns '' when nothing intelligible was said."""
    key = PROVIDERS["groq"].key()
    if not key:
        raise SpeechError("תמלול קולי דורש GROQ_API_KEY.")
    seconds = wav_seconds(audio)
    if seconds is not None and seconds < 0.5:
        return ""
    last_error = ""
    for model in _working_stt or STT_MODELS:
        try:
            resp = requests.post(
                f"{PROVIDERS['groq'].base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("answer.wav", audio, "audio/wav")},
                data={"model": model, "language": "he", "response_format": "json", "temperature": "0",
                      "prompt": hint[:400]},
                timeout=(6, 60),
            )
            if resp.status_code == 429:
                raise SpeechError("מכסת התמלול החינמית מוצתה לרגע. אפשר להקליד את התשובה או לנסות שוב בעוד דקה.")
            if resp.status_code >= 400:
                last_error = f"{model}: HTTP {resp.status_code}"
                continue
            text = (resp.json().get("text") or "").strip()
            if not _working_stt:
                _working_stt.append(model)
            bare = re.sub(r"[^\w\u05d0-\u05ea ]+", "", text).strip().lower()
            if not bare or (bare in _HALLUCINATIONS and (seconds is None or seconds < 4)):
                return ""
            return text
        except requests.RequestException as exc:
            last_error = f"{model}: {type(exc).__name__}"
    log.error("transcription failed: %s", last_error)
    raise SpeechError("התמלול לא הצליח. אפשר לנסות שוב או להקליד את התשובה.")
