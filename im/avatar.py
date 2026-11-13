"""The talking avatar, as a Streamlit v2 component (no iframe, no server, no cost).

``render`` mounts a "video call" tile that animates the persona's still photo
in the browser. Passing a new ``turn`` number makes it speak the given audio.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

import streamlit as st

from .personas import Persona

ASSETS = Path(__file__).parent / "assets"


@st.cache_resource
def _component():
    tris = json.loads((ASSETS / "face_topology.json").read_text())["tris"]
    js = (ASSETS / "avatar.js").read_text(encoding="utf-8").replace("__FACE_TRIS__", json.dumps(tris, separators=(",", ":")))
    return st.components.v2.component(
        "interview_mirror_avatar",
        html=(ASSETS / "avatar.html").read_text(encoding="utf-8"),
        css=(ASSETS / "avatar.css").read_text(encoding="utf-8"),
        js=js,
    )


@lru_cache(maxsize=8)
def _face(key: str) -> tuple[str, dict]:
    photo = base64.b64encode((ASSETS / f"{key}.jpg").read_bytes()).decode()
    mesh = json.loads((ASSETS / f"{key}.mesh.json").read_text())
    return photo, mesh


def photo_path(persona: Persona) -> str:
    return str(ASSETS / f"{persona.key}.jpg")


def render(persona: Persona, *, turn: int | None = None, audio: bytes | None = None, mime: str = "audio/mpeg",
           text: str = "", live: bool = False, started: float = 0.0, ended: float = 0.0, key: str = "avatar") -> None:
    photo, mesh = _face(persona.key)
    _component()(
        key=key,
        data={
            "persona": persona.key,
            "name": persona.name,
            "title": persona.title,
            "accent": persona.accent,
            "mood": persona.mood,
            "photo": photo,
            "mesh": mesh,
            "turn": turn,
            "audio": base64.b64encode(audio).decode() if audio else "",
            "mime": mime,
            "text": text,
            "live": live,
            "started": started,
            "ended": ended,
        },
    )
