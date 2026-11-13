"""HTTP client tests against a local stand-in for the model API - no real network."""
import base64
import io
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from im import llm, speech


class FakeAPI(BaseHTTPRequestHandler):
    plan: dict = {}
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, payload, headers=None):
        data = json.dumps(payload).encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/v1beta/voices"):
            FakeAPI.seen.append(("voices", self.path))
            return self._send(200, {"voices": FakeAPI.plan.get("voices", [])})
        self._send(404, {})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["content-length"]))
        if self.path.endswith("/interactions"):
            body = json.loads(raw)
            FakeAPI.seen.append(("gemini", body))
            code, payload = FakeAPI.plan.get(body["model"], (500, {}))
            return self._send(code, payload)
        if self.path.endswith("/audio/transcriptions"):
            FakeAPI.seen.append(("stt", raw))
            return self._send(200, {"text": FakeAPI.plan.get("stt", "")})
        body = json.loads(raw)
        FakeAPI.seen.append((body["model"], body))
        code, content = FakeAPI.plan.get(body["model"], (200, '{"say": "ok"}'))
        if code == 429:
            return self._send(429, {"error": "slow down"}, {"retry-after": "7"})
        if code == "strict" and "response_format" in body:
            return self._send(400, {"error": "unknown parameter"})
        if code not in (200, "strict"):
            return self._send(code, {"error": "x"})
        self._send(200, {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 42}})


@pytest.fixture()
def api(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GROQ_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("GEMINI_NATIVE_URL", f"http://127.0.0.1:{srv.server_port}/v1beta")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    FakeAPI.plan, FakeAPI.seen = {}, []
    llm._cooldown.clear()
    speech._working_stt.clear()
    speech._rest_until.clear()
    speech._voice_cache.clear()
    yield FakeAPI
    srv.shutdown()


def test_first_route_answers(api):
    res = llm.chat_json("turn", [{"role": "user", "content": "hi"}])
    assert res.data == {"say": "ok"} and res.model == "groq:openai/gpt-oss-120b" and res.tokens == 42
    assert api.seen[0][1]["response_format"] == {"type": "json_object"}


def test_rate_limit_falls_through_and_rests_the_route(api):
    api.plan = {"openai/gpt-oss-120b": (429, "")}
    assert llm.chat_json("turn", [{"role": "user", "content": "hi"}]).model == "groq:qwen/qwen3.8-27b"
    assert 0 < llm._resting("groq:openai/gpt-oss-120b") <= 7
    api.seen.clear()
    llm.chat_json("turn", [{"role": "user", "content": "hi"}])
    assert [m for m, _ in api.seen] == ["qwen/qwen3.8-27b"]            # the rested model is not even tried


def test_all_rate_limited_is_reported_as_such(api):
    api.plan = {m: (429, "") for m in ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b")}
    with pytest.raises(llm.LLMUnavailable) as err:
        llm.chat_json("turn", [{"role": "user", "content": "hi"}])
    assert err.value.rate_limited and err.value.wait > 0


def test_bad_json_and_server_errors_fall_through(api):
    api.plan = {"openai/gpt-oss-120b": (200, "not json at all"), "qwen/qwen3.8-27b": (503, "")}
    assert llm.chat_json("turn", [{"role": "user", "content": "hi"}]).model == "groq:openai/gpt-oss-20b"


def test_provider_that_rejects_optional_params_gets_a_minimal_retry(api):
    api.plan = {"openai/gpt-oss-120b": ("strict", '```json\n{"say": "שלום"}\n```')}
    res = llm.chat_json("turn", [{"role": "user", "content": "hi"}])
    assert res.data == {"say": "שלום"} and "response_format" not in api.seen[-1][1]


def test_no_key_is_a_clear_error(monkeypatch):
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(llm.LLMUnavailable, match="GROQ_API_KEY"):
        llm.chat_json("turn", [{"role": "user", "content": "hi"}])


def _wav(seconds):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * seconds))
    return buf.getvalue()


