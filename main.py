import sqlite3
import json
from flask import Flask, request, redirect, url_for, session, g
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

# --- Configuration and Initialization ---
app = Flask(__name__)
# IMPORTANT: In a real app, use a strong, complex secret key from environment variables.
app.secret_key = 'super_secret_exam_key_for_session_management'
DATABASE = 'exam_system.db'


def get_db():
    """Connects to the SQLite database and ensures row factory returns dict-like objects."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Allows accessing columns by name (like dictionary keys)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection at the end of the request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Initializes the database schema if tables do not exist."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # Table 1: Users (Admin/Student authentication)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL -- 'admin' or 'student'
            )
        """)

        # Table 2: Questions (Exam content)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                options TEXT NOT NULL, -- JSON string of options (A, B, C, D)
                correct_option TEXT NOT NULL, -- e.g., "Option B"
                topic TEXT
            )
        """)

        # Table 3: Results (Student scores)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.commit()


def create_initial_admin():
    """Creates a default admin user for initial access."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        admin_username = 'admin'
        admin_password = 'adminpassword'
        hashed_password = generate_password_hash(admin_password)
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (admin_username, hashed_password, 'admin')
        )
        db.commit()
        print(f"Default admin created: {admin_username}/{admin_password}")


# Run database initialization when the app starts
with app.app_context():
    init_db()
    create_initial_admin()

# --- Core Exam Logic (Consolidated from exam_logic.py) ---


