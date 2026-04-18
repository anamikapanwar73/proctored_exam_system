"""
python -m ensurepip --upgrade
============================================================
  database.py  —  Database Module
  - Auto creates database if not exists
  - Auto creates all tables if not exists
  - Seeds default admin + sample exam
  - All DB queries live here (no DB code in app.py)
============================================================
"""

import mysql.connector
import bcrypt
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ============================================================
#  CONFIG
# ============================================================
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER",     "root"),
    "password": os.getenv("DB_PASSWORD", "Anamika@123"),
}
DB_NAME = os.getenv("DB_NAME", "proctored_exam_db")


# ============================================================
#  VIOLATION PENALTY CONFIG  (single source of truth)
# ============================================================
VIOLATION_PENALTIES = {
    "HIGH":   10,
    "MEDIUM":  5,
    "LOW":     2,
}

VIOLATION_SEVERITY = {
    "right_click": "HIGH",
    "dev_tools":   "HIGH",
    "tab_switch":  "MEDIUM",
    "copy_paste":  "MEDIUM",
    "fullscreen":  "LOW",
    "mouse_leave": "LOW",
}


# ============================================================
#  LOW-LEVEL CONNECTION HELPERS
# ============================================================
def _connect_no_db():
    """Connect to MySQL WITHOUT selecting a database (used for DB creation)."""
    return mysql.connector.connect(**DB_CONFIG)


def get_db():
    """Return a connection to the app database. Use this everywhere in app.py."""
    return mysql.connector.connect(
        **DB_CONFIG,
        database=DB_NAME,
        autocommit=False
    )


# ============================================================
#  AUTO-INIT  —  called once on app startup
# ============================================================
def init_db():
    """
    1. Create the database if it doesn't exist.
    2. Create all tables if they don't exist.
    3. Seed default admin + sample exam (only if tables are empty).
    """
    _create_database()
    _create_tables()
    _seed_data()
    print(f"[DB] ✅ Database '{DB_NAME}' is ready.")


# ── Step 1: Create Database ──────────────────────────────────
def _create_database():
    conn = _connect_no_db()
    cur = conn.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"[DB] Database '{DB_NAME}' ensured.")


