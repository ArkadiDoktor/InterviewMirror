# InterviewMirror

**סימולטור ראיון עבודה חכם בעברית מבוסס בינה מלאכותית**

[Streamlit App](https://interviewmirror.streamlit.app)

---

## תיאור הפרויקט

מערכת סימולציה אינטראקטיבית לראיונות עבודה בעברית, המיועדת להכין מועמדים לראיונות אמיתיים. בניגוד לכלים קיימים בשוק, המערכת מנהלת **שיחה דינמית בזמן אמת** – השאלות מותאמות לתשובות המשתמש, ולא נקבעות מראש.

> 🏆 המוצר הראשון בשוק המציע סימולציית ראיון עבודה אינטראקטיבית מלאה **בשפה העברית**.

---

## יכולות עיקריות

| יכולת | תיאור |
|---|---|
| 🗣️ שיחה דינמית | המראיין מגיב לתוכן תשובותיך ומתאים שאלות בהתאם |
| 🎙️ קלט קולי | ענה בדיבור – Whisper של Groq מתמלל לעברית |
| 🔊 קול המראיין | המראיין מדבר בעברית באמצעות edge-tts |
| 👔 3 סוגי מראיינים | ידידותי / טכני / קשוח – כל אחד עם סגנון שונה |
| 📊 ניתוח ביצועים | גרף התקדמות ציונים, חוזקות ונקודות לשיפור |
| 💬 פידבק בזמן אמת | ציון X/10 לאחר כל תשובה (אופציונלי) |
| 🗄️ שמירת נתונים | כל ראיון נשמר במאגר נתונים לניתוח עתידי |

---

## השוואה למתחרים

|  | InterviewMirror | Google Interview Warmup | Yoodli | Final Round AI |
|---|:---:|:---:|:---:|:---:|
| שיחה דינמית | ✅ | ❌ | ❌ | ⚠️ |
| עברית מלאה | ✅ | ❌ | ❌ | ❌ |
| קלט קולי | ✅ | ✅ | ✅ | ✅ |
| אווטר מדבר | ✅ | ❌ | ❌ | ❌ |
| סוגי מראיינים | ✅ | ❌ | ❌ | ❌ |
| מחיר | חינמי* | חינמי | Freemium | $29+/חודש |

---

## טכנולוגיות

```
LLM          →  Groq LLaMA 3.3 70B       (שיחה דינמית + פידבק)
STT          →  Groq Whisper Large v3     (דיבור → טקסט בעברית)
TTS          →  edge-tts he-IL-AvriNeural (טקסט → דיבור בעברית)
UI           →  Streamlit
ניתוח גרפי  →  Matplotlib
בסיס נתונים →  Firebase Firestore
אווטר וידאו →  D-ID API (קונספט)
```

---

## התקנה והרצה מקומית

### דרישות מוקדמות
- Python 3.10+
- חשבון [Groq](https://console.groq.com) (חינמי)
- פרויקט [Firebase](https://firebase.google.com) עם Firestore

### 1. שכפול הריפו
```bash
git clone https://github.com/your-username/interviewmirror.git
cd interviewmirror
```

### 2. התקנת תלויות
```bash
pip install -r requirements.txt
```

### 3. הגדרת משתני סביבה

צור קובץ `.streamlit/secrets.toml`:

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

### 4. הרצה
```bash
streamlit run interview_mirror_app.py
```

פתח את הדפדפן בכתובת: `http://localhost:8501`

---

## גרסה מקוונת

הפרויקט פרוס ב-Streamlit Cloud:

**[https://interviewmirror.streamlit.app](https://interviewmirror.streamlit.app)**

---

## מבנה הפרויקט

```
interviewmirror/
├── interview_mirror_app.py   # קוד האפליקציה הראשי
├── requirements.txt          # תלויות Python
├── D-ID avatar concept.mkv   # הדגמת קונספט אווטר מדבר
└── README.md
```

---

## תהליך הראיון

```
1. הגדרות  →  בחר תפקיד וסוג מראיין
2. ראיון   →  ענה בטקסט או בקול
3. ניתוח   →  קבל ציונים, חוזקות ושיפורים
```


## מבנה הנתונים ב-Firebase

כל תור בראיון נשמר עם השדות הבאים:

```json
{
  "interview_id": "uuid",
  "turn_index": 3,
  "interviewer_type": "טכני",
  "job_role": "AI Engineer",
  "question": "שאלת המראיין",
  "user_answer": "תשובת המשתמש",
  "score": 7,
  "ai_feedback": "פידבק מלא מה-LLM",
  "timestamp": "2025-05-20T..."
}
```

---

## מפת דרכים

- [ ] שילוב HeyGen API לאווטר מדבר באיכות גבוהה
- [ ] תמיכה בשפות נוספות
- [ ] דשבורד ניתוח מתקדם על נתוני Firebase
- [ ] מצב "ראיון עיוור" ללא פידבק בכלל
- [ ] שאלות מותאמות לקובץ CV

---

פרויקט זה הוא חלק מפרויקט קורס אקדמי.

