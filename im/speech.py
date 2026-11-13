"""Voice in both directions, free of charge.

Text-to-speech, best first:
  1. Gemini TTS (needs the free GEMINI_API_KEY). The most natural Hebrew, but
     the free quota is small, so it is used per interview and dropped for the
     rest of that interview as soon as it fails (the voice never flips back and forth).
  2. Microsoft Edge neural voice via ``edge-tts`` (no key).
  3. Google Translate voice via ``gTTS`` (no key, robotic - last server option).
  4. The browser's own voice, inside the avatar component.

Speech-to-text, best first:
  1. Gemini 3.5 Transcribe (GEMINI_API_KEY) - noticeably better at Hebrew.
  2. Whisper large-v3 on Groq (GROQ_API_KEY).
Both are guarded against the phrases recognisers invent from silence.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import threading
import time
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher

import requests

from .config import PROVIDERS, STT_MODELS, secret

log = logging.getLogger("interviewmirror.speech")

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
_HEBREW = re.compile(r"[\u05d0-\u05ea]")

# What recognisers tend to "hear" in silence or noise (Hebrew + English).
_HALLUCINATIONS = {
    "תודה", "תודה רבה", "תודה רבה לכם", "תודה שצפיתם", "תודה על הצפייה", "כתוביות", "תרגום",
    "כתוביות בעברית", "להתראות", "ביי", "שלום", "you", "thank you", "thanks for watching", "bye",
}

_rest_until: dict[str, float] = {}          # engine/model -> time it may be tried again
_lock = threading.Lock()
_voice_cache: dict[str, str] = {}           # persona key -> chosen Gemini voice id
_working_stt: list[str] = []


class SpeechError(RuntimeError):
    pass


@dataclass
class Speech:
    audio: bytes
    mime: str
    engine: str          # e.g. "gemini:gemini-3.8-flash-tts/Charon", "edge:he-IL-AvriNeural", "gtts"


# ------------------------------------------------------------------ helpers
def _rest(name: str, seconds: float) -> None:
    with _lock:
        _rest_until[name] = time.time() + seconds


def _resting(name: str) -> bool:
    with _lock:
        return _rest_until.get(name, 0) > time.time()


def _gemini_key() -> str | None:
    return PROVIDERS["gemini"].key()


def _gemini_base() -> str:
    return (secret("GEMINI_NATIVE_URL") or GEMINI_API).rstrip("/")


def _models(name: str, default: tuple[str, ...]) -> list[str]:
    raw = secret(name)
    return [m.strip() for m in raw.split(",") if m.strip()] if raw else list(default)


def speakable(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = re.sub(r"[*_#`~|<>\[\]{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect(obj, kind: str) -> list[dict]:
    """All content blocks of a given type inside an Interactions API response."""
    found = []
    if isinstance(obj, dict):
        if obj.get("type") == kind and ("data" in obj or "text" in obj):
            found.append(obj)
        for v in obj.values():
            found += _collect(v, kind)
    elif isinstance(obj, list):
        for v in obj:
            found += _collect(v, kind)
    return found


def _gemini_post(key: str, body: dict, timeout: float) -> requests.Response:
    return requests.post(f"{_gemini_base()}/interactions", headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                         json=body, timeout=(6, timeout))


def _quota_wait(resp: requests.Response, default: float) -> float:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        pass
    # a per-day quota cannot be waited out within an interview
    return 3600.0 if "per_day" in resp.text.lower() or "perday" in resp.text.lower() else default


# ------------------------------------------------------------ text-to-speech
def gemini_voice(persona: dict) -> str:
    """Pick a native Hebrew voice from Google's voice library, else a prebuilt one."""
    key = persona["key"]
    if key in _voice_cache:
        return _voice_cache[key]
    choice = persona["prebuilt"]
    api_key = _gemini_key()
    if api_key and not _resting("gemini:voices"):
        try:
            r = requests.get(f"{_gemini_base()}/voices", headers={"x-goog-api-key": api_key},
                             params={"language_code": "he-IL", "gender": "male", "page_size": 100}, timeout=(5, 10))
            if r.ok:
                voices = [v for v in r.json().get("voices", []) if v.get("id") or v.get("name")]
                taken = set(_voice_cache.values())
                best, best_score = None, -1
                for v in voices:
                    desc = " ".join(str(v.get(k, "")) for k in ("description", "persona", "display_name", "pitch")).lower()
                    score = sum(2 for w in persona["traits"] if w in desc) + (1 if v.get("pitch") == persona["pitch"] else 0)
                    vid = v.get("id") or v.get("name")
                    if vid in taken:
                        score -= 3                       # three different interviewers, three different voices
                    if score > best_score:
                        best, best_score = vid, score
                if best:
                    choice = best
            else:
                _rest("gemini:voices", 900)
        except requests.RequestException as exc:
            log.info("voice list unavailable: %s", exc)
            _rest("gemini:voices", 900)
    _voice_cache[key] = choice
    return choice


