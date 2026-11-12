"""The interview engine.

The language model plays the interviewer, but it does not run the interview.
This module does: it owns the agenda, counts questions, follow-ups, failed
attempts and disruptions, and tells the model each turn what is allowed next.
Whatever comes back is checked; when the model breaks a rule (repeats a
question, refuses to move on, forgets to end) it gets exactly one corrective
retry and then a deterministic fallback takes over. The interview can
therefore never get stuck in a loop, which was the main flaw of v1.

No Streamlit imports here - the engine is plain Python and unit-testable.
"""
from __future__ import annotations

import json
import random
import re
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Callable

from . import prompts
from .llm import LLMResult, chat_json
from .personas import LEVELS, PERSONAS, Persona, Topic

MAX_ANSWER_CHARS = 2500
HISTORY_EXCHANGES = 7
WRAP_MAX_TURNS = 3

ANY_QUESTIONS = {
    "friendly": "אלה היו השאלות שלי. לפני שנסיים – יש משהו שחשוב לך לשאול אותי?",
    "technical": "זה מה שרציתי לשאול. יש לך שאלות אליי?",
    "tough": "סיימתי עם השאלות שלי. יש לך שאלות? בקצרה.",
}
GOODBYE = {
    "friendly": "תודה רבה על השיחה, היה לי נעים להכיר. נחזור אליך עם תשובה בתוך כשבוע. בהצלחה!",
    "technical": "תודה על הזמן. הצוות ידון בדברים, ומשאבי אנוש יעדכנו אותך לגבי ההמשך.",
    "tough": "זהו מבחינתי. יש לי עוד מועמדים לראות, נעדכן אותך. תודה.",
}

LLMFn = Callable[..., LLMResult]


@dataclass
class Turn:
    n: int
    question: str
    answer: str
    kind: str
    eval: dict | None
    topic: str
    main_no: int
    decision: str
    reply: str
    model: str = ""
    input_method: str = "text"
    corrected: bool = False


@dataclass
class Interview:
    persona_key: str
    role: str
    level: str
    gender: str = "m"
    n_questions: int = 8
    company: str = ""
    job_desc: str = ""
    cv: str = ""
    coach: bool = False
    interview_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tag: str = field(default_factory=lambda: secrets.token_hex(3))
    system: str = ""
    topics: list[str] = field(default_factory=list)   # topic keys, opener first
    phase: str = "opening"                            # opening | core | wrap | ended
    main_no: int = 0
    followups: int = 0
    attempts: int = 0
    strikes: int = 0
    good_streak: int = 0
    wrap_turns: int = 0
    opening: str = ""
    turns: list[Turn] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0
    end_reason: str = ""                              # completed | terminated | candidate_stopped | user_ended

    # -- convenience -------------------------------------------------------
    @property
    def persona(self) -> Persona:
        return PERSONAS[self.persona_key]

    @property
    def active(self) -> bool:
        return self.phase != "ended"

    @property
    def last_interviewer_line(self) -> str:
        return self.turns[-1].reply if self.turns else self.opening

    @property
    def scores(self) -> list[int]:
        return [t.eval["score"] for t in self.turns if t.eval]

    def transcript(self) -> list[dict]:
        """Visible conversation, oldest first."""
        out = [{"role": "assistant", "content": self.opening, "turn": None}] if self.opening else []
        for t in self.turns:
            out.append({"role": "user", "content": t.answer, "turn": t})
            out.append({"role": "assistant", "content": t.reply, "turn": None})
        return out

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ helpers
def _topic(p: Persona, key: str) -> Topic:
    if key == p.opener.key:
        return p.opener
    return next(t for t in p.agenda if t.key == key)


def plan_topics(p: Persona, n_questions: int, rng: random.Random | None = None) -> list[str]:
    """Opener + the persona's two signature topics + a varied pick of the rest."""
    rng = rng or random.Random()
    need = max(0, n_questions - 1)
    core, rest = list(p.agenda[:2]), list(p.agenda[2:])
    chosen = core[:need]
    extra = need - len(chosen)
    if extra > 0:
        picks = set(rng.sample(range(len(rest)), min(extra, len(rest))))
        chosen += [t for i, t in enumerate(rest) if i in picks]
    return [p.opener.key] + [t.key for t in chosen]


