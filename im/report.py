"""End-of-interview report.

One model call turns the transcript and the per-answer evaluations into a
structured report. If no model is available the report is assembled from the
evaluations that were already collected during the interview, so the candidate
always gets something useful.
"""
from __future__ import annotations

import logging
from statistics import mean, pstdev

from . import prompts
from .engine import Interview
from .llm import chat_json
from .personas import LEVELS

log = logging.getLogger("interviewmirror.report")

VERDICTS = {"advance": "ממשיכים לשלב הבא", "borderline": "על הגבול", "reject": "לא ממשיכים הפעם"}
END_REASONS = {
    "completed": "הראיון הושלם",
    "terminated": "המראיין סיים את הראיון מוקדם",
    "candidate_stopped": "ביקשת לסיים את הראיון",
    "user_ended": "סיימת את הראיון לפני סופו",
}


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _strs(items, limit=4, width=400) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(x).strip()[:width] for x in items if str(x).strip()][:limit]


def scored_turns(iv: Interview):
    return [t for t in iv.turns if t.eval]


def _facts(iv: Interview) -> str:
    scored = scored_turns(iv)
    unanswered = len({t.main_no for t in iv.turns if t.topic != "wrap"} - {t.main_no for t in scored})
    disruptive = sum(1 for t in iv.turns if t.kind in prompts.DISRUPTIVE)
    lines = [
        f"Planned main questions: {iv.n_questions}. Reached: {iv.main_no}. Main questions left without a real answer: {unanswered}.",
        f"Disruptive turns (jokes, off-topic, refusals, hostility): {disruptive}.",
        f"How it ended: {iv.end_reason or 'completed'}.",
    ]
    if scored:
        lines.append(f"Interviewer's private scores per answer (1-10): {[t.eval['score'] for t in scored]}")
    return "\n".join(lines)


