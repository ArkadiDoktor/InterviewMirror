"""Optional persistence in Firebase Firestore (free Spark plan).

Storage must never break an interview: when Firestore is not configured or a
write fails, the app carries on and only logs the problem.

Collections
  interview_responses  one document per candidate turn. Same fields as v1, plus
                       a few new ones (answer_kind, topic, model ...). Firestore
                       is schemaless, so old and new documents live side by side
                       and no migration is needed.
  interview_sessions   one document per finished interview (settings + report).
"""
from __future__ import annotations

import logging

log = logging.getLogger("interviewmirror.storage")

_FIELDS = ("type", "project_id", "private_key_id", "private_key", "client_email", "client_id",
           "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url")
_db = None
_tried = False


def _client():
    global _db, _tried
    if _tried:
        return _db
    _tried = True
    try:
        import streamlit as st

        cfg = st.secrets["connections"]["firestore"]
    except Exception:
        log.info("Firestore not configured - interviews will not be saved.")
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred = {k: cfg[k] for k in _FIELDS if k in cfg}
            cred["private_key"] = cred.get("private_key", "").replace("\\n", "\n")
            firebase_admin.initialize_app(credentials.Certificate(cred))
        _db = firestore.client()
    except Exception as exc:  # noqa: BLE001
        log.error("Firestore init failed: %s: %s", type(exc).__name__, exc)
        _db = None
    return _db


def enabled() -> bool:
    return _client() is not None


def save_turn(iv, turn) -> bool:
    db = _client()
    if db is None:
        return False
    try:
        from firebase_admin import firestore

        ev = turn.eval or {}
        feedback = " | ".join(x for x in (
            f"ציון {ev['score']}/10" if ev else "", ev.get("strength", ""), ev.get("improve", "")) if x)
        db.collection("interview_responses").document().set({
            # --- v1 fields (unchanged) ---
            "interview_id": iv.interview_id,
            "turn_index": turn.n,
            "interviewer_type": iv.persona.label,
            "job_role": iv.role,
            "question": turn.question,
            "user_answer": turn.answer,
            "score": ev.get("score"),
            "ai_feedback": feedback,
            "input_method": turn.input_method,
            "timestamp": firestore.SERVER_TIMESTAMP,
            # --- new in v2 ---
            "interviewer_reply": turn.reply,
            "answer_kind": turn.kind,
            "decision": turn.decision,
            "topic": turn.topic,
            "main_question": turn.main_no,
            "tip": ev.get("tip"),
            "model": turn.model,
            "app_version": 2,
        })
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("saving turn failed: %s: %s", type(exc).__name__, exc)
        return False


def _session_base(iv) -> dict:
    return {
        "interview_id": iv.interview_id,
        "interviewer_type": iv.persona.label,
        "persona": iv.persona_key,
        "job_role": iv.role,
        "level": iv.level,
        "planned_questions": iv.n_questions,
        "coach_mode": iv.coach,
        "app_version": 2,
    }


def save_session_start(iv) -> bool:
    """Written when an interview starts, so abandoned interviews show up in the statistics."""
    db = _client()
    if db is None:
        return False
    try:
        from firebase_admin import firestore

        db.collection("interview_sessions").document(iv.interview_id).set(
            {**_session_base(iv), "status": "started", "started": firestore.SERVER_TIMESTAMP,
             "timestamp": firestore.SERVER_TIMESTAMP})
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("saving session start failed: %s: %s", type(exc).__name__, exc)
        return False


def save_session(iv, report: dict | None, usage: dict | None = None) -> bool:
    db = _client()
    if db is None:
        return False
    try:
        from firebase_admin import firestore

        db.collection("interview_sessions").document(iv.interview_id).set({
            **_session_base(iv),
            "status": "finished",
            "questions_reached": iv.main_no,
            "turns": len(iv.turns),
            "scores": iv.scores,
            "disruptions": iv.strikes,
            "end_reason": iv.end_reason,
            "duration_sec": int(max(0, (iv.ended_at or 0) - (iv.started_at or 0))),
            "overall": (report or {}).get("overall"),
            "verdict": (report or {}).get("verdict"),
            "report_model": (report or {}).get("source"),
            "usage": usage or {},
            "report": report,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("saving session failed: %s: %s", type(exc).__name__, exc)
        return False


def load_sessions(days: int = 30, limit: int = 2000) -> list[dict] | None:
    """Recent interview sessions (without the full report text) for the statistics page."""
    db = _client()
    if db is None:
        return None
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    try:
        query = db.collection("interview_sessions").where("timestamp", ">=", since).limit(limit)
        for doc in query.stream():
            d = doc.to_dict() or {}
            d.pop("report", None)
            rows.append(d)
    except Exception as exc:  # noqa: BLE001
        log.error("loading sessions failed: %s: %s", type(exc).__name__, exc)
        return None
    return rows
