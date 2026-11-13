"""One small client for every OpenAI-compatible chat API, with automatic fail-over.

Free tiers are rate-limited, so a single model is a single point of failure.
``chat_json`` walks an ordered list of routes and returns the first good JSON
answer; a route that reports a rate limit is rested for as long as the server
asks, so the next turn does not waste a request on it.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass

import requests

from .config import PROVIDERS, Route, routes

log = logging.getLogger("interviewmirror.llm")

_cooldown: dict[str, float] = {}
_lock = threading.Lock()
_session = requests.Session()


class LLMUnavailable(RuntimeError):
    """No configured model could answer right now."""

    def __init__(self, message: str, rate_limited: bool = False, wait: float = 0.0):
        super().__init__(message)
        self.rate_limited = rate_limited
        self.wait = wait


@dataclass
class LLMResult:
    data: dict
    model: str
    tokens: int = 0


def _rest(route_id: str, seconds: float) -> None:
    with _lock:
        _cooldown[route_id] = time.time() + min(max(seconds, 1.0), 900.0)


def _resting(route_id: str) -> float:
    with _lock:
        return max(0.0, _cooldown.get(route_id, 0.0) - time.time())


def _retry_after(resp: requests.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        raw = resp.headers.get(header)
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            m = re.fullmatch(r"(?:(\d+)m)?(?:([\d.]+)s)?", raw.strip())  # e.g. "1m6.4s"
            if m and (m.group(1) or m.group(2)):
                return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return 20.0


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply, tolerating wrappers."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


def _post(route: Route, key: str, body: dict, timeout: float) -> requests.Response:
    return _session.post(
        f"{PROVIDERS[route.provider].base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=(6, timeout),
    )


def chat_json(task: str, messages: list[dict], *, temperature: float = 0.6, max_tokens: int = 900,
              timeout: float = 45.0) -> LLMResult:
    """Ask for a JSON object; try each route for ``task`` until one answers."""
    tried, limited, min_wait, any_key = [], 0, 0.0, False
    for route in routes(task):
        key = PROVIDERS[route.provider].key()
        if not key:
            continue
        any_key = True
        wait = _resting(route.id)
        if wait > 0:
            limited += 1
            min_wait = wait if not min_wait else min(min_wait, wait)
            tried.append(f"{route.id}: resting {wait:.0f}s")
            continue
        base = {"model": route.model, "messages": messages, "temperature": temperature}
        full = {**base, "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"}, **route.extra}
        try:
            resp = _post(route, key, full, timeout)
            if resp.status_code == 400:
                # A provider rejected an optional parameter: retry with the bare minimum.
                log.warning("%s rejected optional params: %s", route.id, resp.text[:200])
                resp = _post(route, key, {**base, "max_tokens": max_tokens}, timeout)
            if resp.status_code == 429:
                wait = _retry_after(resp)
                _rest(route.id, wait)
                limited += 1
                min_wait = wait if not min_wait else min(min_wait, wait)
                tried.append(f"{route.id}: rate limited")
                continue
            if resp.status_code in (401, 403):
                _rest(route.id, 600)
                tried.append(f"{route.id}: key rejected ({resp.status_code})")
                continue
            if resp.status_code == 404:
                _rest(route.id, 900)
                tried.append(f"{route.id}: model not found")
                continue
            if resp.status_code >= 400:
                tried.append(f"{route.id}: HTTP {resp.status_code}")
                continue
            payload = resp.json()
            content = payload["choices"][0]["message"].get("content") or ""
            data = extract_json(content)
            if data is None:
                tried.append(f"{route.id}: reply was not JSON")
                continue
            return LLMResult(data=data, model=route.id, tokens=int((payload.get("usage") or {}).get("total_tokens") or 0))
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            tried.append(f"{route.id}: {type(exc).__name__}")
            continue
    if not any_key:
        raise LLMUnavailable("No API key configured. Add GROQ_API_KEY to .streamlit/secrets.toml.")
    log.error("all LLM routes failed for %s: %s", task, "; ".join(tried))
    all_limited = bool(tried) and limited == len(tried)
    raise LLMUnavailable("; ".join(tried), rate_limited=all_limited, wait=min_wait)