class ExamLogic:
    """Handles all database transactions and business logic for the exam system."""

    @staticmethod
    def get_user_by_username(username):
        db = get_db()
        # Returns a dict-like row due to db.row_factory = sqlite3.Row
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return user

    @staticmethod
    def verify_login(username, password):
        user = ExamLogic.get_user_by_username(username)
        if user and check_password_hash(user['password_hash'], password):
            return user
        return None

    @staticmethod
    def register_student(username, password):
        if not username or not password:
            return "Username and password are required."
        if ExamLogic.get_user_by_username(username):
            return "Username already exists. Please choose another."

        hashed_password = generate_password_hash(password)
        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hashed_password, 'student')
            )
            db.commit()
            return None  # Success
        except Exception as e:
            return f"Database error during registration: {e}"

    # --- Admin Functions ---

    @staticmethod
    def add_question(question_text, options, correct_option, topic="General"):
        """Adds a new question to the database."""
        db = get_db()
        try:
            # Store options as a JSON string for flexible storage
            options_json = json.dumps(options)
            db.execute(
                "INSERT INTO questions (question_text, options, correct_option, topic) VALUES (?, ?, ?, ?)",
                (question_text, options_json, correct_option, topic)
            )
            db.commit()
            return True
        except Exception as e:
            print(f"Error adding question: {e}")
            return False

    @staticmethod
    def get_all_questions():
        """Retrieves all questions for admin view."""
        db = get_db()
        questions = db.execute(
            "SELECT * FROM questions ORDER BY topic, id").fetchall()
        return [dict(q) for q in questions]  # Convert rows to dictionaries

    @staticmethod
    def delete_question(question_id):
        """Deletes a question by its ID."""
        db = get_db()
        try:
            db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            db.commit()
            return True
        except Exception as e:
            print(f"Error deleting question: {e}")
            return False

    @staticmethod
    def get_all_results():
        """Retrieves all exam results joined with student usernames."""
        db = get_db()
        results = db.execute("""
            SELECT r.*, u.username
            FROM results r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.timestamp DESC
        """).fetchall()
        return [dict(r) for r in results]

    # --- Student Functions ---

    @staticmethod
    def get_exam_questions():
        """Retrieves questions ready for the student exam."""
        db = get_db()
        questions = db.execute(
            "SELECT id, question_text, options FROM questions").fetchall()

        exam_questions = []
        for q in questions:
            q_dict = dict(q)
            try:
                # Deserialize options from JSON string
                q_dict['options'] = json.loads(q_dict['options'])
                exam_questions.append(q_dict)
            except json.JSONDecodeError:
                print(f"Error decoding JSON options for question ID {q['id']}")
                continue
        return exam_questions

    @staticmethod
    def submit_exam(user_id, answers):
        """Processes the student's submitted answers, calculates score, and saves the result."""
        db = get_db()
        score = 0
        total_questions = 0

        # 1. Get correct answers for all submitted questions
        question_ids = list(answers.keys())
        if not question_ids:
            return 0, 0

        placeholders = ','.join('?' for _ in question_ids)
        correct_answers_db = db.execute(
            f"SELECT id, correct_option FROM questions WHERE id IN ({placeholders})",
            question_ids
        ).fetchall()

        correct_answers_map = {str(q['id']): q['correct_option']
                               for q in correct_answers_db}
        total_questions = len(correct_answers_map)

        # 2. Score the exam
        for q_id, submitted_answer in answers.items():
            if str(q_id) in correct_answers_map and submitted_answer == correct_answers_map[str(q_id)]:
                score += 1

        # 3. Save the result
        try:
            db.execute(
                "INSERT INTO results (user_id, score, total_questions) VALUES (?, ?, ?)",
                (user_id, score, total_questions)
            )
            db.commit()
        except Exception as e:
            print(f"Error saving result: {e}")

        return score, total_questions

    @staticmethod
    def get_student_results(user_id):
        """Retrieves a specific student's past exam results."""
        db = get_db()
        results = db.execute(
            "SELECT * FROM results WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in results]

# --- HTML Template Functions (Frontend) ---


def html_header(title):
    """Generates the common HTML head, Tailwind CSS link, and body start."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: 'Inter', sans-serif; background-color: #f7f9fb; }}
        .card {{
            background-color: white;
            padding: 2rem;
            border-radius: 0.75rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }}
    </style>
</head>
<body class="min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-5xl">
"""


def html_footer():
    """Closes the main containers and body tags."""
    return """
    </div>
</body>
</html>
"""


def nav_bar(username, role):
    """Generates the responsive navigation bar."""
    links = {
        'admin': [('Dashboard', '/admin'), ('Logout', '/logout')],
        'student': [('Dashboard', '/student'), ('Take Exam', '/take_exam'), ('Logout', '/logout')],
    }

    nav_items = "".join([
        f"""
        <a href="{url}" class="text-white hover:bg-indigo-600 px-3 py-2 rounded-md text-sm font-medium transition duration-150">
            {text}
        </a>
        """ for text, url in links.get(role, [])
    ])

    return f"""
    <nav class="bg-indigo-700 rounded-lg shadow-lg mb-6 p-4 flex justify-between items-center flex-wrap">
        <h1 class="text-xl font-bold text-white mr-4">Web Exam System ({role.title()})</h1>
        <div class="flex items-center space-x-4 mt-2 sm:mt-0">
            <span class="text-white text-sm">Welcome, <strong class="font-semibold">{username}</strong></span>
            <div class="flex space-x-2">
                {nav_items}
            </div>
        </div>
    </nav>
    """


def login_html(message=""):
    """HTML for the login page."""
    return html_header("Login") + f"""
    <div class="card max-w-md mx-auto">
        <h2 class="text-3xl font-extrabold text-gray-900 text-center mb-6">Sign In</h2>
        {'<p class="text-sm text-red-600 text-center mb-4 p-2 bg-red-100 rounded-md">{}</p>'.format(message) if message else ''}
        <form method="POST" action="{url_for('login')}" class="space-y-6">
            <div>
                <label for="username" class="block text-sm font-medium text-gray-700">Username</label>
                <input id="username" name="username" type="text" required class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
            </div>
            <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <input id="password" name="password" type="password" required class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
            </div>
            <div>
                <button type="submit" class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition duration-150">
                    Sign In
                </button>
            </div>
        </form>
        <div class="mt-6 text-center">
            <p class="text-sm text-gray-600">
                New Student? 
                <a href="{url_for('register')}" class="font-medium text-indigo-600 hover:text-indigo-500">
                    Register here
                </a>
            </p>
            <p class="text-xs text-gray-400 mt-4">Admin Credentials: username 'admin', password 'adminpassword'</p>
        </div>
    </div>
    """ + html_footer()


def register_html(message=""):
    """HTML for the student registration page."""
    return html_header("Student Registration") + f"""
    <div class="card max-w-md mx-auto">
        <h2 class="text-3xl font-extrabold text-gray-900 text-center mb-6">Student Registration</h2>
        {'<p class="text-sm text-red-600 text-center mb-4 p-2 bg-red-100 rounded-md">{}</p>'.format(message) if message else ''}
        <form method="POST" action="{url_for('register')}" class="space-y-6">
            <div>
                <label for="username" class="block text-sm font-medium text-gray-700">New Student Username</label>
                <input id="username" name="username" type="text" required class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
            </div>
            <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <input id="password" name="password" type="password" required class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
            </div>
            <div>
                <button type="submit" class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition duration-150">
                    Register
                </button>
            </div>
        </form>
        <div class="mt-6 text-center">
            <p class="text-sm text-gray-600">
                Already registered? 
                <a href="{url_for('login')}" class="font-medium text-indigo-600 hover:text-indigo-500">
                    Sign In
                </a>
            </p>
        </div>
    </div>
    """ + html_footer()


def admin_dashboard_html(username, message="", questions=None, results=None):
    """HTML for the Admin Dashboard, showing question management and results."""
    questions = questions or []
    results = results or []

    question_rows = ""
    for q in questions:
        try:
            options_list = json.loads(q['options'])
            options_str = ", ".join(options_list)
        except:
            options_str = q['options']

        question_rows += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-3 py-3 whitespace-nowrap text-sm font-medium text-gray-900">{q['id']}</td>
            <td class="px-3 py-3 whitespace-normal text-sm text-gray-500 max-w-sm">{q['question_text']}</td>
            <td class="px-3 py-3 whitespace-normal text-sm text-gray-500 max-w-xs">{options_str}</td>
            <td class="px-3 py-3 whitespace-nowrap text-sm text-green-600 font-semibold">{q['correct_option']}</td>
            <td class="px-3 py-3 whitespace-nowrap text-sm text-gray-500">{q['topic']}</td>
            <td class="px-3 py-3 whitespace-nowrap text-right text-sm font-medium">
                <!-- DELETE FORM: Submits question_id to the delete endpoint -->
                <form method="POST" action="{url_for('admin_delete_question')}" onsubmit="return confirm('Confirm deletion of question ID {q['id']}?');" class="inline">
                    <input type="hidden" name="question_id" value="{q['id']}">
                    <button type="submit" class="text-red-600 hover:text-red-900 ml-4 p-1 rounded-md bg-red-50 hover:bg-red-100 transition duration-150">Delete</button>
                </form>
            </td>
        </tr>
        """

    result_rows = ""
    for r in results:
        result_rows += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{r['username']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-lg text-gray-800 font-bold">{r['score']} / {r['total_questions']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{datetime.strptime(r['timestamp'].split('.')[0], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        """

    return html_header("Admin Dashboard") + nav_bar(username, 'admin') + f"""
    <div class="space-y-12">
        {f'<div class="p-3 bg-green-100 text-green-700 rounded-md shadow-md">{message}</div>' if message else ''}
        
        <!-- Section 1: Add New Question FORM -->
        <div class="card">
            <h3 class="text-xl font-bold mb-4 text-indigo-700">Add New Question</h3>
            <form method="POST" action="{url_for('admin_add_question')}" class="space-y-4">
                <div>
                    <label for="question_text" class="block text-sm font-medium text-gray-700">Question Text</label>
                    <textarea id="question_text" name="question_text" required rows="3" class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2 focus:ring-indigo-500 focus:border-indigo-500"></textarea>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="option_a" class="block text-sm font-medium text-gray-700">Option A</label>
                        <input id="option_a" name="option_a" type="text" required class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2">
                    </div>
                    <div>
                        <label for="option_b" class="block text-sm font-medium text-gray-700">Option B</label>
                        <input id="option_b" name="option_b" type="text" required class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2">
                    </div>
                    <div>
                        <label for="option_c" class="block text-sm font-medium text-gray-700">Option C</label>
                        <input id="option_c" name="option_c" type="text" required class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2">
                    </div>
                    <div>
                        <label for="option_d" class="block text-sm font-medium text-gray-700">Option D</label>
                        <input id="option_d" name="option_d" type="text" required class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2">
                    </div>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="correct_option" class="block text-sm font-medium text-gray-700">Correct Option (e.g., Option A, Option B)</label>
                        <input id="correct_option" name="correct_option" type="text" required class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2 focus:ring-indigo-500 focus:border-indigo-500">
                    </div>
                    <div>
                        <label for="topic" class="block text-sm font-medium text-gray-700">Topic (Optional)</label>
                        <input id="topic" name="topic" type="text" class="mt-1 block w-full border border-gray-300 rounded-md shadow-sm p-2">
                    </div>
                </div>
                
                <button type="submit" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 transition duration-150">
                    Add Question
                </button>
            </form>
        </div>

        <!-- Section 2: Question Management Table (with Delete buttons) -->
        <div class="card overflow-x-auto">
            <h3 class="text-xl font-bold mb-4 text-indigo-700">Existing Questions ({len(questions)} Total)</h3>
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th scope="col" class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                        <th scope="col" class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Question</th>
                        <th scope="col" class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Options</th>
                        <th scope="col" class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Correct</th>
                        <th scope="col" class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Topic</th>
                        <th scope="col" class="relative px-3 py-3"><span class="sr-only">Delete</span></th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {question_rows if question_rows else '<tr><td colspan="6" class="px-6 py-4 text-center text-gray-500">No questions added yet.</td></tr>'}
                </tbody>
            </table>
        </div>

        <!-- Section 3: All Student Results -->
        <div class="card overflow-x-auto">
            <h3 class="text-xl font-bold mb-4 text-indigo-700">All Student Results ({len(results)} Entries)</h3>
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Student</th>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Score</th>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {result_rows if result_rows else '<tr><td colspan="3" class="px-6 py-4 text-center text-gray-500">No exams have been taken yet.</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
    """ + html_footer()


def student_dashboard_html(username, user_id, results=None):
    """HTML for the Student Dashboard, showing past performance."""
    results = results or []

    result_rows = ""
    for r in results:
        result_rows += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{r['id']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-lg text-gray-800 font-bold">{r['score']} / {r['total_questions']}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{datetime.strptime(r['timestamp'].split('.')[0], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M')}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">
                <span class="px-3 py-1 inline-flex text-xs leading-5 font-semibold rounded-full {'bg-green-100 text-green-800' if r['score'] >= r['total_questions'] / 2 else 'bg-red-100 text-red-800'}">
                    {'Passed' if r['score'] >= r['total_questions'] / 2 else 'Needs Review'}
                </span>
            </td>
        </tr>
        """

    return html_header("Student Dashboard") + nav_bar(username, 'student') + f"""
    <div class="space-y-8">
        <div class="card p-6 text-center bg-indigo-50 border-indigo-200 border-2">
            <h3 class="text-2xl font-bold text-indigo-700 mb-2">Ready to take an exam?</h3>
            <p class="text-indigo-600 mb-4">Click the button below to start the test and review your knowledge.</p>
            <a href="{url_for('take_exam')}" class="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-lg text-white bg-indigo-600 hover:bg-indigo-700 transition duration-300 transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                Start Exam Now
            </a>
        </div>

        <!-- Section: Past Results -->
        <div class="card overflow-x-auto">
            <h3 class="text-xl font-bold mb-4 text-gray-800 border-b pb-2">Your Past Exam Results ({len(results)} History)</h3>
            <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Run ID</th>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Score</th>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date Taken</th>
                        <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                    {result_rows if result_rows else '<tr><td colspan="4" class="px-6 py-4 text-center text-gray-500">No exams taken yet.</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
    """ + html_footer()


def take_exam_html(username, questions):
    """HTML for the exam taking page."""

    if not questions:
        return html_header("Take Exam") + nav_bar(username, 'student') + f"""
        <div class="card max-w-2xl mx-auto p-8 text-center bg-yellow-50 border-yellow-200 border-l-4">
            <h3 class="text-2xl font-bold text-yellow-800 mb-4">No Questions Available</h3>
            <p class="text-yellow-700">The administrator has not added any questions yet. Please check back later.</p>
        </div>
        """ + html_footer()

    question_forms = ""
    for idx, q in enumerate(questions):
        options_html = ""
        # The options are a list of strings like ["Option A content", "Option B content", ...]
        for i, option_text in enumerate(q['options']):
            # Create a clean ID for the radio button
            option_id = f"q{q['id']}_opt{i}"
            # The value submitted will be the text of the option itself
            option_value = option_text
            options_html += f"""
            <label for="{option_id}" class="flex items-center space-x-3 p-3 border border-gray-200 rounded-lg hover:bg-indigo-50 cursor-pointer transition duration-100">
                <input id="{option_id}" name="question_{q['id']}" type="radio" value="{option_value}" required class="h-4 w-4 text-indigo-600 border-gray-300 focus:ring-indigo-500">
                <span class="text-base text-gray-700">{option_text}</span>
            </label>
            """

        question_forms += f"""
        <div class="card mb-6 border-l-4 border-indigo-500">
            <p class="text-lg font-semibold text-gray-900 mb-4">Question {idx + 1}. {q['question_text']}</p>
            <div class="space-y-3">
                {options_html}
            </div>
        </div>
        """

    return html_header("Take Exam") + nav_bar(username, 'student') + f"""
    <div class="max-w-3xl mx-auto">
        <h2 class="text-3xl font-bold text-gray-800 mb-6 border-b pb-2">Start Your Exam</h2>
        <form method="POST" action="{url_for('submit_exam')}" class="space-y-8">
            {question_forms}
            <button type="submit" class="w-full py-3 px-4 border border-transparent rounded-md shadow-lg text-base font-medium text-white bg-green-600 hover:bg-green-700 transition duration-300 transform hover:scale-[1.01] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500">
                Submit Exam
            </button>
        </form>
    </div>
    """ + html_footer()


def exam_result_html(username, score, total_questions):
    """HTML for displaying exam results."""
    percentage = (score / total_questions) * 100 if total_questions > 0 else 0

    if percentage >= 50:
        color = 'bg-green-100 text-green-700 border-green-500'
        title = 'Congratulations!'
        message = 'You passed the exam. Keep up the great work!'
    else:
        color = 'bg-red-100 text-red-700 border-red-500'
        title = 'Keep Studying!'
        message = 'You did not pass this time. Review the material and try again!'

    return html_header("Exam Results") + nav_bar(username, 'student') + f"""
    <div class="card max-w-xl mx-auto p-8 text-center {color} border-l-8">
        <h2 class="text-4xl font-extrabold mb-4">{title}</h2>
        <p class="text-xl font-semibold mb-6">{message}</p>
        
        <div class="my-8">
            <p class="text-7xl font-bold mb-2">
                {score}<span class="text-4xl">/{total_questions}</span>
            </p>
            <p class="text-3xl font-semibold">
                Score: {percentage:.1f}%
            </p>
        </div>
        
        <div class="flex flex-col space-y-3">
            <a href="{url_for('student_dashboard')}" class="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition duration-150">
                Go to Dashboard
            </a>
            <a href="{url_for('take_exam')}" class="w-full py-2 px-4 border border-indigo-600 rounded-md shadow-sm text-sm font-medium text-indigo-700 bg-white hover:bg-indigo-50 transition duration-150">
                Retake Exam
            </a>
        </div>
    </div>
    """ + html_footer()


# --- Flask Routes (Web Application Flow) ---

def requires_auth(role):
    """Decorator to check user session and role."""
    def wrapper(f):
        def decorated(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            if session.get('role') != role:
                # Redirect unauthorized users to their own dashboard or logout
                if session.get('role') == 'student':
                    return redirect(url_for('student_dashboard'))
                else:
                    return redirect(url_for('login'))
            return f(*args, **kwargs)
        decorated.__name__ = f.__name__  # Fix for flask function naming conflict
        return decorated
    return wrapper


@app.route('/')
def index():
    """Default route redirects based on login status."""
    if 'username' in session:
        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = ExamLogic.verify_login(username, password)

        if user:
            session['username'] = user['username']
            session['role'] = user['role']
            session['user_id'] = user['id']

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            return login_html("Invalid username or password. Please try again.")

    return login_html()


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles student registration."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        error = ExamLogic.register_student(username, password)

        if error:
            return register_html(error)
        else:
            # Automatic login after successful registration
            user = ExamLogic.get_user_by_username(username)
            if user:
                session['username'] = user['username']
                session['role'] = user['role']
                session['user_id'] = user['id']
                return redirect(url_for('student_dashboard'))
            # Should not happen if registration was successful
            return redirect(url_for('login'))

    return register_html()


@app.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    session.clear()
    return redirect(url_for('login'))

# --- Admin Routes ---


@app.route('/admin')
@requires_auth('admin')
def admin_dashboard():
    """Admin dashboard view."""
    questions = ExamLogic.get_all_questions()
    results = ExamLogic.get_all_results()
    message = session.pop('message', None)
    return admin_dashboard_html(session['username'], message, questions, results)


@app.route('/admin/add_question', methods=['POST'])
@requires_auth('admin')
def admin_add_question():
    """Handles form submission for adding a new question."""
    try:
        question_text = request.form['question_text']
        topic = request.form['topic']
        correct_option = request.form['correct_option']

        # Collect options into a list
        options = [
            request.form['option_a'],
            request.form['option_b'],
            request.form['option_c'],
            request.form['option_d'],
        ]

        if ExamLogic.add_question(question_text, options, correct_option, topic):
            session['message'] = "Question added successfully!"
        else:
            session['message'] = "Failed to add question due to a database error."

    except Exception as e:
        session['message'] = f"Error: Missing form data. {e}"

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_question', methods=['POST'])
@requires_auth('admin')
def admin_delete_question():
    """Handles question deletion."""
    question_id = request.form.get('question_id')
    if question_id and ExamLogic.delete_question(question_id):
        session['message'] = f"Question ID {question_id} deleted successfully."
    else:
        session['message'] = "Failed to delete question."

    return redirect(url_for('admin_dashboard'))

# --- Student Routes ---


@app.route('/student')
@requires_auth('student')
def student_dashboard():
    """Student dashboard view, showing past results and exam link."""
    user_id = session['user_id']
    results = ExamLogic.get_student_results(user_id)
    return student_dashboard_html(session['username'], user_id, results)


@app.route('/take_exam')
@requires_auth('student')
def take_exam():
    """Displays the list of questions for the exam."""
    questions = ExamLogic.get_exam_questions()
    return take_exam_html(session['username'], questions)


@app.route('/submit_exam', methods=['POST'])
@requires_auth('student')
def submit_exam():
    """Processes submitted answers and displays the results."""
    user_id = session['user_id']

    # Filter POST data to find only question answers (keys starting with 'question_')
    answers = {}
    for key, value in request.form.items():
        if key.startswith('question_'):
            # Key is 'question_ID', extract ID for mapping
            question_id = key.split('_')[1]
            answers[question_id] = value

    score, total_questions = ExamLogic.submit_exam(user_id, answers)

    # Store result in session to pass to the result page (or calculate on the fly)
    return exam_result_html(session['username'], score, total_questions)


if __name__ == '__main__':
    # For local development only. In production, gunicorn will run the app.
    # Use HOST 0.0.0.0 so that container/host binding works if needed.
    app.run(host='0.0.0.0', port=int(
        os.environ.get('PORT', 5000)), debug=False)