def _transcript(iv: Interview, budget: int = 9000) -> str:
    rows = [f"INTERVIEWER (opening): {iv.opening}"]
    for t in iv.turns:
        tag = f"SCORED score={t.eval['score']}" if t.eval else f"not scored, kind={t.kind}"
        rows.append(f"--- turn {t.n} [{tag}] ---\nINTERVIEWER asked: {t.question}\nCANDIDATE: {t.answer[:900]}")
    rows.append(f"INTERVIEWER (last words): {iv.last_interviewer_line}")
    text = "\n".join(rows)
    return text if len(text) <= budget else text[: budget // 2] + "\n[...]\n" + text[-budget // 2 :]


def fallback_report(iv: Interview) -> dict:
    scored = scored_turns(iv)
    scores = [t.eval["score"] for t in scored]
    asked = max(1, len({t.main_no for t in iv.turns if t.topic != "wrap"}))
    answered = len({t.main_no for t in scored})
    coverage = answered / asked
    avg = mean(scores) if scores else 0
    overall = round(avg * 10 * (0.5 + 0.5 * coverage))
    if iv.end_reason == "terminated":
        overall = min(overall, 25)
    verdict = "advance" if overall >= 75 else "borderline" if overall >= 55 else "reject"
    spread = pstdev(scores) if len(scores) > 1 else 0
    comps = [
        {"name": "איכות התשובות", "score": _clamp(avg, 1, 10, 1), "comment": "ממוצע הציונים שנתן המראיין לתשובות."},
        {"name": "עומק ופירוט", "score": _clamp(10 * sum(s >= 7 for s in scores) / max(1, len(scores)), 1, 10, 1),
         "comment": "שיעור התשובות שכללו דוגמה קונקרטית ופירוט."},
        {"name": "עקביות", "score": _clamp(10 - 2 * spread, 1, 10, 5), "comment": "עד כמה הרמה נשמרה לאורך הראיון."},
        {"name": "מענה לשאלות", "score": _clamp(10 * coverage, 1, 10, 1), "comment": "כמה מהשאלות קיבלו תשובה עניינית."},
        {"name": "התנהלות בראיון", "score": _clamp(10 - 3 * iv.strikes, 1, 10, 10), "comment": "רצינות ושיתוף פעולה עם המראיין."},
    ]
    best = sorted(scored, key=lambda t: -t.eval["score"])
    worst = sorted(scored, key=lambda t: t.eval["score"])
    return {
        "overall": overall,
        "verdict": verdict,
        "headline": "סיכום אוטומטי על בסיס הציונים שניתנו במהלך הראיון.",
        "summary": (f"ענית באופן ענייני על {answered} מתוך {asked} שאלות, בציון ממוצע {avg:.1f} מתוך 10. "
                    f"{END_REASONS.get(iv.end_reason, '')}."),
        "competencies": comps,
        "strengths": [t.eval["strength"] for t in best[:3] if t.eval.get("strength")] or ["השלמת את הראיון."],
        "improvements": [t.eval["improve"] for t in worst[:3] if t.eval.get("improve")] or ["כדאי לתת תשובות מפורטות יותר, עם דוגמאות."],
        "questions": [{"n": t.n, "feedback": t.eval.get("improve", ""), "better": t.eval.get("tip", "")} for t in scored],
        "practice": ["לבחור שלוש שאלות מהראיון ולענות עליהן שוב בקול, במבנה: מצב, פעולה שלי, תוצאה."],
        "source": "fallback",
    }


def build_report(iv: Interview, llm=chat_json) -> dict:
    """Always returns a complete report dict."""
    base = fallback_report(iv)
    if not iv.turns:
        return base
    try:
        res = llm("report", prompts.report_prompt(persona=iv.persona, role=iv.role, level=LEVELS.get(iv.level, iv.level),
                                                  transcript=_transcript(iv), facts=_facts(iv)),
                  temperature=0.3, max_tokens=2200, timeout=75.0)
        raw = res.data
    except Exception as exc:  # noqa: BLE001
        log.warning("report model unavailable, using fallback: %s", exc)
        return base

    overall = _clamp(raw.get("overall"), 0, 100, base["overall"])
    if iv.end_reason == "terminated":
        overall = min(overall, 25)
    verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else (
        "advance" if overall >= 75 else "borderline" if overall >= 55 else "reject")
    comps = []
    for c in raw.get("competencies") or []:
        if isinstance(c, dict) and str(c.get("name", "")).strip():
            comps.append({"name": str(c["name"]).strip()[:40], "score": _clamp(c.get("score"), 1, 10, 5),
                          "comment": str(c.get("comment", "")).strip()[:300]})
    valid = {t.n for t in scored_turns(iv)}
    questions = []
    for q in raw.get("questions") or []:
        if isinstance(q, dict) and _clamp(q.get("n"), 0, 10_000, -1) in valid:
            questions.append({"n": int(q["n"]), "feedback": str(q.get("feedback", "")).strip()[:500],
                              "better": str(q.get("better", "")).strip()[:500]})
    seen = {q["n"] for q in questions}
    questions += [q for q in base["questions"] if q["n"] not in seen]
    return {
        "overall": overall,
        "verdict": verdict,
        "headline": str(raw.get("headline") or base["headline"]).strip()[:300],
        "summary": str(raw.get("summary") or base["summary"]).strip()[:1200],
        "competencies": comps[:5] or base["competencies"],
        "strengths": _strs(raw.get("strengths")) or base["strengths"],
        "improvements": _strs(raw.get("improvements")) or base["improvements"],
        "questions": sorted(questions, key=lambda q: q["n"]),
        "practice": _strs(raw.get("practice"), 3) or base["practice"],
        "source": res.model,
    }


def to_markdown(iv: Interview, rep: dict) -> str:
    """Plain-text version the candidate can download and keep."""
    p = iv.persona
    out = [
        "# InterviewMirror – סיכום ראיון", "",
        f"**תפקיד:** {iv.role}  ", f"**מראיין:** {p.name}, {p.title} ({p.label})  ",
        f"**ציון כולל:** {rep['overall']}/100 – {VERDICTS[rep['verdict']]}  ",
        f"**סיום:** {END_REASONS.get(iv.end_reason, '')}", "",
        f"> {rep['headline']}", "", rep["summary"], "", "## מדדים",
    ]
    out += [f"- **{c['name']}** – {c['score']}/10. {c['comment']}" for c in rep["competencies"]]
    out += ["", "## חוזקות"] + [f"- {s}" for s in rep["strengths"]]
    out += ["", "## מה לשפר"] + [f"- {s}" for s in rep["improvements"]]
    out += ["", "## מעבר על התשובות"]
    by_n = {q["n"]: q for q in rep["questions"]}
    for t in iv.turns:
        if not t.eval:
            continue
        q = by_n.get(t.n, {})
        out += ["", f"### {t.question}", f"**התשובה שלך ({t.eval['score']}/10):** {t.answer}", ""]
        if q.get("feedback"):
            out.append(f"**משוב:** {q['feedback']}")
        if q.get("better"):
            out.append(f"**איך לחזק:** {q['better']}")
    out += ["", "## תרגול לשבוע הקרוב"] + [f"- {s}" for s in rep["practice"]]
    return "\n".join(out) + "\n"