def test_whisper_transcription_and_silence_guards(api):
    api.plan = {"stt": "עבדתי שנתיים בתמיכה טכנית."}
    assert speech.transcribe(_wav(3)).text == "עבדתי שנתיים בתמיכה טכנית."
    api.plan = {"stt": "תודה רבה."}
    assert speech.transcribe(_wav(2)).text == ""                      # the classic answer to silence
    assert speech.transcribe(_wav(8)).text == "תודה רבה."             # ...but a long take may really say it
    api.plan = {"stt": "ספר לי על פרויקט שעשית"}
    assert speech.transcribe(_wav(3), hint="ספר לי על פרויקט שעשית?").text == ""   # echo of the prompt
    api.plan = {"stt": "אני אני אני אני אני חושב שכן"}
    assert speech.transcribe(_wav(3)).text == "אני חושב שכן"           # stuck-in-a-loop output
    n = len(api.seen)
    assert speech.transcribe(_wav(0.2)).text == "" and len(api.seen) == n   # too short: no request at all


def _audio_reply(wav):
    return (200, {"steps": [{"type": "user_input", "content": [{"type": "text", "text": "x"}]},
                            {"type": "model_output", "content": [{"type": "audio", "mime_type": "audio/wav",
                                                                 "data": base64.b64encode(wav).decode()}]}]})


def test_gemini_is_preferred_for_transcription(api, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    api.plan = {"gemini-3.5-transcribe": (200, {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "הובלתי צוות של חמישה"}]}]}),
                "stt": "לא אמור להגיע לכאן"}
    r = speech.transcribe(_wav(3), vocabulary=["React"])
    assert (r.text, r.engine) == ("הובלתי צוות של חמישה", "gemini")
    sent = [b for m, b in api.seen if m == "gemini"][0]
    assert sent["generation_config"]["transcription_config"]["language_codes"][0] == "he-IL"
    assert sent["input"][0]["type"] == "audio" and sent["generation_config"]["transcription_config"]["custom_vocabulary"] == ["React"]


def test_gemini_quota_falls_back_to_whisper(api, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    api.plan = {"gemini-3.5-transcribe": (429, {"error": "GenerateRequestsPerDayPerProjectPerModel"}), "stt": "תשובה מ-Whisper"}
    assert speech.transcribe(_wav(3)).engine == "whisper"
    api.seen.clear()
    speech.transcribe(_wav(3))
    assert not [m for m, _ in api.seen if m == "gemini"]               # a spent daily quota is not retried


def test_tts_prefers_gemini_with_a_native_voice(api, monkeypatch):
    from im.personas import PERSONAS
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    wav = _wav(1)
    api.plan = {"gemini-3.8-flash-tts": _audio_reply(wav),
                "voices": [{"id": "voice_he_1", "gender": "male", "pitch": "low", "description": "Deep, firm and authoritative"},
                           {"id": "voice_he_2", "gender": "male", "pitch": "medium", "description": "Warm and friendly"}]}
    tough = speech.synthesize("שלום", PERSONAS["tough"].voice, ["gemini", "edge"])
    friendly = speech.synthesize("שלום", PERSONAS["friendly"].voice, ["gemini", "edge"])
    assert tough.audio == wav and tough.engine.endswith("/voice_he_1") and friendly.engine.endswith("/voice_he_2")
    body = [b for m, b in api.seen if m == "gemini"][0]
    assert body["input"][0]["content"][0]["annotations"][0]["style"] == PERSONAS["tough"].voice["style"]


def test_tts_falls_through_models_then_engines(api, monkeypatch):
    from im.personas import PERSONAS
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    api.plan = {"gemini-3.8-flash-tts": (429, {}), "gemini-3.8-flash-lite-tts": _audio_reply(_wav(1))}
    assert "flash-lite-tts" in speech.synthesize("שלום", PERSONAS["technical"].voice, ["gemini"]).engine
    api.plan = {"gemini-3.8-flash-lite-tts": (429, {})}
    monkeypatch.setattr(speech, "_edge", lambda text, voice: speech.Speech(b"mp3", "audio/mpeg", "edge:x"))
    assert speech.synthesize("שלום", PERSONAS["technical"].voice, ["gemini", "edge"]).engine == "edge:x"
    monkeypatch.setattr(speech, "_edge", lambda text, voice: None)
    monkeypatch.setattr(speech, "_gtts", lambda text: None)
    assert speech.synthesize("שלום", PERSONAS["technical"].voice) is None        # -> the browser speaks


def test_speakable_strips_markup():
    assert speech.speakable("**שלום** 😀  `עולם`") == "שלום עולם"
