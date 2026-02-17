from flask import Flask, render_template, request, redirect, url_for, session, flash
import os, json
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- APP SETUP ----------------

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_SECRET_KEY"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HOME_FOLDER = os.path.join(BASE_DIR, "static", "images", "home")
DESIGN_FOLDER = os.path.join(BASE_DIR, "static", "images", "designs")
CUSTOMER_FOLDER = os.path.join(BASE_DIR, "static", "images", "customer_uploads")
ADMIN_DB = os.path.join(BASE_DIR, "admin_users.json")
CUSTOMER_DB = os.path.join(BASE_DIR, "customer_submissions.json")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

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

    if not os.path.exists(ADMIN_DB):
        with open(ADMIN_DB, "w", encoding="utf-8") as f:
            json.dump({"admins": []}, f)

    if not os.path.exists(CUSTOMER_DB):
        with open(CUSTOMER_DB, "w", encoding="utf-8") as f:
            json.dump({"submissions": []}, f)

    _initialized = True

# ---------------- HELPERS ----------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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

    if request.method == "POST":
        track_id = request.form.get("track_id", "").strip()

        data = load_json(CUSTOMER_DB)

        for s in data["submissions"]:
            if s.get("track_id") == track_id:
                result = s
                break

        if not result:
            error = "Invalid Track ID. Please check and try again."

    return render_template("track.html", result=result, error=error)


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


    return render_template(
        "admin_dashboard.html",
        home_images=home_images,
        designs=designs,
        customers=customers
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

# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