# ── Step 2: Create All Tables ────────────────────────────────
def _create_tables():
    conn = get_db()
    cur = conn.cursor()

    statements = [

        # USERS
        """
        CREATE TABLE IF NOT EXISTS users (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            username   VARCHAR(50)  NOT NULL UNIQUE,
            email      VARCHAR(100) NOT NULL UNIQUE,
            password   VARCHAR(255) NOT NULL,
            full_name  VARCHAR(100) NOT NULL,
            role       ENUM('student','admin') DEFAULT 'student',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,

        # EXAMS
        """
        CREATE TABLE IF NOT EXISTS exams (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            title           VARCHAR(150) NOT NULL,
            description     TEXT,
            duration_mins   INT  NOT NULL DEFAULT 30,
            total_marks     INT  NOT NULL DEFAULT 100,
            pass_percentage DECIMAL(5,2) DEFAULT 50.00,
            is_active       TINYINT(1)   DEFAULT 1,
            created_by      INT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,

        # QUESTIONS
        """
        CREATE TABLE IF NOT EXISTS questions (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            exam_id       INT NOT NULL,
            question_text TEXT NOT NULL,
            option_a      VARCHAR(255) NOT NULL,
            option_b      VARCHAR(255) NOT NULL,
            option_c      VARCHAR(255) NOT NULL,
            option_d      VARCHAR(255) NOT NULL,
            correct_ans   ENUM('A','B','C','D') NOT NULL,
            marks         INT DEFAULT 1,
            FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,

        # EXAM SESSIONS
        """
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            exam_id        INT NOT NULL,
            student_id     INT NOT NULL,
            started_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            submitted_at   DATETIME,
            status         ENUM('in_progress','submitted','timed_out') DEFAULT 'in_progress',
            raw_score      DECIMAL(6,2) DEFAULT 0,
            penalty_points DECIMAL(6,2) DEFAULT 0,
            final_score    DECIMAL(6,2) DEFAULT 0,
            percentage     DECIMAL(5,2) DEFAULT 0,
            pass_fail      ENUM('pass','fail','pending') DEFAULT 'pending',
            FOREIGN KEY (exam_id)    REFERENCES exams(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,

        # STUDENT ANSWERS
        """
        CREATE TABLE IF NOT EXISTS student_answers (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            session_id  INT NOT NULL,
            question_id INT NOT NULL,
            chosen_ans  ENUM('A','B','C','D'),
            is_correct  TINYINT(1) DEFAULT 0,
            FOREIGN KEY (session_id)  REFERENCES exam_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions(id)     ON DELETE CASCADE,
            UNIQUE KEY uq_session_question (session_id, question_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,

        # VIOLATIONS  (point-deduction model — no auto-submit)
        """
        CREATE TABLE IF NOT EXISTS violations (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            session_id      INT NOT NULL,
            violation_type  VARCHAR(50) NOT NULL,
            severity        ENUM('LOW','MEDIUM','HIGH') NOT NULL,
            points_deducted DECIMAL(5,2) DEFAULT 0,
            detected_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
    ]

    for sql in statements:
        cur.execute(sql)

    conn.commit()
    cur.close()
    conn.close()
    print("[DB] All tables ensured.")


# ── Step 3: Seed Default Data ────────────────────────────────
def _seed_data():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Only seed if users table is empty
    cur.execute("SELECT COUNT(*) AS cnt FROM users;")
    if cur.fetchone()["cnt"] > 0:
        cur.close()
        conn.close()
        print("[DB] Seed skipped (data already exists).")
        return

    # Admin user — Username: admin | Password: Admin@1234
    admin_pass = os.getenv("ADMIN_PASSWORD", "Admin@1234").encode()
    hashed = bcrypt.hashpw(admin_pass, bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO users (username,email,full_name,password,role) VALUES (%s,%s,%s,%s,'admin')",
        ("admin", "admin@examportal.com", "System Admin", hashed)
    )
    admin_id = cur.lastrowid

    # Sample exam
    cur.execute(
        """INSERT INTO exams (title,description,duration_mins,total_marks,pass_percentage,created_by)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        ("Python Basics Quiz", "Beginner-level Python MCQ test.", 20, 10, 60.00, admin_id)
    )
    exam_id = cur.lastrowid

    # Sample questions
    questions = [
        ("Which keyword defines a function in Python?",
         "func",    "def",      "define",   "function", "B"),
        ("Output of print(2 ** 3)?",                      "6",
         "9",        "8",        "5",        "C"),
        ("Which data type is immutable?",                 "list",
         "dict",     "set",      "tuple",    "D"),
        ("How do you start a comment?",                   "//",
         "#",        "--",       "/*",       "B"),
        ("What does len('hello') return?",                "4",
         "6",        "5",        "3",        "C"),
        ("Which method adds item to a list?",
         "add()",   "insert()", "append()", "push()",   "C"),
        ("Correct Python file extension?",                ".pt",
         ".pyt",     ".py",      ".python",  "C"),
        ("Function to convert string to integer?",
         "str()",   "float()",  "int()",    "num()",    "C"),
        ("What does 'not' operator do?",                  "Adds",
         "Reverses bool", "Multiplies", "Divides", "B"),
        ("Loop used to iterate over a sequence?",
         "while",   "do-while", "for",      "repeat",   "C"),
    ]
    for q in questions:
        cur.execute(
            """INSERT INTO questions
               (exam_id,question_text,option_a,option_b,option_c,option_d,correct_ans,marks)
               VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
            (exam_id, *q)
        )

    conn.commit()
    cur.close()
    conn.close()
    print("[DB] ✅ Seed data inserted (admin + sample exam).")


# ============================================================
#  USER QUERIES
# ============================================================
def create_user(username, email, full_name, password):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username,email,full_name,password) VALUES (%s,%s,%s,%s)",
            (username, email, full_name, hashed)
        )
        conn.commit()
        return {"ok": True}
    except mysql.connector.IntegrityError:
        return {"ok": False, "error": "Username or email already exists."}
    finally:
        cur.close()
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def get_user_by_email(email):
    """Used by forgot-password flow."""
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def update_user_password(email, new_password):
    """Hash and store new password. Returns True on success."""
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
    conn.commit()
    affected = cur.rowcount
    cur.close()
    conn.close()
    return affected > 0


def verify_password(plain, hashed):
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ============================================================
#  EXAM QUERIES
# ============================================================
def get_active_exams():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM exams WHERE is_active=1 ORDER BY created_at DESC")
    exams = cur.fetchall()
    cur.close()
    conn.close()
    return exams


def get_exam_by_id(exam_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM exams WHERE id=%s AND is_active=1", (exam_id,))
    exam = cur.fetchone()
    cur.close()
    conn.close()
    return exam


def create_exam(title, description, duration_mins, total_marks, pass_percentage, created_by):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO exams (title,description,duration_mins,total_marks,pass_percentage,created_by)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (title, description, duration_mins,
         total_marks, pass_percentage, created_by)
    )
    conn.commit()
    exam_id = cur.lastrowid
    cur.close()
    conn.close()
    return exam_id


def get_all_exams_admin():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT e.*, u.full_name AS creator FROM exams e LEFT JOIN users u ON e.created_by=u.id")
    exams = cur.fetchall()
    cur.close()
    conn.close()
    return exams


# ============================================================
#  QUESTION QUERIES
# ============================================================
def get_questions_for_exam(exam_id, include_correct=False):
    """
    Returns questions for a given exam.
    NEVER pass include_correct=True to the frontend/student.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    if include_correct:
        cur.execute(
            "SELECT * FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,))
    else:
        cur.execute(
            "SELECT id,exam_id,question_text,option_a,option_b,option_c,option_d,marks "
            "FROM questions WHERE exam_id=%s ORDER BY id",
            (exam_id,)
        )
    questions = cur.fetchall()
    cur.close()
    conn.close()
    return questions


def add_question(exam_id, question_text, option_a, option_b, option_c, option_d,
                 correct_ans, marks=1):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO questions
           (exam_id,question_text,option_a,option_b,option_c,option_d,correct_ans,marks)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (exam_id, question_text, option_a, option_b,
         option_c, option_d, correct_ans, marks)
    )
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
#  EXAM SESSION QUERIES
# ============================================================
def get_or_create_session(exam_id, student_id):
    """
    Return existing in-progress session id, or create a new one.
    BLOCKS re-attempt if student has already submitted this exam.
    Returns session_id (int) or None if already submitted.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Block if already submitted/timed-out
    cur.execute(
        "SELECT id FROM exam_sessions WHERE exam_id=%s AND student_id=%s AND status IN ('submitted','timed_out')",
        (exam_id, student_id)
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return None  # already attempted — no re-attempt allowed

    # Resume in-progress session
    cur.execute(
        "SELECT id FROM exam_sessions WHERE exam_id=%s AND student_id=%s AND status='in_progress'",
        (exam_id, student_id)
    )
    existing = cur.fetchone()
    if existing:
        cur.close()
        conn.close()
        return existing["id"]

    # Create fresh session
    cur.execute(
        "INSERT INTO exam_sessions (exam_id,student_id) VALUES (%s,%s)",
        (exam_id, student_id)
    )
    conn.commit()
    session_id = cur.lastrowid
    cur.close()
    conn.close()
    return session_id


def get_active_session(exam_id, student_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT es.*, e.duration_mins, e.total_marks, e.pass_percentage
           FROM exam_sessions es
           JOIN exams e ON es.exam_id = e.id
           WHERE es.exam_id=%s AND es.student_id=%s AND es.status='in_progress'
           ORDER BY es.started_at DESC LIMIT 1""",
        (exam_id, student_id)
    )
    sess = cur.fetchone()
    cur.close()
    conn.close()
    return sess


def get_session_by_id(session_id, student_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT es.*, e.title, e.total_marks, e.pass_percentage, u.full_name
           FROM exam_sessions es
           JOIN exams e  ON es.exam_id    = e.id
           JOIN users u  ON es.student_id = u.id
           WHERE es.id=%s AND es.student_id=%s""",
        (session_id, student_id)
    )
    sess = cur.fetchone()
    cur.close()
    conn.close()
    return sess


def get_past_results(student_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT es.*, e.title AS exam_title
           FROM exam_sessions es
           JOIN exams e ON es.exam_id = e.id
           WHERE es.student_id=%s AND es.status != 'in_progress'
           ORDER BY es.submitted_at DESC""",
        (student_id,)
    )
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results


def get_all_results_admin():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT es.*, u.full_name, u.username, e.title AS exam_title
           FROM exam_sessions es
           JOIN users u ON es.student_id = u.id
           JOIN exams e ON es.exam_id    = e.id
           WHERE es.status != 'in_progress'
           ORDER BY es.submitted_at DESC LIMIT 50"""
    )
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results


# ============================================================
#  ANSWER QUERIES
# ============================================================
def upsert_answer(session_id, question_id, chosen_ans):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO student_answers (session_id,question_id,chosen_ans)
           VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE chosen_ans=%s""",
        (session_id, question_id, chosen_ans, chosen_ans)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_saved_answers(session_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT question_id, chosen_ans FROM student_answers WHERE session_id=%s",
        (session_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r["question_id"]: r["chosen_ans"] for r in rows}


def get_detailed_answers(session_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
                  q.correct_ans, sa.chosen_ans, sa.is_correct, q.marks
           FROM student_answers sa
           JOIN questions q ON sa.question_id = q.id
           WHERE sa.session_id=%s ORDER BY q.id""",
        (session_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ============================================================
#  VIOLATION QUERIES
# ============================================================
def record_violation(session_id, violation_type):
    """
    Record one violation.
    - 1st aur 2nd violation: sirf warning, koi marks deduct nahi
    - 3rd violation se: marks deduct honge
    Returns dict with severity, points_deducted, running totals, warning_only flag.
    """
    severity = VIOLATION_SEVERITY.get(violation_type, "LOW")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Verify session is still active
    cur.execute(
        "SELECT id FROM exam_sessions WHERE id=%s AND status='in_progress'",
        (session_id,)
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        return None

    # Count existing violations
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM violations WHERE session_id=%s",
        (session_id,)
    )
    existing_count = int(cur.fetchone()["cnt"])

    # Pehli 2 violations pe sirf warning
    if existing_count < 2:
        points_deducted = 0
        warning_only = True
    else:
        # 3rd se marks deduct
        points_deducted = VIOLATION_PENALTIES.get(severity, 2)
        warning_only = False

    cur.execute(
        """INSERT INTO violations (session_id,violation_type,severity,points_deducted)
           VALUES (%s,%s,%s,%s)""",
        (session_id, violation_type, severity, points_deducted)
    )

    cur.execute(
        """SELECT COUNT(*) AS cnt, COALESCE(SUM(points_deducted),0) AS total_penalty
           FROM violations WHERE session_id=%s""",
        (session_id,)
    )
    stats = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return {
        "severity":         severity,
        "points_deducted":  points_deducted,
        "total_violations": int(stats["cnt"]),
        "total_penalty":    float(stats["total_penalty"]),
        "warning_only":     warning_only,
    }


def get_session_penalty(session_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT COALESCE(SUM(points_deducted),0) AS total FROM violations WHERE session_id=%s",
        (session_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return float(row["total"]) if row else 0.0


def get_violations_for_session(session_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT violation_type, severity, points_deducted, detected_at
           FROM violations WHERE session_id=%s ORDER BY detected_at""",
        (session_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ============================================================
#  SUBMIT EXAM  —  calculates and stores final result
# ============================================================
def submit_exam(session_id, student_id):
    """
    Grades all answers, applies violation penalties,
    saves final result. Returns result dict.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Load session info
    cur.execute(
        """SELECT es.*, e.total_marks, e.pass_percentage
           FROM exam_sessions es
           JOIN exams e ON es.exam_id = e.id
           WHERE es.id=%s AND es.student_id=%s AND es.status='in_progress'""",
        (session_id, student_id)
    )
    sess = cur.fetchone()
    if not sess:
        cur.close()
        conn.close()
        return None

    # Grade answers
    cur.execute(
        """SELECT sa.question_id, sa.chosen_ans, q.correct_ans, q.marks
           FROM student_answers sa
           JOIN questions q ON sa.question_id = q.id
           WHERE sa.session_id=%s""",
        (session_id,)
    )
    answers = cur.fetchall()

    raw_score = 0
    for ans in answers:
        if ans["chosen_ans"] == ans["correct_ans"]:
            raw_score += ans["marks"]
            cur.execute(
                "UPDATE student_answers SET is_correct=1 WHERE session_id=%s AND question_id=%s",
                (session_id, ans["question_id"])
            )

    # Fetch total penalty
    cur.execute(
        "SELECT COALESCE(SUM(points_deducted),0) AS total FROM violations WHERE session_id=%s",
        (session_id,)
    )
    penalty = float(cur.fetchone()["total"])

    total_marks = sess["total_marks"]
    final_score = max(0.0, raw_score - penalty)
    percentage = round((final_score / total_marks) *
                       100, 2) if total_marks else 0
    pass_fail = "pass" if percentage >= float(
        sess["pass_percentage"]) else "fail"

    # Persist result
    cur.execute(
        """UPDATE exam_sessions
           SET status='submitted', submitted_at=%s,
               raw_score=%s, penalty_points=%s, final_score=%s,
               percentage=%s, pass_fail=%s
           WHERE id=%s""",
        (datetime.now(), raw_score, penalty,
         final_score, percentage, pass_fail, session_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    return {
        "session_id":  session_id,
        "raw_score":   raw_score,
        "penalty":     penalty,
        "final_score": final_score,
        "percentage":  percentage,
        "pass_fail":   pass_fail,
    }