def _gemini_tts(text: str, persona: dict) -> Speech | None:
    api_key = _gemini_key()
    if not api_key:
        return None
    voice = gemini_voice(persona)
    for model in _models("GEMINI_TTS_MODELS", ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")):
        name = f"gemini-tts:{model}"
        if _resting(name):
            continue
        body = {
            "model": model,
            "input": [{"type": "user_input", "content": [{
                "type": "text", "text": text,
                "annotations": [{"type": "speech_metadata", "style": persona["style"]}]}]}],
            "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
            "generation_config": {"speech_config": [{"voice": voice}]},
        }
        try:
            resp = _gemini_post(api_key, body, 40)
            if resp.status_code == 400 and voice != persona["prebuilt"]:
                voice = _voice_cache[persona["key"]] = persona["prebuilt"]   # library voice rejected: use the prebuilt one
                body["generation_config"]["speech_config"] = [{"voice": voice}]
                resp = _gemini_post(api_key, body, 40)
            if resp.status_code == 429:
                _rest(name, _quota_wait(resp, 60))
                continue
            if not resp.ok:
                log.warning("%s failed: HTTP %s %s", name, resp.status_code, resp.text[:200])
                _rest(name, 600)
                continue
            blocks = _collect(resp.json(), "audio")
            if not blocks:
                log.warning("%s returned no audio", name)
                _rest(name, 300)
                continue
            audio = base64.b64decode(blocks[-1]["data"])
            if len(audio) < 2000:
                continue
            mime = blocks[-1].get("mime_type") or "audio/wav"
            if not audio.startswith(b"RIFF") and "l16" in mime:   # raw PCM: wrap it so the browser can play it
                audio, mime = pcm_to_wav(audio, 24000), "audio/wav"
            return Speech(audio, "audio/wav" if audio.startswith(b"RIFF") else mime, f"gemini:{model}/{voice}")
        except (requests.RequestException, ValueError, KeyError) as exc:
            log.warning("%s error: %s", name, type(exc).__name__)
            _rest(name, 120)
    return None


async def _edge_stream(text: str, voice: dict) -> bytes:
    import edge_tts

    com = edge_tts.Communicate(text, voice.get("edge", "he-IL-AvriNeural"), rate=voice.get("edge_rate", "+0%"))
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


def _edge(text: str, voice: dict) -> Speech | None:
    if _resting("edge"):
        return None
    try:
        audio = _run(_edge_stream(text, voice))
        if audio and len(audio) > 400:
            return Speech(audio, "audio/mpeg", f"edge:{voice.get('edge', 'he-IL-AvriNeural')}")
    except Exception as exc:  # noqa: BLE001
        log.warning("edge-tts failed: %s: %s", type(exc).__name__, exc)
        _rest("edge", 120)
    return None


def _gtts(text: str) -> Speech | None:
    try:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(text=text, lang="iw").write_to_fp(buf)
        if buf.tell() > 400:
            return Speech(buf.getvalue(), "audio/mpeg", "gtts")
    except Exception as exc:  # noqa: BLE001
        log.warning("gTTS failed: %s: %s", type(exc).__name__, exc)
    return None


ENGINES = ("gemini", "edge", "gtts")


def synthesize(text: str, voice: dict, engines: list[str] | None = None) -> Speech | None:
    """Speak ``text`` with the first engine in ``engines`` that works. None -> browser voice."""
    text = speakable(text)
    if not text:
        return None
    for eng in engines or list(ENGINES):
        result = (_gemini_tts(text, voice) if eng == "gemini" else
                  _edge(text, voice) if eng == "edge" else
                  _gtts(text) if eng == "gtts" else None)
        if result:
            return result
    return None


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# ------------------------------------------------------------ speech-to-text
def wav_seconds(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:  # noqa: BLE001 - not a plain WAV; let the API decide
        return None


def _collapse_loops(text: str) -> str:
    """Recognisers sometimes get stuck repeating a word or phrase; keep one copy."""
    for n in (4, 3, 2, 1):
        text = re.sub(r"((?:\S+\s+){%d})(?:\1){2,}" % n, r"\1", text + " ").strip()
    return text


def clean_transcript(text: str, seconds: float | None, hint: str = "") -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = _collapse_loops(text)
    bare = re.sub(r"[^\w\u05d0-\u05ea ]+", "", text).strip().lower()
    if not bare:
        return ""
    if bare in _HALLUCINATIONS and (seconds is None or seconds < 4):
        return ""
    if hint and SequenceMatcher(None, bare, re.sub(r"[^\w\u05d0-\u05ea ]+", "", hint).lower()).ratio() > 0.75:
        return ""   # the recogniser echoed its prompt instead of hearing speech
    return text


def _gemini_stt(audio: bytes, vocabulary: list[str]) -> str | None:
    api_key = _gemini_key()
    if not api_key:
        return None
    for model in _models("GEMINI_STT_MODELS", ("gemini-3.5-transcribe",)):
        name = f"gemini-stt:{model}"
        if _resting(name):
            continue
        cfg: dict = {"language_codes": ["he-IL", "en-US"]}
        if vocabulary:
            cfg["custom_vocabulary"] = vocabulary[:50]
        body = {"model": model,
                "input": [{"type": "audio", "data": base64.b64encode(audio).decode(), "mime_type": "audio/wav"}],
                "generation_config": {"transcription_config": cfg}}
        try:
            resp = _gemini_post(api_key, body, 60)
            if resp.status_code == 429:
                _rest(name, _quota_wait(resp, 60))
                continue
            if not resp.ok:
                log.warning("%s failed: HTTP %s %s", name, resp.status_code, resp.text[:200])
                _rest(name, 600)
                continue
            payload = resp.json()
            texts = [b["text"] for b in _collect(payload.get("steps", payload), "text")]
            text = " ".join(t for t in texts if t).strip() or str(payload.get("output_text", "")).strip()
            return text
        except (requests.RequestException, ValueError) as exc:
            log.warning("%s error: %s", name, type(exc).__name__)
            _rest(name, 120)
    return None


def _whisper(audio: bytes, hint: str) -> str:
    key = PROVIDERS["groq"].key()
    if not key:
        raise SpeechError("תמלול קולי דורש GROQ_API_KEY או GEMINI_API_KEY.")
    last_error = ""
    for model in _working_stt or STT_MODELS:
        try:
            resp = requests.post(
                f"{PROVIDERS['groq'].base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("answer.wav", audio, "audio/wav")},
                data={"model": model, "language": "he", "response_format": "json", "temperature": "0",
                      "prompt": hint[:300]},
                timeout=(6, 60),
            )
            if resp.status_code == 429:
                raise SpeechError("מכסת התמלול החינמית מוצתה לרגע. אפשר להקליד את התשובה או לנסות שוב בעוד דקה.")
            if resp.status_code >= 400:
                last_error = f"{model}: HTTP {resp.status_code}"
                continue
            if not _working_stt:
                _working_stt.append(model)
            return (resp.json().get("text") or "").strip()
        except requests.RequestException as exc:
            last_error = f"{model}: {type(exc).__name__}"
    log.error("transcription failed: %s", last_error)
    raise SpeechError("התמלול לא הצליח. אפשר לנסות שוב או להקליד את התשובה.")


@dataclass
class Transcript:
    text: str
    engine: str


def transcribe(audio: bytes, *, hint: str = "", vocabulary: list[str] | None = None) -> Transcript:
    """Hebrew speech -> text. ``text`` is '' when nothing intelligible was said."""
    seconds = wav_seconds(audio)
    if seconds is not None and seconds < 0.6:
        return Transcript("", "too-short")
    order = _models("STT_ENGINES", ("gemini", "whisper"))
    error: SpeechError | None = None
    for eng in order:
        if eng == "gemini":
            raw = _gemini_stt(audio, vocabulary or [])
            if raw is not None:
                return Transcript(clean_transcript(raw, seconds), "gemini")
        elif eng == "whisper":
            try:
                return Transcript(clean_transcript(_whisper(audio, hint), seconds, hint), "whisper")
            except SpeechError as exc:
                error = exc
    raise error or SpeechError("התמלול לא זמין כרגע. אפשר להקליד את התשובה.")