def clean_candidate_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("<", "‹").replace(">", "›")      # nothing the candidate types can look like a tag
    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS] + " […]"
    return text


_SPEECH_JUNK = re.compile(r"[*_#`~|\[\]{}<>]+")
_HEBREW = re.compile(r"[\u05d0-\u05ea]")


def clean_speech(text: str) -> str:
    text = _SPEECH_JUNK.sub("", str(text or ""))
    text = re.sub(r"\((?:[^)]{0,60})\)", "", text)        # stage directions like (מחייך)
    return re.sub(r"\s+", " ", text).strip()


def _norm(text: str) -> str:
    text = re.sub(r"[\u0591-\u05c7]", "", text)           # niqqud
    return " ".join(re.sub(r"[^\w\u05d0-\u05ea ]+", " ", text).lower().split())


def question_part(text: str) -> str:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if "?" in s]
    return parts[-1] if parts else text


def too_similar(new: str, previous: list[str]) -> bool:
    """True when the interviewer is about to repeat an earlier question."""
    nq, nfull = _norm(question_part(new)), _norm(new)
    if len(nq) < 14:
        return False
    for old in previous[-6:]:
        if SequenceMatcher(None, nq, _norm(question_part(old))).ratio() >= 0.82:
            return True
        if SequenceMatcher(None, nfull, _norm(old)).ratio() >= 0.86:
            return True
    return False


def _normalise(raw: dict, phase: str) -> dict:
    kind = str(raw.get("kind", "")).strip().lower()
    if kind not in prompts.KINDS:
        kind = "answer"
    decision = str(raw.get("decision", "")).strip().lower()
    if decision not in prompts.DECISIONS:
        decision = "next_topic" if kind in prompts.SCORED else "stay"
    ev = raw.get("eval")
    if kind in prompts.SCORED and phase == "core" and isinstance(ev, dict):
        try:
            score = int(round(float(ev.get("score"))))
        except (TypeError, ValueError):
            score = None
        if score is None:
            ev = None
        else:
            ev = {
                "score": max(1, min(10, score)),
                "strength": clean_speech(ev.get("strength", ""))[:300],
                "improve": clean_speech(ev.get("improve", ""))[:300],
                "tip": clean_speech(ev.get("tip", ""))[:300],
            }
    else:
        ev = None
    return {
        "kind": kind,
        "decision": decision,
        "eval": ev,
        "say": clean_speech(raw.get("say", "")),
        "note": clean_speech(raw.get("note", ""))[:160],
    }


