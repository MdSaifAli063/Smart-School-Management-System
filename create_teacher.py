import os
from typing import Optional

from flask import Flask, jsonify, render_template, redirect, request, session, url_for
from jinja2 import TemplateNotFound
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
import bcrypt

# Configuration (override via env if needed)
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "schooldb")
PORT = int(os.getenv("PORT", "5000"))
ENV = os.getenv("ENV", "development").lower()
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

# Connect to Mongo
client = MongoClient(MONGODB_URI)
db = client[MONGODB_DB]
teachers = db.teachers

# Ensure unique index on email; don't crash app if it fails
try:
    teachers.create_index([("email", ASCENDING)], unique=True)
except Exception:
    # In dev, you might see this if Mongo isn't up at app boot; API calls will still error clearly.
    pass

app = Flask(__name__, template_folder="templates")
app.secret_key = SECRET_KEY  # required for session cookies


def _render_with_fallback(template_name: str, fallback_html: str):
    try:
        return render_template(template_name)
    except TemplateNotFound:
        return fallback_html, 200


def _normalize_email(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _authenticate(email: str, password: str):
    try:
        user = teachers.find_one({"email": email})
    except Exception:
        return None
    if not user:
        return None
    if not _check_password(password, user.get("password") or ""):
        return None
    return user


def _login_user(user: dict):
    session["user_id"] = str(user["_id"])
    session["email"] = user.get("email")
    session["name"] = user.get("name", "Teacher")


def _logout_user():
    session.clear()


def _is_authenticated() -> bool:
    return bool(session.get("user_id"))


@app.get("/")
def home():
    # If logged in, go to index; otherwise go to login
    if _is_authenticated():
        return redirect(url_for("index_page"), code=302)
    return redirect(url_for("login_page"), code=302)


@app.get("/login")
def login_page():
    # Serves your templates/login.html
    return _render_with_fallback(
        "login.html",
        "<!doctype html><title>Login</title><h1>Login</h1>"
        "<form method='post' action='/login'>"
        "<input name='email' placeholder='Email'/>"
        "<input name='password' type='password' placeholder='Password'/>"
        "<button type='submit'>Login</button>"
        "</form>",
    )


@app.post("/login")
def login_form():
    # Handle HTML form submission and redirect to index on success
    email = _normalize_email(request.form.get("email"))
    password = request.form.get("password") or ""
    if not email or not password:
        # Missing fields; re-render login with a basic fallback message
        return redirect(url_for("login_page"), code=302)

    user = _authenticate(email, password)
    if not user:
        # Invalid credentials; back to login
        return redirect(url_for("login_page"), code=302)

    _login_user(user)
    return redirect(url_for("index_page"), code=302)


@app.get("/signup")
def signup_page():
    # Serves templates/signup.html (make sure this file exists next to login.html)
    return _render_with_fallback(
        "signup.html",
        "<!doctype html><title>Signup</title><h1>Signup</h1><p>POST /api/auth/register</p>",
    )


@app.get("/index")
def index_page():
    # Post-login landing page
    if not _is_authenticated():
        return redirect(url_for("login_page"), code=302)
    name = session.get("name", "Teacher")
    return _render_with_fallback(
        "index.html",
        f"<!doctype html><title>Index</title><h1>Welcome, {name}</h1>"
        "<p>You are logged in.</p><p><a href='/logout'>Logout</a></p>",
    )


@app.get("/logout")
def logout():
    _logout_user()
    return redirect(url_for("login_page"), code=302)


@app.post("/api/auth/register")
def api_register():
    # JSON body: { name, email, password }
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = _normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    try:
        hashed = _hash_password(password)
        res = teachers.insert_one({"name": name, "email": email, "password": hashed})
    except DuplicateKeyError:
        return jsonify({"error": "Email already registered"}), 409
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    return jsonify({"ok": True, "id": str(res.inserted_id)}), 201


@app.post("/api/auth/login")
def api_login():
    # JSON body: { email, password }
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = _authenticate(email, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    # Establish session so subsequent requests are authenticated and root redirects to index
    _login_user(user)

    return jsonify({
        "ok": True,
        "redirect_url": url_for("index_page"),
        "user": {
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user.get("name", "Teacher")
        }
    }), 200


@app.get("/api/auth/me")
def api_me():
    if not _is_authenticated():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "ok": True,
        "user": {
            "id": session.get("user_id"),
            "email": session.get("email"),
            "name": session.get("name", "Teacher"),
        }
    }), 200


@app.get("/healthz")
def healthz():
    try:
        db.command("ping")
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=(ENV != "production"))