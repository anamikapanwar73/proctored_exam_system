# 🎓 Proctored Exam System
### Python Flask + MySQL (HeidiSQL) | Auto DB Setup | Anti-Cheat Point Deduction

---

## 📁 Project Structure

```
proctored_exam/
│
├── app.py          ← Flask routes ONLY (clean, no DB code)
├── database.py     ← ALL database logic:
│                       • Auto-creates database
│                       • Auto-creates all 6 tables
│                       • Seeds admin + sample exam
│                       • All SQL queries as functions
│
├── requirements.txt
├── .env.example    ← Copy to .env and set your DB password
│
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── exam.html           ← Live exam + anti-cheat JS
│   ├── results.html        ← Score + violations breakdown
│   ├── admin_dashboard.html
│   ├── admin_add_exam.html
│   └── admin_questions.html
│
└── static/css/style.css
```

---

## ⚙️ SETUP (3 steps only)

### Step 1 — Install MySQL + HeidiSQL
- MySQL: https://dev.mysql.com/downloads/mysql/
- HeidiSQL (GUI): https://www.heidisql.com/download.php
- Open HeidiSQL, connect with root + your password. That's it.
  **No need to create database manually — app does it automatically.**

### Step 2 — Configure .env
```bash
copy .env.example .env      # Windows
cp .env.example .env        # Linux/Mac
```
Edit `.env`:
```
SECRET_KEY=any-random-string
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=YOUR_MYSQL_PASSWORD
DB_NAME=proctored_exam_db
```

### Step 3 — Install & Run
```bash
pip install -r requirements.txt
python app.py
```

Open browser: **http://localhost:5000**

### ✅ On first run, app automatically:
1. Creates database `proctored_exam_db`
2. Creates all 6 tables
3. Seeds admin user + sample Python quiz
4. Prints: `[DB] ✅ Database 'proctored_exam_db' is ready.`

---

## 🔐 Default Login :Admin credentials are configured via environment variables.
---

## 📦 database.py — Module Functions

| Function | Purpose |
|---|---|
| `init_db()` | Auto-create DB + tables + seed (called on startup) |
| `get_db()` | Returns MySQL connection |
| `create_user(...)` | Register new student |
| `get_user_by_username(u)` | Fetch user for login |
| `verify_password(plain, hash)` | bcrypt check |
| `get_active_exams()` | List all active exams |
| `get_exam_by_id(id)` | Single exam |
| `create_exam(...)` | Admin: create exam |
| `get_questions_for_exam(id)` | Questions (safe — no correct_ans) |
| `add_question(...)` | Admin: add MCQ |
| `get_or_create_session(...)` | Start or resume exam |
| `get_active_session(...)` | Get in-progress session |
| `get_session_by_id(...)` | Result lookup |
| `get_past_results(student_id)` | Student history |
| `upsert_answer(...)` | Save/update answer (AJAX) |
| `get_saved_answers(session_id)` | Restore answers on reload |
| `record_violation(...)` | Log violation + deduct points |
| `get_session_penalty(session_id)` | Total penalty so far |
| `get_violations_for_session(id)` | Full violation list |
| `submit_exam(session_id, ...)` | Grade + save final result |

---

## 🚨 Violation → Point Deduction Logic

| Violation | Severity | Deduction |
|---|---|---|
| Right-click | HIGH | −10 pts |
| Dev tools | HIGH | −10 pts |
| Tab switch | MEDIUM | −5 pts |
| Copy/Paste | MEDIUM | −5 pts |
| Mouse leave | LOW | −2 pts |

`Final Score = max(0, Raw Score − Total Penalty)`
**Exam is NEVER auto-submitted. Student can continue.**

---

## 🗄️ Tables (auto-created)
`users` · `exams` · `questions` · `exam_sessions` · `student_answers` · `violations`
