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

# ---------------- SAFE STARTUP (RUNS ONCE) ----------------

@app.before_first_request
def setup_app():
    os.makedirs(DESIGN_FOLDER, exist_ok=True)
    os.makedirs(CUSTOMER_FOLDER, exist_ok=True)
    os.makedirs(HOME_FOLDER, exist_ok=True)


    if not os.path.exists(ADMIN_DB):
        with open(ADMIN_DB, "w", encoding="utf-8") as f:
            json.dump({"admins": []}, f)

    if not os.path.exists(CUSTOMER_DB):
        with open(CUSTOMER_DB, "w", encoding="utf-8") as f:
            json.dump({"submissions": []}, f)

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
    return render_template("home.html")

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
            data["submissions"].append({
                "name": name,
                "phone": phone,
                "image": filename,
                "message": message,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            save_json(CUSTOMER_DB, data)

            flash(
                "Thank you! We have received your design. "
                "We will contact you within 3–4 business days.",
                "success"
            )

        return redirect(url_for("customer"))

    return render_template("customer_contact.html")

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

    if request.method == "POST":
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

# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)
