from flask import Flask, render_template, request, redirect, url_for, session, flash

from dotenv import load_dotenv
import google.generativeai as genai
import uuid

import os, json
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- APP SETUP ----------------

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_SECRET_KEY"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash-lite")

HOME_FOLDER = os.path.join(BASE_DIR, "static", "images", "home")
DESIGN_FOLDER = os.path.join(BASE_DIR, "static", "images", "designs")
CUSTOMER_FOLDER = os.path.join(BASE_DIR, "static", "images", "customer_uploads")
ADMIN_DB = os.path.join(BASE_DIR, "admin_users.json")
CUSTOMER_DB = os.path.join(BASE_DIR, "customer_submissions.json")
CHAT_DB = os.path.join(BASE_DIR, "chat_messages.json")
EMPLOYEE_FOLDER = os.path.join(BASE_DIR, "static", "employee_docs")
EMPLOYEE_DB = os.path.join(BASE_DIR, "employee_requests.json")


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp",'pdf'}

def load_chat():
    with open(CHAT_DB, "r", encoding="utf-8") as f:
        return json.load(f)

def save_chat(data):
    with open(CHAT_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ---------------- HEALTH CHECK (RENDER) ----------------

@app.route("/health")
def health():
    return "OK", 200

# ---------------- SAFE STARTUP (RUNS ONCE – FLASK 3 FIX) ----------------

_initialized = False

@app.before_request
def setup_app():
    global _initialized
    if _initialized:
        return

    os.makedirs(DESIGN_FOLDER, exist_ok=True)
    os.makedirs(CUSTOMER_FOLDER, exist_ok=True)
    os.makedirs(HOME_FOLDER, exist_ok=True)
    os.makedirs(EMPLOYEE_FOLDER, exist_ok=True)

    if not os.path.exists(ADMIN_DB):
        with open(ADMIN_DB, "w", encoding="utf-8") as f:
            json.dump({"admins": []}, f)

    if not os.path.exists(CUSTOMER_DB):
        with open(CUSTOMER_DB, "w", encoding="utf-8") as f:
            json.dump({"submissions": []}, f)
    if not os.path.exists(CHAT_DB):
        with open(CHAT_DB, "w", encoding="utf-8") as f:
            json.dump({
                "pending": [],
                "answered": []
            }, f)
    if not os.path.exists(EMPLOYEE_DB):
        with open(EMPLOYEE_DB, "w", encoding="utf-8") as f:
            json.dump({"requests": []}, f)


    _initialized = True

# ---------------- HELPERS ----------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
app.jinja_env.globals.update(load_json=load_json)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

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

@app.route("/contact")
def contact():
    return render_template("contact.html")

# ---------------- CUSTOMER CONTACT ----------------

@app.route("/customer", methods=["GET", "POST"])
def customer():
    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        message = request.form.get("message", "")
        file = request.files.get("image")

        if file and allowed_file(file.filename):
            filename = secure_filename(f"{name}_{file.filename}")
            file.save(os.path.join(CUSTOMER_FOLDER, filename))

            data = load_json(CUSTOMER_DB)
            track_id = f"IF-{datetime.now().strftime('%y%m%d')}-{str(len(data['submissions']) + 1).zfill(4)}"

            data["submissions"].append({
                "track_id": track_id,
                "name": name,
                "phone": phone,
                "image": filename,
                "message": message,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status": "pending"
            })

            save_json(CUSTOMER_DB, data)

            # store track id temporarily
            session["last_track_id"] = track_id

            flash(
                "Thank you! We have received your design.",
                "success"
            )

            return redirect(url_for("customer"))

    last_track_id = session.get("last_track_id")
    session.pop("last_track_id", None)

    return render_template("customer_contact.html", last_track_id=last_track_id)


# ---------------- TRACK CUSTOMER REQUEST ----------------

@app.route("/track", methods=["GET", "POST"])
def track_request():
    result = None
    error = None
    track_type = None  # "customer" or "employee"

    if request.method == "POST":
        track_id = request.form.get("track_id", "").strip()

        # 1️⃣ Check CUSTOMER requests
        customer_data = load_json(CUSTOMER_DB)
        for s in customer_data["submissions"]:
            if s.get("track_id") == track_id:
                result = s
                track_type = "customer"
                break

        # 2️⃣ If not found, check EMPLOYEE applications
        if not result:
            employee_data = load_json(EMPLOYEE_DB)
            for e in employee_data["requests"]:
                if e.get("track_id") == track_id:
                    result = e
                    track_type = "employee"
                    break

        if not result:
            error = "Invalid Track ID. Please check and try again."

    return render_template(
        "track.html",
        result=result,
        error=error,
        track_type=track_type
    )


# ---------------- CAREERS / EMPLOYEE APPLY ----------------

@app.route("/careers", methods=["GET", "POST"])
def careers():
    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        aadhar = request.form.get("aadhar")
        work_type = request.form.get("work_type")
        experience = request.form.get("experience")
        message = request.form.get("message", "")

        aadhar_file = request.files.get("aadhar_file")
        aadhar_filename = ""

        if aadhar_file and allowed_file(aadhar_file.filename):
            aadhar_filename = secure_filename(
                f"{phone}_{aadhar_file.filename}"
            )
            aadhar_file.save(
                os.path.join(EMPLOYEE_FOLDER, aadhar_filename)
            )

        employee_data = load_json(EMPLOYEE_DB)

        track_id = f"EMP-{datetime.now().strftime('%y%m%d')}-{str(len(employee_data['requests']) + 1).zfill(4)}"

        employee_data["requests"].append({
            "track_id": track_id,
            "name": name,
            "phone": phone,
            "aadhar": aadhar,
            "aadhar_file": aadhar_filename,
            "work_type": work_type,
            "experience": experience,
            "message": message,
            "status": "pending",          # pending / approved / rejected
            "salary_model": "Not decided",
            "admin_note": "",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

        save_json(EMPLOYEE_DB, employee_data)

        session["employee_track_id"] = track_id


        flash("Thank you! We will contact you soon.", "success")
        return redirect(url_for("careers"))
    track = session.get("employee_track_id")
    session.pop("employee_track_id", None)

    return render_template("careers.html", employee_track_id=track)


# ---------------- ADMIN SIGNUP (ONE TIME) ----------------

@app.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():
    data = load_json(ADMIN_DB)

    if data["admins"]:
        flash("Admin already exists. Signup disabled.", "error")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        data["admins"].append({
            "username": username,
            "password": generate_password_hash(password)
        })

        save_json(ADMIN_DB, data)
        flash("Admin created successfully. Please login.", "success")
        return redirect(url_for("admin_login"))

    return render_template("admin_signup.html")

# ---------------- ADMIN LOGIN ----------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        data = load_json(ADMIN_DB)

        for admin in data["admins"]:
            if admin["username"] == username and check_password_hash(
                admin["password"], password
            ):
                session["admin"] = username
                return redirect(url_for("admin_dashboard"))

        flash("Invalid username or password", "error")

    return render_template("admin_login.html")

# ---------------- ADMIN DASHBOARD ----------------

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    if request.method == "POST" and (
    "home_image" in request.files or "design_image" in request.files):
        if "home_image" in request.files:
            file = request.files["home_image"]
            if file and allowed_file(file.filename):
                file.save(os.path.join(HOME_FOLDER, secure_filename(file.filename)))

        if "design_image" in request.files:
            file = request.files["design_image"]
            if file and allowed_file(file.filename):
                file.save(os.path.join(DESIGN_FOLDER, secure_filename(file.filename)))

    home_images = os.listdir(HOME_FOLDER)
    designs = os.listdir(DESIGN_FOLDER)
    customers = load_json(CUSTOMER_DB)["submissions"]
    employees = load_json(EMPLOYEE_DB)["requests"]



    return render_template(
        "admin_dashboard.html",
        home_images=home_images,
        designs=designs,
        customers=customers,
        employees = employees
)


@app.route("/admin/delete/<filename>")
def delete_design(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(DESIGN_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)

    return redirect(url_for("admin_dashboard"))

# ---------------- ADMIN DELETE HOME IMAGE ----------------

@app.route("/admin/delete/home/<filename>", methods=["POST"])
def delete_home_image(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(HOME_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)

    return redirect(url_for("admin_dashboard"))


# ---------------- ADMIN DELETE DESIGN IMAGE ----------------

@app.route("/admin/delete/design/<filename>", methods=["POST"])
def delete_design_image(filename):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    path = os.path.join(DESIGN_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)

    return redirect(url_for("admin_dashboard"))

# ---------------- CUSTOMER SUBMISSION STATUS UPDATE ----------------

@app.route("/admin/customer/status/<int:index>/<status>", methods=["POST"])
def update_customer_status(index, status):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    data = load_json(CUSTOMER_DB)

    if 0 <= index < len(data["submissions"]):
        if status in ["approved", "rejected", "pending"]:
            data["submissions"][index]["status"] = status
            save_json(CUSTOMER_DB, data)

    return redirect(url_for("admin_dashboard"))


# ---------------- DELETE CUSTOMER SUBMISSION ----------------

@app.route("/admin/customer/delete/<int:index>", methods=["POST"])
def delete_customer_submission(index):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    data = load_json(CUSTOMER_DB)

    if 0 <= index < len(data["submissions"]):
        img = data["submissions"][index]["image"]
        img_path = os.path.join(CUSTOMER_FOLDER, img)

        if os.path.exists(img_path):
            os.remove(img_path)

        data["submissions"].pop(index)
        save_json(CUSTOMER_DB, data)

    return redirect(url_for("admin_dashboard"))

# ---------------- EMPLOYEE STATUS UPDATE ----------------

@app.route("/admin/employee/status/<int:index>/<status>", methods=["POST"])
def update_employee_status(index, status):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    data = load_json(EMPLOYEE_DB)

    if 0 <= index < len(data["requests"]):
        if status in ["approved", "rejected", "pending"]:
            data["requests"][index]["status"] = status
            save_json(EMPLOYEE_DB, data)

    return redirect(url_for("admin_dashboard"))

# ---------------- EMPLOYEE ADMIN NOTES ----------------

@app.route("/admin/employee/note/<int:index>", methods=["POST"])
def update_employee_note(index):
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    salary_model = request.form.get("salary_model", "")
    admin_note = request.form.get("admin_note", "")

    data = load_json(EMPLOYEE_DB)

    if 0 <= index < len(data["requests"]):
        data["requests"][index]["salary_model"] = salary_model
        data["requests"][index]["admin_note"] = admin_note
        save_json(EMPLOYEE_DB, data)

    return redirect(url_for("admin_dashboard"))


# ---------------- AI CHAT ROUTE ----------------

@app.route("/chat", methods=["POST"])
def chat():
    print("GEMINI KEY:", bool(os.getenv("GEMINI_API_KEY")))

    user_msg = request.json.get("message")
    if "chat_history" not in session:
        session["chat_history"] = []

    session["chat_history"].append({
        "role": "user",
        "text": user_msg
    })

    try:
        history_text = ""
        for msg in session["chat_history"][-6:]:
            history_text += f"{msg['role']}: {msg['text']}\n"

        response = model.generate_content(
        f"""
    You are the official AI assistant for I.F Fashion, an embroidery and saree design business in India.

    Business details:
    - Services: Embroidery work, saree embroidery, custom designs
    - Customers can upload designs through the website
    - Order processing time: 3–5 business days
    - Customers receive a Track ID after submission
    - Customers can track order status using Track ID
    - Admin reviews requests and marks them as Pending, Approved, or Rejected
    - Be polite, helpful, and business-focused
    - If you don’t know something, say admin will assist

    RULES:
    - Reply in the SAME language as the user
    - Keep answers short and clear
    - Do NOT make up prices
    - Encourage customers to upload designs or contact admin

    Customer conversation so far:
    {history_text}

    Customer message:
    {user_msg}

    """
    )

        reply = ""

        # safely extract text from Gemini response
        if hasattr(response, "text") and response.text:
            reply = response.text.strip()
        elif hasattr(response, "candidates"):
            try:
                reply = response.candidates[0].content.parts[0].text.strip()
            except Exception:
                reply = ""

        # fallback ONLY if truly empty
        if not reply:
            raise ValueError("Empty AI response")


        # save assistant reply to memory
        session["chat_history"].append({
            "role": "assistant",
            "text": reply
        })

        # keep last 6 messages only
        session["chat_history"] = session["chat_history"][-6:]

        return {"reply": reply, "admin": False}


    except Exception as e:
        print("CHAT ERROR:", e)
        data = load_chat()
        ticket_id = str(uuid.uuid4())[:8]

        data["pending"].append({
            "id": ticket_id,
            "question": user_msg
        })

        save_chat(data)

        return {
            "reply": "Our admin will reply shortly.",
            "admin": True,
            "ticket_id": ticket_id
        }


# ---------------- CHECK ADMIN REPLY ----------------

@app.route("/chat/check/<ticket_id>")
def check_admin_reply(ticket_id):
    data = load_chat()

    for a in data["answered"]:
        if a["id"] == ticket_id:
            return {"reply": a["reply"]}

    return {"reply": None}


# ---------------- ADMIN CHAT REPLY ----------------

@app.route("/admin/chat/reply", methods=["POST"])
def admin_chat_reply():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    ticket_id = request.form.get("id")
    reply = request.form.get("reply")

    data = load_chat()

    for q in data["pending"]:
        if q["id"] == ticket_id:
            q["reply"] = reply
            data["answered"].append(q)
            data["pending"].remove(q)
            break

    save_chat(data)
    return redirect(url_for("admin_dashboard"))


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
