"""Settings and secrets.

Everything here works on the free tiers. Keys are read from Streamlit secrets
first and from environment variables second; nothing is ever hard-coded.

Optional overrides (secrets or env), e.g. to try another model without touching code:
    LLM_ROUTES_TURN   = "groq:openai/gpt-oss-120b, groq:qwen/qwen3.8-27b"
    LLM_ROUTES_REPORT = "gemini:gemini-3.8-flash, groq:openai/gpt-oss-120b"
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def secret(name: str, default: str | None = None) -> str | None:
    """Read a secret without crashing when no secrets file exists."""
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Provider:
    default_url: str
    key_names: tuple[str, ...]
    url_override: str = ""          # name of an optional secret that replaces the URL (proxy, tests)

    @property
    def base_url(self) -> str:
        return (secret(self.url_override) or self.default_url).rstrip("/") if self.url_override else self.default_url

    def key(self) -> str | None:
        for n in self.key_names:
            v = secret(n)
            if v and not v.startswith("YOUR_"):
                return v
        return None


# Both speak the OpenAI chat-completions dialect, so one client serves all.
PROVIDERS: dict[str, Provider] = {
    "groq": Provider("https://api.groq.com/openai/v1", ("GROQ_API_KEY",), "GROQ_BASE_URL"),
    "gemini": Provider("https://generativelanguage.googleapis.com/v1beta/openai", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "GEMINI_BASE_URL"),
}


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


# Free-tier line-up, verified November 2026. Each Groq model has its own daily
# token budget, so falling through the list multiplies the free capacity.
# Routes whose provider has no API key configured are skipped automatically.
_DEFAULT_ROUTES: dict[str, list[Route]] = {
    # every interview turn: fast, strong, generous limits
    "turn": [
        Route("groq", "openai/gpt-oss-120b", {"reasoning_effort": "low"}),
        Route("groq", "qwen/qwen3.8-27b"),
        Route("gemini", "gemini-3.5-flash-lite"),
        Route("groq", "openai/gpt-oss-20b", {"reasoning_effort": "low"}),
    ],
    # one call per interview: worth spending the scarce "best model" quota on
    "report": [
        Route("gemini", "gemini-3.8-flash"),
        Route("groq", "openai/gpt-oss-120b", {"reasoning_effort": "medium"}),
        Route("groq", "qwen/qwen3.8-27b"),
        Route("groq", "openai/gpt-oss-20b"),
    ],
}

STT_MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")


def routes(task: str) -> list[Route]:
    override = secret(f"LLM_ROUTES_{task.upper()}")
    if override:
        parsed = []
        for part in override.split(","):
            part = part.strip()
            if ":" in part:
                prov, model = part.split(":", 1)
                if prov.strip() in PROVIDERS:
                    parsed.append(Route(prov.strip(), model.strip()))
        if parsed:
            return parsed
    return list(_DEFAULT_ROUTES[task])


def has_llm_key() -> bool:
    return any(p.key() for p in PROVIDERS.values())
