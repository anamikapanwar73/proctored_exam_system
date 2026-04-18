"""
============================================================
  app.py  —  Flask Application (Routes Only)
  All database logic is in database.py
============================================================
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, flash)
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_mail import Mail, Message
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import os
from dotenv import load_dotenv
import database as db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-123")

# ============================================================
#  MAIL CONFIG
# ============================================================
GMAIL_USER = "anamikapanwar73@gmail.com"
GMAIL_PASS = "ehnb xthn kycy kxyf"

app.config["MAIL_SERVER"]         = "smtp.gmail.com"
app.config["MAIL_PORT"]           = 587
app.config["MAIL_USE_TLS"]        = True
app.config["MAIL_USE_SSL"]        = False
app.config["MAIL_USERNAME"]       = GMAIL_USER
app.config["MAIL_PASSWORD"]       = GMAIL_PASS
app.config["MAIL_DEFAULT_SENDER"] = GMAIL_USER

mail       = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)
socketio   = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

live_students = {}

with app.app_context():
    db.init_db()


# ============================================================
#  SOCKET.IO
# ============================================================
@socketio.on("student_join")
def on_student_join(data):
    exam_session_id = data.get("session_id")
    student_name    = data.get("student_name", "Unknown")
    username        = data.get("username", "")
    exam_title      = data.get("exam_title", "")
    join_room("admin_monitor")
    join_room(f"student_{exam_session_id}")
    live_students[str(exam_session_id)] = {
        "session_id":   exam_session_id,
        "student_name": student_name,
        "username":     username,
        "exam_title":   exam_title,
        "violations":   0,
        "penalty":      0,
        "status":       "online",
        "answered":     0,
        "total":        0,
    }
    emit("student_list_update", list(live_students.values()), room="admin_monitor")

@socketio.on("student_heartbeat")
def on_heartbeat(data):
    sid = str(data.get("session_id"))
    if sid in live_students:
        live_students[sid].update({
            "violations": data.get("violations", 0),
            "penalty":    data.get("penalty", 0),
            "answered":   data.get("answered", 0),
            "total":      data.get("total", 0),
            "status":     "online",
        })
        emit("student_list_update", list(live_students.values()), room="admin_monitor")

@socketio.on("student_violation_alert")
def on_violation_alert(data):
    sid = str(data.get("session_id"))
    if sid in live_students:
        live_students[sid]["violations"] = data.get("violations", 0)
        live_students[sid]["penalty"]    = data.get("penalty", 0)
    emit("violation_alert", data, room="admin_monitor")

@socketio.on("student_disconnect_exam")
def on_student_disconnect(data):
    sid = str(data.get("session_id", ""))
    if sid in live_students:
        live_students[sid]["status"] = "offline"
    emit("student_list_update", list(live_students.values()), room="admin_monitor")

@socketio.on("admin_join")
def on_admin_join(data):
    join_room("admin_monitor")
    emit("student_list_update", list(live_students.values()))

@socketio.on("video_frame")
def on_video_frame(data):
    emit("student_frame", data, room="admin_monitor")

@socketio.on("disconnect")
def on_disconnect():
    pass


# ============================================================
#  AUTH DECORATORS
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ============================================================
#  AUTH ROUTES
# ============================================================
@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        result = db.create_user(
            username  = request.form["username"].strip(),
            email     = request.form["email"].strip(),
            full_name = request.form["full_name"].strip(),
            password  = request.form["password"],
        )
        if result["ok"]:
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        flash(result["error"], "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db.get_user_by_username(request.form["username"].strip())
        if user and db.verify_password(request.form["password"], user["password"]):
            session["user_id"]   = user["id"]
            session["username"]  = user["username"]
            session["full_name"] = user["full_name"]
            session["role"]      = user["role"]
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ============================================================
#  FORGOT PASSWORD
# ============================================================
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip()
        user  = db.get_user_by_email(email)

        flash("If this email is registered, a reset link has been sent.", "info")

        if user:
            token     = serializer.dumps(email, salt="password-reset")
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                msg = Message(
                    subject    = "ExamPortal – Password Reset Request",
                    sender     = os.getenv("MAIL_EMAIL", "anamikapanwar73@gmail.com"),
                    recipients = [email],
                    html       = f"""
                    <h3>Password Reset Request</h3>
                    <p>Hi {user['full_name']},</p>
                    <p>Click below to reset your password. Link expires in <strong>30 minutes</strong>.</p>
                    <a href="{reset_url}"
                       style="background:#4f46e5;color:#fff;padding:12px 24px;
                              border-radius:6px;text-decoration:none;display:inline-block;
                              margin:16px 0;font-weight:bold;">
                       Reset Password
                    </a>
                    <p>If you did not request this, ignore this email.</p>
                    """
                )
                mail.send(msg)
                flash("Reset link sent! Please check your inbox (and spam folder).", "success")
            except Exception as e:
                print(f"[MAIL ERROR] {e}")
                flash(f"Mail error: {str(e)}", "danger")

        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html")


# ============================================================
#  RESET PASSWORD
# ============================================================
@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="password-reset", max_age=1800)
    except SignatureExpired:
        flash("Reset link has expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password         = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("reset_password.html", token=token)

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("reset_password.html", token=token)

        result = db.update_user_password(email, password)
        if result:
            flash("Password reset successful! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            flash("Something went wrong. Try again.", "danger")

    return render_template("reset_password.html", token=token)


# ============================================================
#  STUDENT DASHBOARD
# ============================================================
@app.route("/dashboard")
@login_required
def dashboard():
    exams        = db.get_active_exams()
    past_results = db.get_past_results(session["user_id"])
    return render_template("dashboard.html", exams=exams, past_results=past_results)


# ============================================================
#  CAMERA CHECK
# ============================================================
@app.route("/exam/<int:exam_id>/camera")
@login_required
def camera_check(exam_id):
    return render_template("camera_check.html", exam_id=exam_id)


# ============================================================
#  START EXAM
# ============================================================
@app.route("/exam/<int:exam_id>/start", methods=["POST"])
@login_required
def start_exam(exam_id):
    session_id = db.get_or_create_session(exam_id, session["user_id"])
    if session_id is None:
        flash("You have already attempted this exam. Re-attempts are not allowed.", "danger")
        return redirect(url_for("dashboard"))
    session["session_id"] = session_id
    return redirect(url_for("exam_page", exam_id=exam_id))


# ============================================================
#  EXAM PAGE
# ============================================================
@app.route("/exam/<int:exam_id>")
@login_required
def exam_page(exam_id):
    exam = db.get_exam_by_id(exam_id)
    if not exam:
        flash("Exam not found.", "danger")
        return redirect(url_for("dashboard"))

    exam_session = db.get_active_session(exam_id, session["user_id"])
    if not exam_session:
        flash("No active session. Please start the exam first.", "warning")
        return redirect(url_for("dashboard"))

    questions     = db.get_questions_for_exam(exam_id, include_correct=False)
    saved_answers = db.get_saved_answers(exam_session["id"])
    total_penalty = db.get_session_penalty(exam_session["id"])

    from datetime import datetime
    elapsed        = (datetime.now() - exam_session["started_at"]).total_seconds()
    time_remaining = max(0, exam["duration_mins"] * 60 - int(elapsed))

    return render_template("exam.html",
        exam           = exam,
        exam_session   = exam_session,
        questions      = questions,
        saved_answers  = saved_answers,
        time_remaining = time_remaining,
        total_penalty  = total_penalty,
    )


# ============================================================
#  SAVE ANSWER (AJAX)
# ============================================================
@app.route("/exam/save_answer", methods=["POST"])
@login_required
def save_answer():
    data = request.get_json()
    db.upsert_answer(
        session_id  = data["session_id"],
        question_id = data["question_id"],
        chosen_ans  = data["chosen_ans"],
    )
    return jsonify({"status": "ok"})


# ============================================================
#  RECORD VIOLATION (AJAX)
# ============================================================
@app.route("/exam/violation", methods=["POST"])
@login_required
def record_violation():
    data   = request.get_json()
    result = db.record_violation(
        session_id     = data["session_id"],
        violation_type = data.get("violation_type", "unknown"),
    )
    if not result:
        return jsonify({"status": "error", "message": "Invalid session"}), 403

    sev   = result["severity"]
    pts   = result["points_deducted"]
    label = {"HIGH": "🔴 HIGH", "MEDIUM": "🟠 MEDIUM", "LOW": "🟢 LOW"}.get(sev, sev)

    return jsonify({
        "status":           "ok",
        "severity":         sev,
        "points_deducted":  pts,
        "total_violations": result["total_violations"],
        "total_penalty":    result["total_penalty"],
        "message":          f"⚠️ {label} violation! −{pts} points deducted.",
    })


# ============================================================
#  SUBMIT EXAM
# ============================================================
@app.route("/exam/<int:exam_id>/submit", methods=["POST"])
@login_required
def submit_exam(exam_id):
    exam_session = db.get_active_session(exam_id, session["user_id"])
    if not exam_session:
        flash("No active session found.", "warning")
        return redirect(url_for("dashboard"))

    result = db.submit_exam(exam_session["id"], session["user_id"])
    if not result:
        flash("Could not submit exam. Try again.", "danger")
        return redirect(url_for("dashboard"))

    return redirect(url_for("results", session_id=result["session_id"]))


# ============================================================
#  RESULTS
# ============================================================
@app.route("/results/<int:session_id>")
@login_required
def results(session_id):
    result = db.get_session_by_id(session_id, session["user_id"])
    if not result:
        flash("Result not found.", "danger")
        return redirect(url_for("dashboard"))

    answers    = db.get_detailed_answers(session_id)
    violations = db.get_violations_for_session(session_id)

    return render_template("results.html",
        result=result, answers=answers, violations=violations)


# ============================================================
#  ADMIN ROUTES
# ============================================================
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    exams          = db.get_all_exams_admin()
    recent_results = db.get_all_results_admin()
    return render_template("admin_dashboard.html",
        exams=exams, recent_results=recent_results)


@app.route("/admin/exam/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_exam():
    if request.method == "POST":
        exam_id = db.create_exam(
            title           = request.form["title"].strip(),
            description     = request.form["description"].strip(),
            duration_mins   = int(request.form["duration_mins"]),
            total_marks     = int(request.form["total_marks"]),
            pass_percentage = float(request.form["pass_percentage"]),
            created_by      = session["user_id"],
        )
        flash("Exam created! Now add questions.", "success")
        return redirect(url_for("admin_add_questions", exam_id=exam_id))
    return render_template("admin_add_exam.html")


@app.route("/admin/exam/<int:exam_id>/questions", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_questions(exam_id):
    if request.method == "POST":
        db.add_question(
            exam_id       = exam_id,
            question_text = request.form["question_text"].strip(),
            option_a      = request.form["option_a"].strip(),
            option_b      = request.form["option_b"].strip(),
            option_c      = request.form["option_c"].strip(),
            option_d      = request.form["option_d"].strip(),
            correct_ans   = request.form["correct_ans"],
            marks         = int(request.form.get("marks", 1)),
        )
        flash("Question added!", "success")

    exam      = db.get_exam_by_id(exam_id)
    questions = db.get_questions_for_exam(exam_id, include_correct=True)
    return render_template("admin_questions.html", exam=exam, questions=questions)


# ============================================================
#  RUN
# ============================================================
if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)