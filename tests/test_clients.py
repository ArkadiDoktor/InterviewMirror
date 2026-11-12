"""HTTP client tests against a local stand-in for the model API - no real network."""
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

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["content-length"]))
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
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    FakeAPI.plan, FakeAPI.seen = {}, []
    llm._cooldown.clear()
    speech._working_stt.clear()
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


def test_transcription_and_silence_guards(api):
    api.plan = {"stt": "עבדתי שנתיים בתמיכה טכנית."}
    assert speech.transcribe(_wav(3)) == "עבדתי שנתיים בתמיכה טכנית."
    api.plan = {"stt": "תודה רבה."}
    assert speech.transcribe(_wav(2)) == ""                           # Whisper's classic answer to silence
    assert speech.transcribe(_wav(8)) == "תודה רבה."                  # ...but a long take may really say it
    n = len(api.seen)
    assert speech.transcribe(_wav(0.2)) == "" and len(api.seen) == n   # too short: no request at all


def test_speakable_strips_markup():
    assert speech.speakable("**שלום** 😀  `עולם`") == "שלום עולם"
