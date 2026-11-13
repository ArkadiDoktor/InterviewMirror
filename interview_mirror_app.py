"""InterviewMirror - a realistic Hebrew job-interview simulator.

Run:  streamlit run interview_mirror_app.py

The screen flow is setup -> interview room -> report. The logic lives in the
``im`` package; this file only draws the three screens.
"""
from __future__ import annotations

import base64
import re
import time
from difflib import SequenceMatcher
from html import escape

import streamlit as st

from im import admin, avatar, report, speech, storage, ui
from im.config import PROVIDERS, has_llm_key, secret
from im.engine import Interview, InterviewEngine, question_part
from im.llm import LLMUnavailable
from im.personas import LENGTHS, LEVELS, PERSONAS

st.set_page_config(page_title="InterviewMirror", page_icon="🪞", layout="wide")
ui.inject_css()

ss = st.session_state
ss.setdefault("stage", "setup")
ss.setdefault("persona", "friendly")
engine = InterviewEngine()


# ------------------------------------------------------------------ helpers
def tts_engines() -> list[str]:
    """Voice engines for a new interview, best first."""
    custom = secret("TTS_ENGINES")
    if custom:
        return [e.strip() for e in custom.split(",") if e.strip() in speech.ENGINES]
    return (["gemini"] if PROVIDERS["gemini"].key() else []) + ["edge", "gtts"]


def speak(iv: Interview, text: str) -> None:
    """Prepare the interviewer's voice for the avatar. The engine is sticky per interview:
    once a better engine fails it is not tried again, so the voice never switches back and forth."""
    engines = ss.get("tts_engines") or tts_engines()
    result = speech.synthesize(text, iv.persona.voice, engines)
    used = result.engine.split(":")[0] if result else "browser"
    # Drop Gemini for the rest of the interview only when it is out for long (daily quota), so a brief
    # per-minute limit costs one sentence in another voice, not the whole interview.
    if used != "gemini" and "gemini" in engines and speech.gemini_voice_out():
        ss.tts_engines = [e for e in engines if e != "gemini"]
    count("tts", used)
    ss.voice = {"turn": len(iv.turns), "audio": result.audio if result else None, "mime": result.mime if result else "",
                "engine": result.engine if result else "browser", "text": text, "sent": False}


def count(group: str, key: str) -> None:
    """Per-interview usage counters, saved with the session for the statistics page."""
    usage = ss.setdefault("usage", {})
    usage.setdefault(group, {})
    usage[group][key] = usage[group].get(key, 0) + 1