# ------------------------------------------------------------------- engine
class InterviewEngine:
    def __init__(self, llm: LLMFn = chat_json, rng: random.Random | None = None):
        self._llm = llm
        self._rng = rng or random.Random()

    # -- lifecycle ---------------------------------------------------------
    def create(self, *, persona_key: str, role: str, level: str, gender: str = "m", n_questions: int = 8,
               company: str = "", job_desc: str = "", cv: str = "", coach: bool = False) -> Interview:
        p = PERSONAS[persona_key]
        iv = Interview(persona_key=persona_key, role=role.strip()[:120], level=level, gender=gender,
                       n_questions=n_questions, company=company.strip()[:300], job_desc=job_desc.strip()[:1500],
                       cv=cv.strip()[:1500], coach=coach)
        iv.topics = plan_topics(p, n_questions, self._rng)
        iv.n_questions = len(iv.topics)
        iv.system = prompts.system_prompt(
            p, role=iv.role, level=LEVELS.get(level, level), gender=gender, n_questions=iv.n_questions, tag=iv.tag,
            company=clean_candidate_text(iv.company), job_desc=clean_candidate_text(iv.job_desc),
            cv=clean_candidate_text(iv.cv))
        return iv

    def start(self, iv: Interview) -> str:
        p = iv.persona
        note = prompts.director_note(phase="opening", main_no=1, total=iv.n_questions, followups_left=0, attempts=0,
                                     strikes=0, patience=p.patience, next_step=p.opener.brief, covered=[], notes=[],
                                     current_topic=p.opener.key)
        messages = [{"role": "system", "content": iv.system}, {"role": "user", "content": self._user_turn(iv, "", note)}]
        out = _normalise(self._llm("turn", messages, temperature=0.7, max_tokens=700).data, "opening")
        say = out["say"]
        if not say or not _HEBREW.search(say) or "?" not in say:
            say = f"שלום, אני {p.name}, {p.title}. {p.opener.fallback}"
        iv.opening = say
        iv.phase, iv.main_no, iv.started_at = "core", 1, time.time()
        return say

    def finish(self, iv: Interview, reason: str) -> None:
        if iv.phase != "ended":
            iv.phase, iv.end_reason, iv.ended_at = "ended", reason, time.time()

    # -- one turn ----------------------------------------------------------
    def respond(self, iv: Interview, answer: str, input_method: str = "text") -> Turn:
        if not iv.active:
            raise RuntimeError("interview already ended")
        answer = clean_candidate_text(answer)
        question = iv.last_interviewer_line
        earlier = [iv.opening] + [t.reply for t in iv.turns]

        result, out = self._ask(iv, answer, force="")
        problem = self._violation(iv, out, earlier)
        corrected = False
        if problem:
            corrected = True
            try:
                result, out = self._ask(iv, answer, force=problem)
            except Exception:
                pass
            if self._violation(iv, out, earlier):
                out = self._fallback(iv, out)

        kind, decision = out["kind"], out["decision"]
        topic_key = iv.topics[iv.main_no - 1] if iv.phase == "core" else "wrap"
        turn = Turn(n=len(iv.turns) + 1, question=question, answer=answer, kind=kind, eval=out["eval"],
                    topic=topic_key, main_no=iv.main_no, decision=decision, reply=out["say"],
                    model=result.model, input_method=input_method, corrected=corrected)
        iv.turns.append(turn)
        if out["note"]:
            iv.notes.append(out["note"])

        # disruptions and forgiveness
        if kind in prompts.DISRUPTIVE:
            iv.strikes += 2 if kind == "hostile" else 1
            iv.good_streak = 0
        elif kind in ("answer", "partial"):
            iv.good_streak += 1
            if iv.good_streak >= 2 and iv.strikes > 0:
                iv.strikes -= 1
                iv.good_streak = 0

        # advance the state machine
        if decision == "end":
            reason = ("candidate_stopped" if kind == "stop" else
                      "terminated" if kind in prompts.DISRUPTIVE else "completed")
            self.finish(iv, reason)
        elif iv.phase == "wrap":
            iv.wrap_turns += 1
        elif decision == "next_topic":
            iv.covered.append(topic_key)
            iv.followups = iv.attempts = 0
            if iv.main_no >= iv.n_questions:
                iv.phase = "wrap"
            else:
                iv.main_no += 1
        elif decision == "follow_up":
            iv.followups += 1
            iv.attempts = 0
        else:  # stay
            iv.attempts += 1
        return turn

    # -- internals ---------------------------------------------------------
    def _user_turn(self, iv: Interview, answer: str, note: str) -> str:
        t = iv.tag
        return f"<candidate_{t}>\n{answer}\n</candidate_{t}>\n<director_{t}>\n{note}\n</director_{t}>"

    def _next_step(self, iv: Interview) -> str:
        p = iv.persona
        if iv.phase == "wrap":
            return p.closing
        if iv.main_no >= iv.n_questions:
            return ("that was the last main question. Do not open a new topic: ask, in one short sentence in "
                    "character, whether the candidate has any questions for you.")
        nxt = _topic(p, iv.topics[iv.main_no])
        return f'open the topic "{nxt.key}": {nxt.brief}'

    def _messages(self, iv: Interview, answer: str, force: str) -> list[dict]:
        p, t = iv.persona, iv.tag
        current = iv.topics[iv.main_no - 1] if iv.phase == "core" else "closing"
        note = prompts.director_note(
            phase=iv.phase, main_no=iv.main_no, total=iv.n_questions,
            followups_left=max(0, p.max_followups - iv.followups), attempts=iv.attempts, strikes=iv.strikes,
            patience=p.patience, next_step=self._next_step(iv), covered=iv.covered, notes=iv.notes,
            current_topic=current, force=force)
        msgs = [
            {"role": "system", "content": iv.system},
            {"role": "user", "content": f"<director_{t}>\nStart of the interview.\n</director_{t}>"},
            {"role": "assistant", "content": json.dumps({"kind": "none", "decision": "next_topic", "say": iv.opening}, ensure_ascii=False)},
        ]
        for old in iv.turns[-HISTORY_EXCHANGES:]:
            msgs.append({"role": "user", "content": f"<candidate_{t}>\n{old.answer}\n</candidate_{t}>"})
            msgs.append({"role": "assistant", "content": json.dumps(
                {"kind": old.kind, "decision": old.decision, "say": old.reply}, ensure_ascii=False)})
        msgs.append({"role": "user", "content": self._user_turn(iv, answer, note)})
        return msgs

    def _ask(self, iv: Interview, answer: str, force: str) -> tuple[LLMResult, dict]:
        result = self._llm("turn", self._messages(iv, answer, force), temperature=0.8 if force else 0.6, max_tokens=1100)
        return result, _normalise(result.data, iv.phase)

    def _violation(self, iv: Interview, out: dict, earlier: list[str]) -> str:
        """Return a correction for the model, or '' when the reply is acceptable."""
        p, kind, decision, say = iv.persona, out["kind"], out["decision"], out["say"]
        if not say or not _HEBREW.search(say):
            return "Your reply must be a spoken Hebrew sentence in the \"say\" field."
        disruptive = kind in prompts.DISRUPTIVE
        strikes_after = iv.strikes + (2 if kind == "hostile" else 1 if disruptive else 0)
        if disruptive and strikes_after >= p.patience:
            return "" if decision == "end" else (
                "The candidate has exhausted your patience. End the interview now in one or two sentences, in "
                "character. decision must be \"end\".")
        if kind == "stop":
            out["decision"] = "end"
            return ""
        if iv.phase == "wrap":
            if decision != "end" and iv.wrap_turns + 1 >= WRAP_MAX_TURNS:
                return "Time is up. Close the interview now. decision must be \"end\"."
            if decision not in ("end", "stay"):
                out["decision"] = "stay"
            return ""
        # core phase
        if decision == "end":
            return ("Do not end the interview yet - there are main questions left and the candidate has not used up "
                    "your patience. Continue according to the director's notes.")
        if decision == "follow_up" and iv.followups >= p.max_followups:
            return "You have used all follow-ups on this topic. Move on now (decision next_topic)."
        if decision == "stay" and iv.attempts >= 2:
            return ("You have already put this question twice. Do not ask it again in any form. Move on now "
                    "(decision next_topic).")
        if too_similar(say, earlier):
            return ("You are repeating a question you already asked, almost word for word. A real interviewer never "
                    "does that. Say something new: either a genuinely different angle, or move on to the next topic.")
        if "?" not in say and decision != "end":
            return "Your reply must end with exactly one question to keep the interview moving."
        return ""

    def _fallback(self, iv: Interview, out: dict) -> dict:
        """Deterministic way out when the model still breaks a rule after its retry."""
        p, kind = iv.persona, out["kind"]
        disruptive = kind in prompts.DISRUPTIVE
        strikes_after = iv.strikes + (2 if kind == "hostile" else 1 if disruptive else 0)
        fixed = dict(out)
        if disruptive and strikes_after >= p.patience:
            fixed.update(decision="end", say=p.early_exit)
        elif iv.phase == "wrap":
            fixed.update(decision="end", say=GOODBYE[p.key])
        elif iv.main_no >= iv.n_questions:
            fixed.update(decision="next_topic", say=ANY_QUESTIONS[p.key])
        else:
            nxt = _topic(p, iv.topics[iv.main_no])
            fixed.update(decision="next_topic", say=f"{p.bridge} {nxt.fallback}")
        return fixed
