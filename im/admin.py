"""Owner-only statistics page: open the app with ?admin=1.

Protected by ADMIN_PASSWORD from secrets. Shows only aggregates and interview
metadata - never what candidates answered.
"""
from __future__ import annotations

import hmac
from collections import Counter
from datetime import datetime, timezone

import streamlit as st

from . import storage, ui
from .config import secret
from .personas import PERSONAS

END_LABELS = {"completed": "הושלם", "terminated": "המראיין סיים", "candidate_stopped": "המועמד ביקש לעצור",
              "user_ended": "נעצר בכפתור", "": "ננטש באמצע"}


LABELS = {"text": "הקלדה", "voice": "קול", "gemini": "Gemini", "edge": "Edge", "gtts": "Google Translate",
          "browser": "קול הדפדפן", "whisper": "Whisper", "quiet": "שקטה", "very_quiet": "שקטה מאוד",
          "distorted": "מעוותת", "silent": "ללא קול", "fake": "בדיקה"}


def _day(ts) -> str:
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).strftime("%d.%m")
    return "?"


def _sort_key(day: str) -> tuple:
    try:
        d, m = day.split(".")
        return (int(m), int(d))
    except ValueError:
        return (99, 99)


def _table(shares: dict[str, str], title: str) -> None:
    if not shares:
        st.caption(f"{title}: אין נתונים")
        return
    st.table({title: [LABELS.get(k, k) for k in shares], "כמות": list(shares.values())})


def _share(counter: Counter) -> dict[str, str]:
    total = sum(counter.values()) or 1
    return {k: f"{v} ({round(100 * v / total)}%)" for k, v in counter.most_common()}


def compute_stats(rows: list[dict]) -> dict:
    """Pure function, unit-tested: turns session documents into the numbers the page shows."""
    finished = [r for r in rows if r.get("status") == "finished"]
    per_day = Counter(_day(r.get("started") or r.get("timestamp")) for r in rows)
    usage = {"tts": Counter(), "stt": Counter(), "answers": Counter(), "mic": Counter(), "events": Counter()}
    for r in finished:
        for group, counter in usage.items():
            counter.update((r.get("usage") or {}).get(group, {}))
    scores = [r["overall"] for r in finished if isinstance(r.get("overall"), (int, float))]
    durations = [r["duration_sec"] / 60 for r in finished if r.get("duration_sec")]
    ends = Counter(END_LABELS.get(r.get("end_reason") or "", r.get("end_reason")) for r in finished)
    if len(rows) > len(finished):
        ends[END_LABELS[""]] = len(rows) - len(finished)
    by_persona = {}
    for key, p in PERSONAS.items():
        mine = [r for r in rows if r.get("persona") == key or r.get("interviewer_type") == p.label]
        done = [r["overall"] for r in mine if r.get("status") == "finished" and isinstance(r.get("overall"), (int, float))]
        by_persona[p.label] = {"התחילו": len(mine), "ציון ממוצע": round(sum(done) / len(done)) if done else "-"}
    return {
        "started": len(rows),
        "finished": len(finished),
        "completion": round(100 * len(finished) / len(rows)) if rows else 0,
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "avg_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "per_day": dict(sorted(per_day.items(), key=lambda kv: _sort_key(kv[0]))),
        "by_persona": by_persona,
        "end_reasons": _share(ends),
        "roles": Counter((r.get("job_role") or "").strip() for r in rows if r.get("job_role")).most_common(10),
        **{k: _share(v) for k, v in usage.items()},
        "model_busy": usage["events"].get("model_busy", 0),
    }


def _login() -> bool:
    expected = secret("ADMIN_PASSWORD")
    if not expected:
        st.info("כדי לפתוח את דף הסטטיסטיקה, יש להוסיף ADMIN_PASSWORD להגדרות ה-Secrets של האפליקציה.")
        return False
    if st.session_state.get("admin_ok"):
        return True
    pw = st.text_input("סיסמה", type="password")
    if pw:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state.admin_ok = True
            st.rerun()
        st.error("סיסמה שגויה.")
    return False


@st.cache_data(ttl=300, show_spinner="טוען נתונים…")
def _load(days: int):
    return storage.load_sessions(days)


def render() -> None:
    ui.brand()
    st.html('<h1 class="im-h1">סטטיסטיקה</h1>')
    if not _login():
        return
    days = st.segmented_control("תקופה", [7, 30, 90], default=30, format_func=lambda d: f"{d} ימים") or 30
    rows = _load(days)
    if rows is None:
        st.warning("אין חיבור ל-Firestore, ולכן אין נתונים. בלי חיבור כזה האפליקציה לא שומרת ראיונות.")
        return
    if not rows:
        st.info("עדיין אין ראיונות בתקופה הזו.")
        return
    s = compute_stats(rows)
    c = st.columns(4)
    c[0].metric("ראיונות שהתחילו", s["started"])
    c[1].metric(f'הגיעו לסיכום ({s["finished"]})', f'{s["completion"]}%')
    c[2].metric("ציון ממוצע", s["avg_score"] if s["avg_score"] is not None else "-")
    c[3].metric("משך ממוצע (דקות)", s["avg_minutes"] if s["avg_minutes"] is not None else "-")

    ui.h2("ראיונות לפי יום")
    ui.day_bars(s["per_day"])

    a, b = st.columns(2, gap="large")
    with a:
        ui.h2("לפי מראיין")
        st.table(s["by_persona"])
        ui.h2("איך ראיונות הסתיימו")
        _table(s["end_reasons"], "סיום")
    with b:
        ui.h2("תפקידים נפוצים")
        st.table({"תפקיד": [r for r, _ in s["roles"]], "ראיונות": [n for _, n in s["roles"]]})
        ui.h2("תשובות: קול מול הקלדה")
        _table(s["answers"], "אופן")

    ui.h2("בריאות שירותים")
    st.caption("כמה פעמים כל מנוע שימש בפועל. ירידה בשימוש ב-Gemini לטובת Edge או Whisper אומרת שהמכסה החינמית נגמרת.")
    a, b, c = st.columns(3, gap="large")
    with a:
        _table(s["tts"], "קול המראיין")
    with b:
        _table(s["stt"], "תמלול")
    with c:
        _table(s["mic"], "הקלטות חלשות")
    st.metric("פעמים שהמודל היה עמוס (מכסה לדקה/ליום)", s["model_busy"])
    st.caption("הנתונים מתעדכנים כל 5 דקות. ראיונות שננטשו נספרים לפי זמן ההתחלה.")
