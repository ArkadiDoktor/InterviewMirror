# InterviewMirror

**A realistic job-interview simulator in Hebrew, running entirely on free tiers.**

[Live app](https://interviewmirror.streamlit.app)

An interviewer with a face and a voice asks you questions, listens to what you
actually say, pushes back, moves on when a question is going nowhere, and ends
the meeting if you waste his time. Afterwards you get a report: a score, what
worked, what to fix, and how each answer could have been stronger.

## What is new in v2

| Area | v1 | v2 |
|---|---|---|
| Conversation | One prompt; the bot re-asked the same question whenever the answer was off | An interview engine (state machine) owns the agenda. The model plays the interviewer; the engine decides how long to stay on a question and when to move on or stop |
| Edge cases | "Ignore and repeat the question" | 16 answer types (don't know, asks for a hint, joke, off-topic, refusal, prompt injection, hostility, wants to stop ...) each handled the way a person would, with an escalation ladder per interviewer |
| Personas | Three tone descriptions | Three characters with a name, background, agenda of topics, reactions, scoring strictness, patience, voice and body language |
| Feedback | Regex over the chat text | Private structured evaluation per answer + a full report (competencies, per-answer review, practice plan). Live feedback is optional |
| Avatar | Static photo | The photo itself talks: mouth follows the voice, eyes blink, head moves, the interviewer "thinks" while the reply is prepared. Rendered in the browser, no video service |
| Reliability | One model; a failed DB write stopped the app | Fail-over across several free models, answers are never lost on a rate limit, storage errors never interrupt an interview |
| Interface | Three tabs, manual audio player | Setup -> interview room -> report. Voice starts by itself, one input bar for typing or speaking, works on a phone |

## How it works

```
interview_mirror_app.py     the three screens (Streamlit)
im/
  engine.py                 interview state machine + guardrails (plain Python, unit-tested)
  personas.py               the three interviewers
  prompts.py                interviewer instructions, per-turn director notes, report prompt
  llm.py                    OpenAI-compatible client with fail-over and rate-limit back-off
  speech.py                 text-to-speech (edge-tts -> gTTS) and speech-to-text (Whisper on Groq)
  avatar.py + assets/       talking-avatar component (WebGL face mesh, Web Audio lip-sync)
  report.py                 final report, with a no-model fallback
  storage.py                optional Firestore persistence
  ui.py                     stylesheet and HTML snippets
tools/build_avatar_mesh.py  one-off tool: prepare a new portrait photo for animation
tests/                      pytest suite (scripted model, no network needed)
```

**The engine.** Every turn the model returns JSON: how it reads the candidate's
message (`kind`), a private evaluation, a `decision` (follow up / next topic /
stay / end) and what it says out loud. The engine checks that against its own
counters - main questions, follow-ups per topic, failed attempts on the current
question, disruptions versus the interviewer's patience - and against the last
few questions (no repeats). A reply that breaks a rule gets one corrective
retry; after that a deterministic fallback takes over, so a conversation can
never loop.

**The avatar.** `tools/build_avatar_mesh.py` runs MediaPipe Face Mesh once per
photo and stores 478 landmarks. In the browser the photo is drawn as a WebGL
triangle mesh; moving the landmarks opens the jaw, closes the eyelids, raises
the brows and turns the head with a little parallax. Mouth opening follows the
loudness of the interviewer's voice and mouth shape follows its brightness
(Web Audio analyser). This is lip *movement*, not phoneme-accurate lip-sync -
that is the trade for costing nothing.

## Free stack

| Part | Service | Notes (free tier, checked November 2026) |
|---|---|---|
| Interviewer model | Groq: `openai/gpt-oss-120b` -> `qwen/qwen3.8-27b` -> `openai/gpt-oss-20b` | Each model has its own daily budget; the app falls through the list on a rate limit |
| Report model | Gemini `gemini-3.8-flash` if a key is set, otherwise Groq | Optional |
| Speech-to-text | Gemini 3.5 Transcribe if a Gemini key is set, otherwise Groq Whisper large v3 | Small free quota on Gemini; falls back to Whisper |
| Text-to-speech | Gemini 3.8 Flash TTS (native Hebrew voice per interviewer) -> edge-tts (`he-IL-AvriNeural`) -> gTTS -> the browser's own voice | The voice is chosen once per interview, so it never switches mid-conversation |
| Avatar | In-browser WebGL + Web Audio | No service at all |
| Hosting | Streamlit Community Cloud | |
| Database | Firebase Firestore, Spark plan | Optional |

Free-tier limits change often. Models can be swapped in secrets
(`LLM_ROUTES_TURN`, `LLM_ROUTES_REPORT`) without editing code.

## Run locally

Python 3.10 or newer.

```bash
git clone https://github.com/ArkadiDoktor/InterviewMirror.git
cd InterviewMirror
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then put your Groq key in it
streamlit run interview_mirror_app.py
```

Only `GROQ_API_KEY` is required. A free `GEMINI_API_KEY` is strongly recommended:
it gives the interviewer a much more natural Hebrew voice and transcribes spoken
answers more accurately. Without the Firestore block the app runs and simply
does not save interviews.

**Diagnostics:** open the app with `?debug=1` at the end of the address to see
which voice and transcription engines are actually in use.

**Voice answers:** after recording, the transcript is placed in the input box so
the candidate can check or fix it and then press Enter. The interviewer stops
talking as soon as the microphone button is pressed.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite drives the engine with a scripted model and the HTTP clients with a
local stand-in server, so it needs neither a key nor a network connection.

## Adding or replacing an interviewer's face

Use a frontal portrait you have the right to use: mouth closed, eyes open,
square crop, 300-600 px.

```bash
pip install "mediapipe==0.10.14" opencv-python scipy numpy     # dev machine only
python tools/build_avatar_mesh.py im/assets/friendly.jpg       # writes friendly.mesh.json
```

A new persona is one more `Persona(...)` entry in `im/personas.py` plus
`<key>.jpg` and `<key>.mesh.json` in `im/assets/`.

## Data

Firestore is schemaless, so v2 needs no migration.

- `interview_responses` - one document per answer. All v1 fields are unchanged
  (`interview_id`, `turn_index`, `interviewer_type`, `job_role`, `question`,
  `user_answer`, `score`, `ai_feedback`, `input_method`, `timestamp`); v2 adds
  `interviewer_reply`, `answer_kind`, `decision`, `topic`, `main_question`,
  `tip`, `model`, `app_version`.
- `interview_sessions` - new: one document per finished interview with the
  settings, scores, how it ended and the report.

## Known limits

- Lip movement follows the sound of the voice, not the exact phonemes.
- Without a Gemini key (or once its free daily quota is used up) all three interviewers share the same Edge voice.
- Free model quotas are shared by everyone using the deployment; at busy
  moments a reply can be delayed (the answer is kept and can be resent).
- `D-ID avatar concept.mp4` in the repository is the earlier paid-avatar concept, kept for reference.
