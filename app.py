from flask import Flask, render_template, request, redirect, url_for, session, flash

from dotenv import load_dotenv
import requests
import uuid

import os
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- APP SETUP ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "CHANGE_THIS_SECRET_KEY")

HOME_FOLDER = os.path.join(BASE_DIR, "static", "images", "home")
DESIGN_FOLDER = os.path.join(BASE_DIR, "static", "images", "designs")
CUSTOMER_FOLDER = os.path.join(BASE_DIR, "static", "images", "customer_uploads")
EMPLOYEE_FOLDER = os.path.join(BASE_DIR, "static", "employee_docs")

SQLITE_DB = os.path.join(BASE_DIR, "if_fashion.db")
AI_CHAT_ENABLED = os.getenv("ENABLE_AI_CHAT", "0") == "1"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}
ALLOWED_RESUME_EXTENSIONS = {"pdf", "doc", "docx"}


# ---------------- DB HELPERS ----------------

def get_db_connection():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all(query, params=()):
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def fetch_one(query, params=()):
    with get_db_connection() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def execute_query(query, params=()):
    with get_db_connection() as conn:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.lastrowid


def init_database():
    with get_db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS customer_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT NOT NULL UNIQUE,
                name TEXT,
                phone TEXT,
                image TEXT,
                message TEXT,
                time TEXT,
                status TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS employee_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT NOT NULL UNIQUE,
                name TEXT,
                phone TEXT,
                aadhar TEXT,
                aadhar_file TEXT,
                resume_file TEXT DEFAULT '',
                work_type TEXT,
                experience TEXT,
                message TEXT,
                status TEXT DEFAULT 'pending',
                salary_model TEXT DEFAULT 'Not decided',
                admin_note TEXT DEFAULT '',
                time TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_pending (
                id TEXT PRIMARY KEY,
                question TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_answered (
                id TEXT PRIMARY KEY,
                question TEXT,
                reply TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_threads (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'open',
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS request_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(employee_requests)").fetchall()]
        if "resume_file" not in cols:
            conn.execute("ALTER TABLE employee_requests ADD COLUMN resume_file TEXT DEFAULT ''")
        conn.commit()


def generate_track_id(prefix, table_name):
    date_part = datetime.now().strftime("%y%m%d")
    like_pattern = f"{prefix}-{date_part}-%"
    rows = fetch_all(
        f"SELECT track_id FROM {table_name} WHERE track_id LIKE ?",
        (like_pattern,),
    )

    max_seq = 0
    for row in rows:
        parts = (row.get("track_id") or "").split("-")
        if len(parts) == 3 and parts[2].isdigit():
            max_seq = max(max_seq, int(parts[2]))

    return f"{prefix}-{date_part}-{str(max_seq + 1).zfill(4)}"


# ---------------- CHAT HELPERS ----------------

def load_chat():
    pending = fetch_all("SELECT id, question FROM chat_pending ORDER BY rowid DESC")
    answered = fetch_all(
        "SELECT id, question, reply FROM chat_answered ORDER BY rowid DESC"
    )
    return {"pending": pending, "answered": answered}


def create_support_ticket(question, category="general"):
    ticket_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute_query(
        "INSERT OR REPLACE INTO chat_pending (id, question) VALUES (?, ?)",
        (ticket_id, question),
    )
    execute_query(
        """
        INSERT OR REPLACE INTO chat_threads (id, status, category, created_at, updated_at)
        VALUES (?, 'open', ?, ?, ?)
        """,
        (ticket_id, category, now, now),
    )
    execute_query(
        """
        INSERT INTO chat_messages (thread_id, sender, message, created_at)
        VALUES (?, 'user', ?, ?)
        """,
        (ticket_id, question, now),
    )
    return ticket_id


def add_chat_message(ticket_id, sender, message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute_query(
        """
        INSERT INTO chat_messages (thread_id, sender, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (ticket_id, sender, message, now),
    )
    execute_query(
        "UPDATE chat_threads SET updated_at = ? WHERE id = ?",
        (now, ticket_id),
    )


def get_chat_messages(ticket_id, after_id=0):
    return fetch_all(
        """
        SELECT id, sender, message, created_at
        FROM chat_messages
        WHERE thread_id = ? AND id > ?
        ORDER BY id ASC
        """,
        (ticket_id, after_id),
    )


# ---------------- TEMPLATE HELPERS ----------------

@app.context_processor
def inject_csrf_token():
    # Keeps existing templates compatible even when CSRF extension is not configured.
    return {"csrf_token": lambda: ""}


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():
    return "OK", 200


# ---------------- SAFE STARTUP ----------------

_initialized = False


@app.before_request
def setup_app():
    global _initialized
    if not _initialized:
        os.makedirs(DESIGN_FOLDER, exist_ok=True)
        os.makedirs(CUSTOMER_FOLDER, exist_ok=True)
        os.makedirs(HOME_FOLDER, exist_ok=True)
        os.makedirs(EMPLOYEE_FOLDER, exist_ok=True)
        _initialized = True

    # Keep this on every request so the app self-recovers if DB file is deleted.
    init_database()


# ---------------- HELPERS ----------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_resume_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_RESUME_EXTENSIONS


def current_ts():
    return int(datetime.now().timestamp())


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.remote_addr or "unknown").strip()


def is_rate_limited(ip, endpoint, limit_count, window_seconds):
    now = current_ts()
    cutoff = now - window_seconds
    execute_query(
        "DELETE FROM request_limits WHERE created_at < ?",
        (cutoff,),
    )
    recent = fetch_one(
        "SELECT COUNT(*) AS c FROM request_limits WHERE ip = ? AND endpoint = ? AND created_at >= ?",
        (ip, endpoint, cutoff),
    )
    if recent and recent["c"] >= limit_count:
        return True

    execute_query(
        "INSERT INTO request_limits (ip, endpoint, created_at) VALUES (?, ?, ?)",
        (ip, endpoint, now),
    )
    return False


def normalize_phone(phone_raw):
    digits = "".join(ch for ch in (phone_raw or "") if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def is_valid_indian_phone(phone_raw):
    phone = normalize_phone(phone_raw)
    return len(phone) == 10 and phone[0] in {"6", "7", "8", "9"}


def clean_aadhaar(aadhaar_raw):
    return "".join(ch for ch in (aadhaar_raw or "") if ch.isdigit())


def is_valid_aadhaar(aadhaar_raw):
    num = clean_aadhaar(aadhaar_raw)
    if len(num) != 12:
        return False

    # Verhoeff checksum validation.
    d_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    c = 0
    for i, item in enumerate(reversed(num)):
        c = d_table[c][p_table[i % 8][int(item)]]
    return c == 0


# ---------------- PUBLIC PAGES ----------------

@app.route("/")
def home():
    home_images = os.listdir(HOME_FOLDER)
    return render_template(
        "home.html",
        home_images=home_images,
        datetime=datetime
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/designs")
def designs():
    images = os.listdir(DESIGN_FOLDER)
    return render_template("designs.html", images=images)


# ---------------- CUSTOMER CONTACT ----------------

@app.route("/customer_contact", methods=["GET", "POST"])
def customer():
    if request.method == "POST":
        ip = get_client_ip()
        if is_rate_limited(ip, "customer_contact", limit_count=6, window_seconds=3600):
            flash("Too many submissions from your network. Please try again after some time.", "error")
            return redirect(url_for("customer"))

        name = (request.form.get("name") or "").strip()
        phone_raw = request.form.get("phone")
        message = (request.form.get("message", "") or "").strip()
        file = request.files.get("image")

        if len(name) < 2 or len(name) > 60:
            flash("Name must be between 2 and 60 characters.", "error")
            return redirect(url_for("customer"))
        if not is_valid_indian_phone(phone_raw):
            flash("Enter a valid 10-digit Indian mobile number.", "error")
            return redirect(url_for("customer"))
        if len(message) > 1000:
            flash("Message is too long. Please keep it under 1000 characters.", "error")
            return redirect(url_for("customer"))

        phone = normalize_phone(phone_raw)

        if file and allowed_file(file.filename):
            filename = secure_filename(f"{name}_{file.filename}")
            file.save(os.path.join(CUSTOMER_FOLDER, filename))

            track_id = generate_track_id("IF", "customer_submissions")
            execute_query(
                """
                INSERT INTO customer_submissions (track_id, name, phone, image, message, time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track_id,
                    name,
                    phone,
                    filename,
                    message,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "pending",
                ),
            )

            session["last_track_id"] = track_id
            flash("Thank you! We have received your design.", "success")
            return redirect(url_for("customer"))
        flash("Please upload a valid file (png, jpg, jpeg, webp, pdf).", "error")
        return redirect(url_for("customer"))

    last_track_id = session.get("last_track_id")
    session.pop("last_track_id", None)
    return render_template("customer_contact.html", last_track_id=last_track_id)


# ---------------- TRACK REQUEST ----------------

@app.route("/track", methods=["GET", "POST"])
def track_request():
    result = None
    error = None
    track_type = None

    if request.method == "POST":
        track_id = request.form.get("track_id", "").strip()

        result = fetch_one(
            "SELECT track_id, name, phone, image, message, time, status FROM customer_submissions WHERE track_id = ?",
            (track_id,),
        )
        if result:
            track_type = "customer"

        if not result:
            result = fetch_one(
                "SELECT track_id, name, phone, work_type, experience, salary_model, admin_note, resume_file, time, status FROM employee_requests WHERE track_id = ?",
                (track_id,),
            )
            if result:
                track_type = "employee"

        if not result:
            error = "Invalid Track ID. Please check and try again."

    return render_template("track.html", result=result, error=error, track_type=track_type)


# ---------------- CAREERS / EMPLOYEE APPLY ----------------

@app.route("/careers", methods=["GET", "POST"])
def careers():
    if request.method == "POST":
        ip = get_client_ip()
        if is_rate_limited(ip, "careers_apply", limit_count=5, window_seconds=3600):
            flash("Too many applications from your network. Please try again later.", "error")
            return redirect(url_for("careers"))

        name = (request.form.get("name") or "").strip()
        phone_raw = request.form.get("phone")
        aadhar_raw = request.form.get("aadhar")
        work_type = (request.form.get("work_type") or "").strip()
        experience = (request.form.get("experience") or "").strip()
        message = (request.form.get("message", "") or "").strip()

        aadhar_file = request.files.get("aadhar_file")
        aadhar_filename = ""
        resume_file = request.files.get("resume_file")
        resume_filename = ""

        if len(name) < 2 or len(name) > 60:
            flash("Name must be between 2 and 60 characters.", "error")
            return redirect(url_for("careers"))
        if not is_valid_indian_phone(phone_raw):
            flash("Enter a valid 10-digit Indian mobile number.", "error")
            return redirect(url_for("careers"))
        if not is_valid_aadhaar(aadhar_raw):
            flash("Enter a valid 12-digit Aadhaar number.", "error")
            return redirect(url_for("careers"))
        if len(experience) > 120:
            flash("Experience field is too long.", "error")
            return redirect(url_for("careers"))
        if len(message) > 1000:
            flash("Message is too long. Please keep it under 1000 characters.", "error")
            return redirect(url_for("careers"))

        phone = normalize_phone(phone_raw)
        aadhar = clean_aadhaar(aadhar_raw)

        if aadhar_file and allowed_file(aadhar_file.filename):
            aadhar_filename = secure_filename(f"{phone}_{aadhar_file.filename}")
            aadhar_file.save(os.path.join(EMPLOYEE_FOLDER, aadhar_filename))

        if resume_file and resume_file.filename:
            if not allowed_resume_file(resume_file.filename):
                flash("Resume must be PDF, DOC, or DOCX.", "error")
                return redirect(url_for("careers"))
            resume_filename = secure_filename(f"{phone}_resume_{resume_file.filename}")
            resume_file.save(os.path.join(EMPLOYEE_FOLDER, resume_filename))

        track_id = generate_track_id("EMP", "employee_requests")
        execute_query(
            """
            INSERT INTO employee_requests
            (track_id, name, phone, aadhar, aadhar_file, resume_file, work_type, experience, message, status, salary_model, admin_note, time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                name,
                phone,
                aadhar,
                aadhar_filename,
                resume_filename,
                work_type,
                experience,
                message,
                "pending",
                "Not decided",
                "",
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )

        session["employee_track_id"] = track_id
        flash("Thank you! We will contact you soon.", "success")
        return redirect(url_for("careers"))

    track = session.get("employee_track_id")
    session.pop("employee_track_id", None)
    return render_template("careers.html", employee_track_id=track)


# ---------------- ADMIN SIGNUP ----------------

@app.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():
    existing_admin = fetch_one("SELECT id FROM admins LIMIT 1")

    if existing_admin:
        flash("Admin already exists. Signup disabled.", "error")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username and password:
            execute_query(
                "INSERT INTO admins (username, password) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            flash("Admin created successfully. Please login.", "success")
            return redirect(url_for("admin_login"))

    return render_template("admin_signup.html")


# ---------------- ADMIN LOGIN ----------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    existing_admin = fetch_one("SELECT id FROM admins LIMIT 1")
    if not existing_admin:
        flash("No admin account found. Please create one first.", "error")
        return redirect(url_for("admin_signup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin = fetch_one(
            "SELECT username, password FROM admins WHERE username = ?",
            (username,),
        )

        if admin and check_password_hash(admin["password"], password):
            session["admin"] = username
            return redirect(url_for("admin_dashboard"))

        flash("Invalid username or password", "error")

    return render_template("admin_login.html")


# ---------------- ADMIN DASHBOARD ----------------

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    uploads_done = []
    if request.method == "POST" and (
        "home_image" in request.files or "design_image" in request.files
    ):
        if "home_image" in request.files:
            file = request.files["home_image"]
            if file and allowed_file(file.filename):
                file.save(os.path.join(HOME_FOLDER, secure_filename(file.filename)))
                uploads_done.append("home gallery")

        if "design_image" in request.files:
            file = request.files["design_image"]
            if file and allowed_file(file.filename):
                file.save(os.path.join(DESIGN_FOLDER, secure_filename(file.filename)))
                uploads_done.append("design gallery")
        if uploads_done:
            flash(f"Upload successful: {', '.join(uploads_done)}.", "success")

    home_images = os.listdir(HOME_FOLDER)
    designs = os.listdir(DESIGN_FOLDER)

    customers = fetch_all(
        """
        SELECT id, track_id, name, phone, image, message, time, status
        FROM customer_submissions
        ORDER BY id DESC
        """
    )
    employees = fetch_all(
        """
        SELECT id, track_id, name, phone, aadhar, aadhar_file, resume_file, work_type, experience, status, salary_model, admin_note, time
        FROM employee_requests
        ORDER BY id DESC
        """
    )
    pending_tickets = fetch_all(
        """
        SELECT id, status, category, created_at, updated_at
        FROM chat_threads
        WHERE status = 'open'
        ORDER BY updated_at DESC
        """
    )
    for ticket in pending_tickets:
        msgs = fetch_all(
            """
            SELECT id, sender, message, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (ticket["id"],),
        )
        ticket["messages"] = msgs
        ticket["latest_question"] = msgs[-1]["message"] if msgs else ""

    stats = {
        "total_customers": len(customers),
        "total_employees": len(employees),
        "pending_customers": sum(1 for c in customers if c["status"] == "pending"),
        "pending_employees": sum(1 for e in employees if e["status"] == "pending"),
        "pending_tickets": len(pending_tickets),
    }

    return render_template(
        "admin_dashboard.html",
        home_images=home_images,
        designs=designs,
        customers=customers,
        employees=employees,
        pending_tickets=pending_tickets,
        stats=stats,
    )


@app.route("/admin/delete/<filename>")
def delete_design(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(DESIGN_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/home/<filename>", methods=["POST"])
def delete_home_image(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(HOME_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)
        flash("Home image deleted.", "success")
    else:
        flash("Image not found.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/design/<filename>", methods=["POST"])
def delete_design_image(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(DESIGN_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)
        flash("Design image deleted.", "success")
    else:
        flash("Image not found.", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------- CUSTOMER SUBMISSION STATUS UPDATE ----------------

@app.route("/admin/customer/status/<int:submission_id>/<status>", methods=["POST"])
def update_customer_status(submission_id, status):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    submission = fetch_one(
        "SELECT id FROM customer_submissions WHERE id = ?",
        (submission_id,),
    )
    if not submission:
        flash("Customer request not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if status in ["approved", "rejected", "pending"]:
        execute_query(
            "UPDATE customer_submissions SET status = ? WHERE id = ?",
            (status, submission_id),
        )
        status_text = {
            "approved": "approved",
            "rejected": "declined",
            "pending": "moved to review",
        }[status]
        flash(f"Customer request {status_text}.", "success")
    else:
        flash("Invalid status value.", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------- DELETE CUSTOMER SUBMISSION ----------------

@app.route("/admin/customer/delete/<int:submission_id>", methods=["POST"])
def delete_customer_submission(submission_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    submission = fetch_one(
        "SELECT image FROM customer_submissions WHERE id = ?",
        (submission_id,),
    )

    if submission:
        img = submission.get("image")
        if img:
            img_path = os.path.join(CUSTOMER_FOLDER, img)
            if os.path.exists(img_path):
                os.remove(img_path)

        execute_query("DELETE FROM customer_submissions WHERE id = ?", (submission_id,))
        flash("Customer request deleted.", "success")
    else:
        flash("Customer request not found.", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------- EMPLOYEE STATUS UPDATE ----------------

@app.route("/admin/employee/status/<int:employee_id>/<status>", methods=["POST"])
def update_employee_status(employee_id, status):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    employee = fetch_one(
        "SELECT id FROM employee_requests WHERE id = ?",
        (employee_id,),
    )
    if not employee:
        flash("Employee application not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if status in ["approved", "rejected", "pending"]:
        execute_query(
            "UPDATE employee_requests SET status = ? WHERE id = ?",
            (status, employee_id),
        )
        status_text = {
            "approved": "approved",
            "rejected": "declined",
            "pending": "moved to review",
        }[status]
        flash(f"Employee application {status_text}.", "success")
    else:
        flash("Invalid status value.", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------- EMPLOYEE ADMIN NOTES ----------------

@app.route("/admin/employee/note/<int:employee_id>", methods=["POST"])
def update_employee_note(employee_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    salary_model = request.form.get("salary_model", "")
    admin_note = request.form.get("admin_note", "")

    execute_query(
        "UPDATE employee_requests SET salary_model = ?, admin_note = ? WHERE id = ?",
        (salary_model, admin_note, employee_id),
    )
    flash("Compensation model and internal notes updated.", "success")

    return redirect(url_for("admin_dashboard"))


# ---------------- AI CHAT ROUTE ----------------

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = (request.json or {}).get("message")
    if not AI_CHAT_ENABLED:
        return {
            "reply": "AI assistant is disabled to control costs. Please use manual options or contact support.",
            "admin": False,
            "ai_disabled": True,
        }

    api_key = os.getenv("AIPIPE_TOKEN")

    if "chat_history" not in session:
        session["chat_history"] = []
    session["chat_history"].append({"role": "user", "text": user_msg})

    try:
        url = "https://aipipe.org/openrouter/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_instruction = """
            You are the official AI assistant for I.F Fashion.

            About the company:
            - We provide custom fashion design services.
            - Customers can upload their own design ideas and images.
            - Our team reviews submissions and creates tailored fashion products.
            - Users receive a tracking ID to track their request status.
            - We also hire employees through the careers section.

            How the website works:
            1. Customer uploads design via the website.
            2. Admin reviews and approves/rejects the request.
            3. Work starts after approval.
            4. Customer can track status using tracking ID.

            Customer Help:
            - If user wants help, guide them step-by-step.
            - If they ask about contact, provide this:

            Contact Page:
            /customer_contact

            - Tell users they can reach out via the contact form for support.

            Admin Assistance:
            - If the AI cannot solve something, inform the user:
            "I will connect you to a human assistant."
            - Explain that their query will be forwarded to admin support.

            Your behavior:
            - Answer ONLY based on I.F Fashion services.
            - Be clear, helpful, and slightly conversational.
            - Always guide users on what to do next.
            - If question is unrelated, politely say you only assist with this website.
            """

        payload = {
            "model": "openai/gpt-4.1-nano",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_msg}
            ]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code == 200:
            res_data = response.json()
            reply = res_data["choices"][0]["message"]["content"].strip()
            return {"reply": reply, "admin": False}

        raise Exception("AI Response Failed")

    except Exception:
        ticket_id = create_support_ticket(user_msg)
        return {
            "reply": "I'm connecting you to a human assistant. One moment...",
            "admin": True,
            "ticket_id": ticket_id
        }


@app.route("/chat/ticket", methods=["POST"])
def create_manual_ticket():
    payload = request.json or {}
    message = (payload.get("message") or "").strip()
    category = (payload.get("category") or "general").strip().lower()
    ip = get_client_ip()
    if is_rate_limited(ip, "chat_ticket", limit_count=8, window_seconds=3600):
        return {"error": "Too many support messages. Please retry later."}, 429
    if not message:
        return {"error": "Message is required."}, 400
    if len(message) < 5:
        return {"error": "Please provide more details in your message."}, 400
    if len(message) > 500:
        return {"error": "Message is too long. Keep it under 500 characters."}, 400

    ticket_id = create_support_ticket(message, category=category)
    return {
        "reply": "Your support request is registered. An admin will respond shortly.",
        "admin": True,
        "ticket_id": ticket_id,
        "manual": True,
    }


@app.route("/chat/ticket/message", methods=["POST"])
def add_manual_ticket_message():
    payload = request.json or {}
    ticket_id = (payload.get("ticket_id") or "").strip()
    message = (payload.get("message") or "").strip()
    ip = get_client_ip()

    if is_rate_limited(ip, "chat_ticket_message", limit_count=20, window_seconds=3600):
        return {"error": "Too many chat messages. Please retry later."}, 429
    if not ticket_id or not message:
        return {"error": "ticket_id and message are required."}, 400
    if len(message) > 500:
        return {"error": "Message is too long. Keep it under 500 characters."}, 400

    thread = fetch_one("SELECT id, status FROM chat_threads WHERE id = ?", (ticket_id,))
    if not thread:
        return {"error": "Ticket not found."}, 404
    if thread["status"] != "open":
        return {"error": "This ticket is closed."}, 400

    add_chat_message(ticket_id, "user", message)
    execute_query(
        "INSERT OR REPLACE INTO chat_pending (id, question) VALUES (?, ?)",
        (ticket_id, message),
    )
    return {"ok": True}


@app.route("/chat/ticket/<ticket_id>/messages")
def get_ticket_messages(ticket_id):
    after_id = request.args.get("after_id", "0").strip()
    if not after_id.isdigit():
        after_id = "0"
    thread = fetch_one("SELECT id, status FROM chat_threads WHERE id = ?", (ticket_id,))
    if not thread:
        return {"error": "Ticket not found."}, 404
    msgs = get_chat_messages(ticket_id, int(after_id))
    return {"messages": msgs, "status": thread["status"]}


# ---------------- CHECK ADMIN REPLY ----------------

@app.route("/chat/check/<ticket_id>")
def check_admin_reply(ticket_id):
    latest = fetch_one(
        """
        SELECT message
        FROM chat_messages
        WHERE thread_id = ? AND sender = 'admin'
        ORDER BY id DESC
        LIMIT 1
        """,
        (ticket_id,),
    )
    return {"reply": latest["message"] if latest else None}


# ---------------- ADMIN CHAT REPLY ----------------

@app.route("/admin/chat/reply", methods=["POST"])
def admin_chat_reply():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    ticket_id = request.form.get("id")
    reply = request.form.get("reply", "")

    thread = fetch_one("SELECT id, status FROM chat_threads WHERE id = ?", (ticket_id,))
    if thread and thread["status"] == "open":
        add_chat_message(ticket_id, "admin", reply)
        flash("Support reply sent to customer.", "success")
    else:
        flash("Ticket not found or already closed.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/chat/close/<ticket_id>", methods=["POST"])
def admin_chat_close(ticket_id):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    thread = fetch_one("SELECT id, status FROM chat_threads WHERE id = ?", (ticket_id,))
    if not thread:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin_dashboard"))
    if thread["status"] == "closed":
        flash("Ticket already closed.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_query(
        "UPDATE chat_threads SET status = 'closed', updated_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ticket_id),
    )
    execute_query("DELETE FROM chat_pending WHERE id = ?", (ticket_id,))
    flash("Ticket closed successfully.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
