# InterviewMirror

**An AI-powered interactive job interview simulator in Hebrew**

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://interviewmirror.streamlit.app)

---

## Overview

InterviewMirror is a real-time job interview simulation system designed to prepare candidates for actual interviews. Unlike existing tools on the market, the system conducts a **fully dynamic conversation** — questions are adapted to the candidate's responses rather than being predetermined.

> The first product on the market offering a fully interactive job interview simulation in the **Hebrew language**.

---

## Key Features

| Feature | Description |
|---|---|
| Dynamic conversation | The interviewer responds to answer content and adapts follow-up questions accordingly |
| Voice input | Answer by speaking — Groq Whisper transcribes Hebrew in real time |
| Interviewer voice | The interviewer speaks Hebrew via edge-tts (he-IL-AvriNeural) |
| 3 interviewer personas | Friendly / Technical / Tough — each with a distinct style and behavior |
| Performance analysis | Score progression chart, strengths, and improvement points |
| Real-time feedback | Score out of 10 after each answer (optional) |
| Data persistence | Every interview is saved to Firebase Firestore for future analysis |

---

## Comparison with Competitors

|  | InterviewMirror | Google Interview Warmup | Yoodli | Final Round AI |
|---|:---:|:---:|:---:|:---:|
| Dynamic conversation | Yes | No | No | Partial |
| Full Hebrew support | Yes | No | No | No |
| Voice input (STT) | Yes | Yes | Yes | Yes |
| Talking avatar | Yes | No | No | No |
| Multiple interviewer types | Yes | No | No | No |
| Pricing | Free* | Free | Freemium | $29+/month |

---

## Technology Stack

| Component | Technology |
|---|---|
| LLM | Groq LLaMA 3.3 70B |
| Speech-to-Text | Groq Whisper Large v3 |
| Text-to-Speech | edge-tts (he-IL-AvriNeural) |
| UI Framework | Streamlit |
| Data Visualization | Matplotlib |
| Database | Firebase Firestore |
| Talking Avatar | D-ID API (concept) |

---

## Local Setup

### Prerequisites
- Python 3.10 or higher
- [Groq](https://console.groq.com) account (free tier available)
- [Firebase](https://firebase.google.com) project with Firestore enabled

### 1. Clone the repository
```bash
git clone https://github.com/your-username/interviewmirror.git
cd interviewmirror
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure secrets

Create the file `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "gsk_your_groq_key_here"

[connections.firestore]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

### 4. Run
```bash
streamlit run interview_mirror_app.py
```

Open your browser at `http://localhost:8501`

---

## Live Demo

The project is deployed on Streamlit Cloud:

**[https://interviewmirror.streamlit.app](https://interviewmirror.streamlit.app)**

---

## Project Structure

```
interviewmirror/
├── interview_mirror_app.py   # Main application code
├── requirements.txt          # Python dependencies
├── D-ID avatar concept.mkv   # Talking avatar concept demonstration
└── README.md
```

---

## Interview Flow

```
Step 1 — Settings    Select job role and interviewer type
Step 2 — Interview   Answer questions by text or voice
Step 3 — Analysis    Receive scores, strengths, and improvement points
```

### Scoring Metrics

| Metric | Methodology |
|---|---|
| Overall score | Average of LLM-assigned scores throughout the interview |
| Clarity | Based on answer length and structure |
| Confidence | Based on strong vs. hesitant language patterns |
| Professionalism | Based on domain-specific terminology usage |

---

## Firebase Data Schema

Each interview turn is stored with the following fields:

```json
{
  "interview_id": "uuid",
  "turn_index": 3,
  "interviewer_type": "Technical",
  "job_role": "AI Engineer",
  "question": "Interviewer question text",
  "user_answer": "Candidate answer text",
  "score": 7,
  "ai_feedback": "Full LLM feedback",
  "timestamp": "server timestamp"
}
```

---

## Roadmap

- Integration with HeyGen API for high-quality talking avatar
- Multi-language support
- Advanced analytics dashboard over Firebase data
- CV-aware question generation
- Blind interview mode (no real-time feedback)

---

## License

This project was developed as part of an academic course project.