def vocabulary(iv: Interview) -> list[str]:
    """Latin-script terms the candidate is likely to say (React, SQL, Full Stack ...)."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]{1,30}", " ".join((iv.role, iv.job_desc, iv.cv)))
    return list(dict.fromkeys(words))[:40]


def unavailable_message(exc: LLMUnavailable) -> str:
    if exc.rate_limited:
        wait = f" (בערך {int(exc.wait) + 1} שניות)" if exc.wait else ""
        return f"המכסה החינמית של המודל מוצתה לרגע{wait}. התשובה שלך נשמרה – אפשר לשלוח אותה שוב."
    return "המראיין לא זמין כרגע בגלל תקלת תקשורת עם המודל. התשובה שלך נשמרה – אפשר לשלוח אותה שוב."


def go(stage: str) -> None:
    ss.stage = stage
    st.rerun()


@st.cache_data(show_spinner=False)
def photo_uri(key: str) -> str:
    with open(avatar.photo_path(PERSONAS[key]), "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


# -------------------------------------------------------------------- setup
def setup_screen() -> None:
    ui.brand()
    st.html('<h1 class="im-h1">ראיון עבודה, כמו שהוא באמת</h1>'
            '<p class="im-lede">מראיין שמקשיב לתשובות, מקשה כשצריך ולא נתקע על אותה שאלה. '
            'בסוף מחכה סיכום מפורט: מה עבד, מה פחות, ואיך לענות טוב יותר בפעם הבאה.</p>')

    if not has_llm_key():
        st.error("חסר מפתח API. יש להוסיף GROQ_API_KEY לקובץ ‎.streamlit/secrets.toml (מקומית) "
                 "או להגדרות ה-Secrets ב-Streamlit Cloud. המפתח חינמי: console.groq.com")

    ui.h2("מי יראיין אותך?")
    for col, p in zip(st.columns(3, gap="medium"), PERSONAS.values()):
        chosen = ss.persona == p.key
        with col, st.container(key=f"pc-{p.key}-{'on' if chosen else 'off'}"):
            st.html(f'<div class="im-pc"><img src="{photo_uri(p.key)}" alt=""><div><b>{escape(p.name)}</b>'
                    f'<span>{escape(p.title)}</span></div></div>'
                    f'<p class="im-pc-text">{escape(p.card)}</p>')
            if st.button("נבחר" if chosen else "בחירה", key=f"pick-{p.key}", type="primary" if chosen else "secondary",
                         use_container_width=True) and not chosen:
                ss.persona = p.key
                st.rerun()

    ui.h2("על מה הראיון?")
    c1, c2 = st.columns([3, 2], gap="medium")
    role = c1.text_input("התפקיד", placeholder="למשל: מפתח/ת Full Stack, אנליסט/ית נתונים, מנהל/ת שיווק", key="f_role")
    level = c2.selectbox("רמת ניסיון", list(LEVELS), index=1, key="f_level")
    c3, c4, c5 = st.columns(3, gap="medium")
    length = c3.segmented_control("אורך הראיון", list(LENGTHS), default="רגיל", key="f_len",
                                  help="קצר: 5 שאלות. רגיל: 8. מעמיק: 12.")
    gender = c4.segmented_control("איך לפנות אליך?", ["בלשון זכר", "בלשון נקבה"], default="בלשון זכר", key="f_gender")
    mode = c5.segmented_control("משוב", ["בסוף הראיון", "אחרי כל תשובה"], default="בסוף הראיון", key="f_mode",
                                help="״בסוף הראיון״ מדמה ראיון אמיתי. ״אחרי כל תשובה״ מתאים לאימון.")

    with st.expander("התאמה אישית – לא חובה"):
        st.html('<p class="im-note">ככל שהמראיין יודע יותר, השאלות יהיו קרובות יותר לראיון האמיתי שמחכה לך.</p>')
        company = st.text_input("החברה", placeholder="שם החברה ומה היא עושה, במשפט", key="f_company")
        job_desc = st.text_area("תיאור המשרה", placeholder="אפשר להדביק כאן את הדרישות ממודעת הדרושים", height=110, key="f_jd")
        cv = st.text_area("עיקרי קורות החיים", placeholder="תפקידים קודמים, השכלה, פרויקטים בולטים", height=110, key="f_cv")

    problem = st.empty()          # errors appear right above the button, where the eye already is
    if st.button("התחלת הראיון", type="primary", use_container_width=True):
        if not (role or "").strip():
            problem.error("צריך למלא את שם התפקיד כדי שהמראיין ידע על מה לשאול.")
            return
        ss.tts_engines = tts_engines()
        ss.usage = {}
        iv = engine.create(
            persona_key=ss.persona, role=role, level=level, gender="f" if gender == "בלשון נקבה" else "m",
            n_questions=LENGTHS.get(length or "רגיל", 8), company=company, job_desc=job_desc, cv=cv,
            coach=(mode == "אחרי כל תשובה"))
        try:
            with st.spinner(f"{iv.persona.name} נכנס לחדר…"):
                opening = engine.start(iv)
                ss.iv = iv
                speak(iv, opening)
        except LLMUnavailable as exc:
            problem.error(unavailable_message(exc).replace("התשובה שלך נשמרה – אפשר לשלוח אותה שוב.", "אפשר לנסות שוב בעוד רגע."))
            return
        ss.report = None
        ss.pending = None
        ss.draft = ss.voice_draft = None
        storage.save_session_start(iv)
        go("interview")


# ---------------------------------------------------------------- interview
def take_answer(iv: Interview, text: str, method: str, box, echo: bool = True) -> None:
    """Show the candidate's words at once, get the interviewer's reply, rerun."""
    with box:
        if echo:
            with st.chat_message("user", avatar="🧑"):
                st.write(text)
        with st.chat_message("assistant", avatar=avatar.photo_path(iv.persona)):
            ui.typing()
    try:
        turn = engine.respond(iv, text, method)
    except LLMUnavailable as exc:
        count("events", "model_busy")
        ss.pending = {"text": text, "method": method, "error": unavailable_message(exc)}
        st.rerun()
    ss.pending = None
    count("answers", method)
    storage.save_turn(iv, turn)
    speak(iv, turn.reply)
    st.rerun()


def interview_screen() -> None:
    iv: Interview = ss.iv
    p = iv.persona
    voice = ss.get("voice") or {}
    left, right = st.columns([5, 7], gap="large")

    with left:
        fresh = not voice.get("sent")                 # the audio travels to the browser once per turn
        avatar.render(p, turn=voice.get("turn"), audio=voice.get("audio") if fresh else None,
                      mime=voice.get("mime") or "audio/mpeg", text=voice.get("text", ""),
                      browser_voice=voice.get("engine") == "browser", live=iv.active,
                      started=iv.started_at, ended=iv.ended_at)
        if voice:
            voice["sent"] = True
        if iv.phase == "wrap":
            ui.progress("שאלות אחרונות", "הזמן שלך לשאול", 1.0, p.accent)
        elif iv.active:
            ui.progress(f"שאלה {iv.main_no} מתוך {iv.n_questions}", p.label, (iv.main_no - 1) / iv.n_questions, p.accent)
        if iv.active:
            if st.button("סיום הראיון", use_container_width=True, help="אפשר לעצור בכל רגע ולקבל סיכום על מה שנאמר עד כה"):
                engine.finish(iv, "user_ended")
                go("report")
        else:
            st.info(report.END_REASONS.get(iv.end_reason, "הראיון הסתיים") + ".")
            if st.button("לסיכום הראיון", type="primary", use_container_width=True):
                go("report")

    with right:
        box = st.container(height=520, key="room-chat", autoscroll=True)
        with box:
            for m in iv.transcript():
                if m["role"] == "assistant":
                    with st.chat_message("assistant", avatar=avatar.photo_path(p)):
                        st.write(m["content"])
                else:
                    with st.chat_message("user", avatar="🧑"):
                        st.write(m["content"])
                    if iv.coach and m["turn"].eval:
                        ui.feedback_card(m["turn"].eval)
            if ss.get("pending") and iv.active:
                with st.chat_message("user", avatar="🧑"):
                    st.write(ss.pending["text"])

        if not iv.active:
            return
        pending = ss.get("pending")
        if pending:
            st.warning(pending["error"])
            if st.button("שליחה חוזרת של התשובה", type="primary"):
                take_answer(iv, pending["text"], pending["method"], box, echo=False)
            return

        draft = ss.get("draft")
        if draft:                                      # a fresh transcript goes into the box for checking
            ss["answer"] = draft["text"]
            ss.voice_draft, ss.draft = draft, None
        if ss.get("voice_draft"):
            st.caption("זה מה שהבנתי מההקלטה. אפשר לתקן ולשלוח ב-Enter, או להקליט שוב.")
        sent = st.chat_input("כתיבת תשובה, או לחיצה על המיקרופון כדי לענות בקול", accept_audio=True,
                             key="answer", submit_mode="disable")
        if not sent:
            return
        text = (sent.text or "").strip()
        if not text and sent.audio is not None:
            ss.voice_draft = None
            audio = sent.audio.getvalue()
            stats = speech.audio_stats(audio)
            ss.last_audio, ss.last_stats = audio, stats
            if stats and stats.verdict != "ok":
                count("mic", stats.verdict)
                st.warning(stats.message())
                if stats.verdict == "silent":
                    return
            try:
                with st.spinner("מתמלל את התשובה…"):
                    result = speech.transcribe(audio, hint=question_part(iv.last_interviewer_line),
                                               vocabulary=vocabulary(iv))
            except speech.SpeechError as exc:
                st.warning(str(exc))
                return
            ss.last_stt = result.engine
            count("stt", result.engine)
            if not result.text:
                st.warning("לא נשמע דיבור ברור בהקלטה. כדאי לבדוק שהמיקרופון הנכון פעיל ולהקליט שוב.")
                return
            ss.draft = {"text": result.text, "engine": result.engine}
            st.rerun()
        if text:
            spoken = ss.get("voice_draft")
            method = "voice" if spoken and SequenceMatcher(None, text, spoken["text"]).ratio() > 0.5 else "text"
            ss.voice_draft = None
            take_answer(iv, text, method, box)


def diagnostics() -> None:
    """Open the app with ?debug=1 to see which engines are in use and to test the microphone."""
    if st.query_params.get("debug") != "1":
        return
    iv = ss.get("iv")
    with st.expander("אבחון", expanded=True):
        voice = ss.get("voice") or {}
        st.write({
            "קול המראיין": voice.get("engine", "-"),
            "מנועי קול זמינים בראיון": ss.get("tts_engines"),
            "תמלול אחרון": ss.get("last_stt", "-"),
            "מפתח Gemini": bool(PROVIDERS["gemini"].key()),
            "מפתח Groq": bool(PROVIDERS["groq"].key()),
        })
        audio, stats = ss.get("last_audio"), ss.get("last_stats")
        if audio:
            st.markdown("**ההקלטה האחרונה שלך** – כדאי להאזין: אם היא נשמעת ברורה, הבעיה במנוע התמלול ולא במיקרופון.")
            st.audio(audio, format="audio/wav")
            if stats:
                st.write({"משך (שניות)": stats.seconds, "עוצמת דיבור (dBFS, תקין: ‎-30 עד ‎-6)": stats.level_db,
                          "שיא": stats.peak, "דגימות חתוכות": stats.clipped,
                          "הערכה": {"ok": "תקין", "quiet": "שקט", "very_quiet": "שקט מאוד", "distorted": "מעוות",
                                    "silent": "שקט מוחלט"}[stats.verdict]})
            if st.button("השוואת מנועי תמלול על ההקלטה הזו"):
                hint = question_part(iv.last_interviewer_line) if iv else ""
                for name, eng in (("Gemini", "gemini"), ("Whisper (Groq)", "whisper")):
                    try:
                        with st.spinner(f"מתמלל עם {name}…"):
                            st.markdown(f"**{name}:** {escape(speech.transcribe_with(eng, audio, hint=hint, vocabulary=vocabulary(iv) if iv else []))}")
                    except speech.SpeechError as exc:
                        st.markdown(f"**{name}:** לא זמין – {escape(str(exc))}")
        else:
            st.caption("אחרי הקלטה ראשונה יופיעו כאן ההקלטה, מדדי עוצמה וכפתור להשוואת מנועי תמלול.")
        errors = speech.recent_errors()
        if errors:
            st.markdown("**תקלות אחרונות בשירותי הקול**")
            st.code("\n".join(f"{t_} {eng}: {msg}" for t_, eng, msg in errors[-10:]), language=None)


# ------------------------------------------------------------------- report
def report_screen() -> None:
    iv: Interview = ss.iv
    p = iv.persona
    ui.brand()
    if not iv.turns:
        st.html('<h1 class="im-h1">הראיון הסתיים לפני התשובה הראשונה</h1>'
                '<p class="im-lede">אין עדיין על מה לתת משוב. אפשר להתחיל ראיון חדש.</p>')
        if st.button("ראיון חדש", type="primary"):
            go("setup")
        return

    if not ss.get("report"):
        with st.spinner("מכין את סיכום הראיון…"):
            ss.report = report.build_report(iv)
            storage.save_session(iv, ss.report, ss.get("usage"))
    rep = ss.report
    color = {"advance": ui.GOOD, "borderline": ui.MID, "reject": ui.LOW}[rep["verdict"]]
    minutes = max(1, round(((iv.ended_at or time.time()) - iv.started_at) / 60))
    meta = (f"{iv.role}, מול {p.name} ({p.label}). {minutes} דקות. "
            f"{report.END_REASONS.get(iv.end_reason, '')}.")

    st.html(f'<h1 class="im-h1" style="max-width:26ch">{escape(rep["headline"])}</h1>')
    ui.score_ring(rep["overall"], report.VERDICTS[rep["verdict"]], color, rep["summary"], meta)
    if rep.get("source") == "fallback":
        st.caption("הסיכום המלא לא היה זמין כרגע (מכסת המודל), ולכן מוצג סיכום מקוצר על בסיס הציונים מהראיון.")

    a, b = st.columns(2, gap="large")
    with a:
        ui.h2("מדדים")
        ui.bars(rep["competencies"])
    with b:
        ui.h2("מהלך הראיון")
        if len(iv.scores) >= 2:
            ui.score_chart(iv.scores)
        else:
            st.html('<p class="im-note">אין מספיק תשובות מדורגות כדי לצייר מגמה.</p>')

    a, b = st.columns(2, gap="large")
    with a:
        ui.h2("חוזקות")
        ui.bullet_list(rep["strengths"], ui.GOOD)
    with b:
        ui.h2("מה לשפר")
        ui.bullet_list(rep["improvements"], ui.LOW)

    by_n = {q["n"]: q for q in rep["questions"]}
    scored = report.scored_turns(iv)
    if scored:
        ui.h2("מעבר על התשובות")
        for t in scored:
            q = by_n.get(t.n, {})
            title = question_part(t.question)
            title = title if len(title) <= 90 else title[:88] + "…"
            with st.expander(f"{t.eval['score']}/10 – {title}"):
                rows = [f'<p><b>השאלה:</b> {escape(t.question)}</p>', f'<p class="a"><b>התשובה שלך:</b> {escape(t.answer)}</p>']
                if q.get("feedback"):
                    rows.append(f'<p><b>משוב:</b> {escape(q["feedback"])}</p>')
                if q.get("better"):
                    rows.append(f'<p><b>איך לחזק:</b> {escape(q["better"])}</p>')
                st.html(f'<div class="im-qa">{"".join(rows)}</div>')

    ui.h2("תרגול לשבוע הקרוב")
    ui.bullet_list(rep["practice"], ui.INK)

    st.write("")
    a, b = st.columns(2, gap="medium")
    a.download_button("הורדת הסיכום", report.to_markdown(iv, rep), file_name="interview-summary.md",
                      mime="text/markdown", use_container_width=True)
    if b.button("ראיון חדש", type="primary", use_container_width=True):
        go("setup")


if st.query_params.get("admin") == "1":
    admin.render()
elif ss.stage == "interview" and ss.get("iv"):
    interview_screen()
    diagnostics()
elif ss.stage == "report" and ss.get("iv"):
    report_screen()
else:
    setup_screen()
