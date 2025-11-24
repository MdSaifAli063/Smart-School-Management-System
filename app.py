import os
import re
from typing import Optional
from datetime import timedelta
from flask import request

from flask import Flask, jsonify, render_template, redirect, request, session, url_for
from flask_cors import CORS
from jinja2 import TemplateNotFound

from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, InvalidURI
import bcrypt

import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

from functools import wraps

# Optional .env loading
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

if load_dotenv:
    _dotenv_path = os.getenv("DOTENV_PATH")
    try:
        if _dotenv_path and os.path.exists(_dotenv_path):
            load_dotenv(_dotenv_path)
        else:
            load_dotenv()
    except Exception:
        pass

# -------------------- App & Config --------------------
def _getenv_clean(name: str, default: str | None = None) -> str | None:
    """Return an env var stripped of surrounding whitespace and quotes."""
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    v = str(v).strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v

MONGODB_URI = _getenv_clean(
    "MONGODB_URI",
    "",
)
MONGODB_DB = _getenv_clean("MONGODB_DB", "school_app")
PORT = int(_getenv_clean("PORT", "5000") or "5000")
ENV = (_getenv_clean("ENV", "development") or "development").lower()
SECRET_KEY = _getenv_clean("FLASK_SECRET_KEY", "dev-secret-change-me") or "dev-secret-change-me"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY

# ... existing CORS/session config ...

# -------------------- Mongo Connection --------------------
if not MONGODB_URI or not (
    MONGODB_URI.startswith("mongodb://") or MONGODB_URI.startswith("mongodb+srv://")
):
    raise RuntimeError(
        f"Invalid MONGODB_URI. Must start with 'mongodb://' or 'mongodb+srv://'. Got: {repr(MONGODB_URI)}. "
        "If you set it in Windows, ensure it is not wrapped in quotes. Prefer using a .env file without quotes."
    )

try:
    client = MongoClient(MONGODB_URI)
except InvalidURI as e:
    raise RuntimeError(
        f"MONGODB_URI appears invalid: {repr(MONGODB_URI)}. "
        "It must begin with 'mongodb://' or 'mongodb+srv://'. Remove any surrounding quotes in your env."
    ) from e

db = client[MONGODB_DB]
teachers = db.teachers

# Ensure unique index on email; non-fatal if fails at boot
try:
    teachers.create_index([("email", ASCENDING)], unique=True)
except Exception:
    pass

# -------------------- In-memory "DB" for school features --------------------
students = {}
timetable = {}
attendance = {}
diary = {}
shared_homework = {}
daily_report = {}
behaviors = {}

# -------------------- Helpers --------------------
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
    # Mark session as permanent so PERMANENT_SESSION_LIFETIME applies (sliding TTL)
    session.permanent = True
    session["user_id"] = str(user["_id"])
    session["email"] = user.get("email")
    session["name"] = user.get("name", "Teacher")

def _logout_user():
    session.clear()

def _is_authenticated() -> bool:
    return bool(session.get("user_id"))

# Add login_required decorator (new)
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_authenticated():
            return redirect(url_for("login_page"), code=302)
        return fn(*args, **kwargs)
    return wrapper

def ensure_student(roll_no):
    roll_no = str(roll_no)
    if roll_no not in students:
        return False, jsonify({"error": "Student not found"}), 404
    return True, None, None

def _env(name, default=None):
    val = os.getenv(name)
    return val if (val is not None and str(val).strip() != "") else default

def _latest_key(d: dict):
    if not d:
        return None
    return next(reversed(d.keys()))

def _format_attendance(records):
    lines = []
    for r in records:
        subj = r.get("Subject", "")
        status = r.get("Status", "")
        lines.append(f"- {subj}: {status}")
    return "\n".join(lines) if lines else "No attendance records."

def _format_diary(tasks):
    lines = []
    for i, t in enumerate(tasks):
        subj = t.get("Subject", "")
        hw = t.get("Homework", "")
        st = t.get("Status", "")
        prefix = f"{i+1}."
        lines.append(f"- {prefix} {subj}: {hw} [{st}]")
    return "\n".join(lines) if lines else "No homework entries."

def _format_daily_report(rep):
    if not rep:
        return "No daily report."
    lunch = rep.get("Lunch", "No")
    acts = rep.get("Activities", [])
    lines = [f"Lunch: {lunch}"]
    if acts:
        for a in acts:
            lines.append(f"- {a.get('Activity','')}: {a.get('Remark','')}")
    else:
        lines.append("(No activities)")
    return "\n".join(lines)

def _format_behaviors(items):
    if not items:
        return "No behavior records."
    lines = []
    for b in items:
        teacher = b.get("With Teacher", "Neutral")
        mates = b.get("With Classmates", "Neutral")
        note = b.get("Note", "")
        lines.append(f"- With Teacher: {teacher}; With Classmates: {mates}; Note: {note}")
    return "\n".join(lines)

def compile_student_update(roll_no, day: str | None = None, date: str | None = None):
    roll_no = str(roll_no)
    stu = students.get(roll_no, {})
    name = stu.get("Name", "")
    grade = stu.get("Grade", "")
    header = f"Student Update\nName: {name}\nRoll No: {roll_no}\nGrade: {grade}\n"

    # Attendance (by day)
    att_block = "No attendance records."
    if roll_no in attendance and attendance[roll_no]:
        day_key = day.capitalize() if day else _latest_key(attendance[roll_no])
        if day_key and day_key in attendance[roll_no]:
            att_block = f"Attendance ({day_key}):\n" + _format_attendance(attendance[roll_no][day_key])
        else:
            att_block = "No attendance for the specified day."

    # Diary/Homework (by day)
    diary_block = "No homework diary."
    if roll_no in diary and diary[roll_no]:
        dkey = day.capitalize() if day else _latest_key(diary[roll_no])
        if dkey and dkey in diary[roll_no]:
            diary_block = f"Homework Diary ({dkey}):\n" + _format_diary(diary[roll_no][dkey])
        else:
            diary_block = "No diary for the specified day."

    # Daily Report (by date)
    report_block = "No daily report."
    if roll_no in daily_report and daily_report[roll_no]:
        rkey = date if (date and date in daily_report[roll_no]) else _latest_key(daily_report[roll_no])
        if rkey and rkey in daily_report[roll_no]:
            report_block = f"Daily Report ({rkey}):\n" + _format_daily_report(daily_report[roll_no][rkey])
        else:
            report_block = "No daily report for the specified date."

    # Behaviors (all recorded)
    behaviors_block = "No behavior records."
    if roll_no in behaviors and behaviors[roll_no]:
        behaviors_block = "Behavior Records:\n" + _format_behaviors(behaviors[roll_no])

    body = (
        f"{header}\n"
        f"----------------------\n"
        f"{att_block}\n\n"
        f"----------------------\n"
        f"{diary_block}\n\n"
        f"----------------------\n"
        f"{report_block}\n\n"
        f"----------------------\n"
        f"{behaviors_block}\n"
    )
    return body

def _smtp_config_status():
    host = _env("SMTP_HOST")
    port = _env("SMTP_PORT")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    from_email = _env("SMTP_FROM", user)
    use_ssl = str(_env("SMTP_USE_SSL", "false")).strip().lower() == "true"

    missing = []
    for name, val in [
        ("SMTP_HOST", host),
        ("SMTP_PORT", port),
        ("SMTP_USER", user),
        ("SMTP_PASS", password),
        ("SMTP_FROM", from_email),
    ]:
        if not val:
            missing.append(name)

    return {
        "configured": len(missing) == 0,
        "missing": missing,
        "host_set": bool(host),
        "port_set": bool(port),
        "user_set": bool(user),
        "from_set": bool(from_email),
        "use_ssl": use_ssl,
    }

def send_email(to_addrs, subject, body):
    """
    Send a plain-text email using SMTP environment variables.
    Returns: (success: bool, error: str | None)
    """
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", 587))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    from_email = _env("SMTP_FROM", user)
    from_name = _env("SMTP_FROM_NAME", "School Updates")
    use_ssl_flag = str(_env("SMTP_USE_SSL", "false")).strip().lower() == "true"
    timeout = int(_env("SMTP_TIMEOUT", 15))

    if not host or not port or not user or not password or not from_email:
        return False, "SMTP is not configured (missing SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM)."

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    msg["To"] = ", ".join(to_addrs)

    try:
        if use_ssl_flag or port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as server:
                server.login(user, password)
                refused = server.sendmail(from_email, to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(user, password)
                refused = server.sendmail(from_email, to_addrs, msg.as_string())

        if refused:
            return False, f"Some recipients were refused: {refused}"
        return True, None
    except Exception as e:
        return False, str(e)

# -------------------- Auth + Pages --------------------

@app.route('/')
def home():
    return render_template('home.html')

# Protect informational pages so unauthenticated users are redirected to login
@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/features')
@login_required
def features():
    return render_template('features.html')

@app.route('/contact')
@login_required
def contact():
    return render_template('contact.html')

@app.get("/login")
def login_page():
    # If already authenticated, skip the login page and show index directly
    if _is_authenticated():
        return redirect(url_for("index_page"), code=302)
    return render_template("login.html")

# Alias so your button can use /signin or /login
@app.get("/signin")
def signin_redirect():
    return redirect(url_for("login_page"), code=302)

@app.post("/login")
def login_form():
    email = _normalize_email(request.form.get("email"))
    password = request.form.get("password") or ""
    if not email or not password:
        return redirect(url_for("login_page"), code=302)
    user = _authenticate(email, password)
    if not user:
        return redirect(url_for("login_page"), code=302)
    _login_user(user)
    # After form login, send user to the public home — they can click
    # "Get Started" to access the authenticated dashboard (/index).
    return redirect(url_for("home"), code=302)

@app.get("/signup")
def signup_page():
    return render_template("signup.html")

@app.get("/index")
def index_page():
    if not _is_authenticated():
        return redirect(url_for("login_page"), code=302)
    return render_template("index.html")

@app.get("/logout")
def logout():
    _logout_user()
    # After logging out, return to the public landing page
    return redirect(url_for("home"), code=302)

# -------------------- Auth API --------------------
@app.post("/api/auth/register")
def api_register():
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
    data = request.get_json(silent=True) or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    user = _authenticate(email, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    _login_user(user)
    return jsonify({
        "ok": True,
        "redirect_url": url_for("home"),
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

@app.post("/api/auth/logout")
def api_logout():
    _logout_user()
    return jsonify({"ok": True}), 200

# -------------------- Health --------------------
@app.get("/healthz")
def healthz():
    try:
        db.command("ping")
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------- Students --------------------
@app.post("/students")
def add_student():
    data = request.get_json(silent=True) or {}
    required = ["roll_no","name","age","grade","gender","fathers_name","mothers_name","blood_group","address"]
    missing = [k for k in required if k not in data or str(data[k]).strip() == ""]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    roll_no = str(data["roll_no"]).strip()
    if roll_no in students:
        return jsonify({"error": f"Student with roll_no {roll_no} already exists"}), 409

    parent_emails = []
    for key in ("parent_email", "father_email", "mother_email"):
        val = str(data.get(key, "")).strip()
        if val:
            parent_emails.append(val)

    students[roll_no] = {
        "Name": data["name"],
        "Age": data["age"],
        "Grade": data["grade"],
        "Gender": data["gender"],
        "Fathers_name": data["fathers_name"],
        "Mothers_name": data["mothers_name"],
        "Blood_group": data["blood_group"],
        "Address": data["address"],
        "ParentEmails": parent_emails,
    }
    diary.setdefault(roll_no, {})

    return jsonify({"message": "Student added", "student": students[roll_no]}), 201

@app.get("/students")
def list_students():
    return jsonify(students)

@app.get("/students/<roll_no>")
def get_student(roll_no):
    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code
    return jsonify(students[str(roll_no)])

@app.get("/students/<roll_no>/contacts")
def get_parent_contacts(roll_no):
    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code
    return jsonify({"parent_emails": students[str(roll_no)].get("ParentEmails", [])})

@app.post("/students/<roll_no>/contacts")
def set_parent_contacts(roll_no):
    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code
    data = request.get_json(silent=True) or {}
    emails = data.get("parent_emails", [])
    if isinstance(emails, str):
        emails = [emails]
    emails = [e.strip() for e in emails if isinstance(e, str) and e.strip()]
    if not emails:
        return jsonify({"error": "Provide at least one parent email in parent_emails[]"}), 400
    students[str(roll_no)]["ParentEmails"] = emails
    return jsonify({"message": "Parent emails updated", "parent_emails": emails})

# -------------------- Timetable --------------------
def _grade_key(grade: Optional[str]) -> str:
    """Normalize grade string to a stable key for timetable lookup."""
    if grade is None:
        return ""
    g = str(grade).strip()
    # Lowercase and collapse multiple spaces to single space for stable keys
    g = re.sub(r"\s+", " ", g).lower()
    return g

def _day_key(day: Optional[str]) -> str:
    """Normalize a day string to a stable form (Title case, trimmed)."""
    if not day:
        return ""
    return str(day).strip().capitalize()

def _find_day_in_timetable(gkey: str, day_raw: Optional[str]) -> Optional[str]:
    """
    Try to find the best matching day key in timetable[gkey] for a provided day string.
    Returns the actual stored day key (as used in timetable[gkey]) or None.
    """
    if not gkey or gkey not in timetable or not day_raw:
        return None
    want = str(day_raw).strip().lower()
    # direct / exact match (case-insensitive)
    for k in timetable[gkey].keys():
        if k.lower() == want:
            return k
    # loose match: startswith / contains (helps with small typos or variants)
    for k in timetable[gkey].keys():
        kl = k.lower()
        if kl.startswith(want) or want.startswith(kl) or want in kl:
            return k
    return None

@app.post("/timetable")
def add_timetable():
    data = request.get_json(silent=True) or {}
    grade_raw = str(data.get("grade", "")).strip()
    day_raw = str(data.get("day", "")).strip()
    day = _day_key(day_raw)
    periods = data.get("periods", [])

    if not grade_raw or not day or not isinstance(periods, list) or not periods:
        return jsonify({"error": "grade, day, and periods[] are required"}), 400

    gkey = _grade_key(grade_raw)

    if gkey in timetable and day in timetable[gkey]:
        return jsonify({"error": f"Timetable already exists for Grade {grade_raw} on {day} and cannot be changed"}), 409

    built = []
    for i, p in enumerate(periods):
        built.append({
            "Time": p.get("time", ""),
            "Subject": p.get("subject", ""),
            "Teacher": p.get("teacher", ""),
            "Room": p.get("room", ""),
        })
        if i == 1:
            built.append({"Time": "10:30 - 10:45", "Subject": "Short Break"})
        elif i == 3:
            built.append({"Time": "12:00 - 12:30", "Subject": "Lunch Break"})
        elif i == 5:
            built.append({"Time": "2:15 - 2:30", "Subject": "Games Break"})

    timetable.setdefault(gkey, {})[day] = built
    return jsonify({"message": "Timetable added", "timetable": timetable[gkey][day]}), 201

@app.get("/timetable/<grade>")
def view_timetable(grade):
    gkey = _grade_key(grade)
    if gkey not in timetable:
        return jsonify({"error": "No timetable for this grade"}), 404
    return jsonify(timetable[gkey])

@app.get("/timetable/<grade>/<day>")
def view_timetable_by_day(grade, day):
    gkey = _grade_key(grade)
    # Try to find a matching stored day key
    matched = _find_day_in_timetable(gkey, day)
    if gkey in timetable and matched:
        return jsonify(timetable[gkey][matched])
    # helpful error with available days if present
    available = list(timetable.get(gkey, {}).keys())
    if gkey in timetable and not matched:
        return jsonify({"error": "No timetable found for this grade on that day", "available_days": available}), 404
    return jsonify({"error": "No timetable found for this grade on this day"}), 404

# -------------------- Attendance --------------------
@app.post("/attendance/mark")
def mark_attendance():
    data = request.get_json(silent=True) or {}
    roll_no = str(data.get("roll_no", "")).strip()
    day_raw = str(data.get("day", "")).strip()

    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code

    # normalize grade key from stored student grade
    grade_raw = students[roll_no].get("Grade", "")
    grade_key = _grade_key(grade_raw)

    # Find a matching stored day key for this grade
    matched_day = _find_day_in_timetable(grade_key, day_raw)
    if not matched_day:
        available = list(timetable.get(grade_key, {}).keys())
        return jsonify({
            "error": "No timetable found for this student's grade and day. Add timetable first or use a valid day.",
            "grade": grade_raw,
            "requested_day": day_raw,
            "available_days": available
        }), 400

    provided = data.get("attendance")
    records = []
    for period in timetable[grade_key][matched_day]:
        if "Teacher" in period and period.get("Teacher"):
            subj = period["Subject"]
            status = "Pending"
            if isinstance(provided, list):
                match = next((x for x in provided if x.get("Subject") == subj), None)
                if match:
                    status = str(match.get("Status", "Pending")).capitalize()
            records.append({"Subject": subj, "Status": status})
        else:
            records.append({"Subject": period["Subject"], "Status": "N/A"})

    attendance.setdefault(roll_no, {})[matched_day] = records
    return jsonify({"message": "Attendance marked", "records": records})

@app.get("/attendance/<roll_no>")
def view_attendance(roll_no):
    r = str(roll_no)
    if r not in attendance:
        return jsonify({"error": "No attendance records for this student"}), 404
    return jsonify(attendance[r])

# -------------------- Homework & Diary --------------------
@app.post("/homework/set")
def set_homework_for_day():
    data = request.get_json(silent=True) or {}
    day = str(data.get("day", "")).strip().capitalize()
    tasks = data.get("tasks", [])

    if not day or not tasks:
        return jsonify({"error": "day and tasks[] required"}), 400

    if day in shared_homework:
        return jsonify({"error": f"Homework for {day} already set and cannot be changed"}), 409

    shared_homework[day] = [{"Subject": t.get("Subject", ""), "Homework": t.get("Homework", "")} for t in tasks]
    return jsonify({"message": "Homework set", "tasks": shared_homework[day]}), 201

@app.post("/homework/mark")
def mark_homework_complete():
    data = request.get_json(silent=True) or {}
    roll_no = str(data.get("roll_no", "")).strip()
    day = str(data.get("day", "")).strip().capitalize()

    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code

    if day not in shared_homework:
        return jsonify({"error": "No homework set for this day"}), 404

    diary.setdefault(roll_no, {})
    if day not in diary[roll_no]:
        diary[roll_no][day] = [{**task, "Status": "Pending"} for task in shared_homework[day]]

    completed = set(data.get("completed", []))
    statuses = data.get("statuses", [])

    for i in completed:
        if isinstance(i, int) and 0 <= i < len(diary[roll_no][day]):
            diary[roll_no][day][i]["Status"] = "Completed"

    for st in statuses:
        idx = st.get("index")
        val = st.get("Status")
        if isinstance(idx, int) and 0 <= idx < len(diary[roll_no][day]) and val in ("Pending", "Completed"):
            diary[roll_no][day][idx]["Status"] = val

    return jsonify({"message": "Homework updated", "day": day, "tasks": diary[roll_no][day]})

@app.get("/diary/<roll_no>")
def view_diary(roll_no):
    r = str(roll_no)
    if r not in diary or not diary[r]:
        return jsonify({"error": "No diary records for this student"}), 404
    return jsonify(diary[r])

@app.get("/diary/<roll_no>/<day>")
def view_diary_by_day(roll_no, day):
    r = str(roll_no)
    d = day.capitalize()
    if r in diary and d in diary[r]:
        return jsonify({"student": students.get(r, {}).get("Name", ""), "day": d, "tasks": diary[r][d]})
    return jsonify({"error": "No homework marked yet for that day"}), 404

# -------------------- Daily Report --------------------
@app.post("/report/log")
def log_daily_activity():
    data = request.get_json(silent=True) or {}
    roll_no = str(data.get("roll_no", "")).strip()

    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code

    date = str(data.get("date", "")).strip()  # "DD-MM-YYYY"
    lunch = "Yes" if str(data.get("lunch", "no")).strip().lower() == "yes" else "No"
    activities = data.get("activities", [])

    if not date:
        return jsonify({"error": "date required (DD-MM-YYYY)"}), 400

    daily_report.setdefault(roll_no, {})[date] = {
        "Lunch": lunch,
        "Activities": [{"Activity": a.get("Activity", ""), "Remark": a.get("Remark", "")} for a in activities]
    }
    return jsonify({"message": "Daily report logged"})

@app.get("/report/<roll_no>")
def view_report(roll_no):
    r = str(roll_no)
    if r not in daily_report:
        return jsonify({"error": "No reports found"}), 404
    return jsonify(daily_report[r])

# -------------------- Behavior --------------------
@app.post("/behavior/record")
def record_behavior():
    data = request.get_json(silent=True) or {}
    roll_no = str(data.get("roll_no", "")).strip()

    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code

    with_teacher = str(data.get("with_teacher", "Neutral")).capitalize()
    with_classmates = str(data.get("with_classmates", "Neutral")).capitalize()
    note = data.get("note", "")

    behaviors.setdefault(roll_no, []).append({
        "With Teacher": with_teacher,
        "With Classmates": with_classmates,
        "Note": note
    })
    return jsonify({"message": "Behavior record added"})

@app.get("/behavior/<roll_no>")
def view_behavior(roll_no):
    r = str(roll_no)
    if r not in behaviors:
        return jsonify({"error": "No behavior records found"}), 404
    name = students.get(r, {}).get("Name", "")
    return jsonify({"student": name, "roll_no": r, "records": behaviors[r]})

# -------------------- Notifications --------------------
@app.post("/notify/parents")
def notify_parents():
    data = request.get_json(silent=True) or {}
    roll_no = str(data.get("roll_no", "")).strip()
    if not roll_no:
        return jsonify({"error": "roll_no is required"}), 400

    ok, resp, code = ensure_student(roll_no)
    if not ok:
        return resp, code

    day = str(data.get("day", "")).strip()
    date = str(data.get("date", "")).strip()
    to = data.get("to")
    preview_only = bool(data.get("preview_only", False))

    if isinstance(to, str):
        recipients = [to.strip()]
    elif isinstance(to, list):
        recipients = [x.strip() for x in to if isinstance(x, str) and x.strip()]
    else:
        recipients = list(students[roll_no].get("ParentEmails", []))

    if not recipients and not preview_only:
        return jsonify({"error": "No parent email configured. Provide 'to' or set 'ParentEmails' for the student."}), 400

    body = compile_student_update(roll_no, day or None, date or None)
    subject = f"Update for {students[roll_no].get('Name','Student')} (Roll {roll_no})"

    if preview_only:
        return jsonify({"message": "Preview generated (email not sent).", "subject": subject, "body": body, "to": recipients})

    success, err = send_email(recipients, subject, body)
    if not success:
        return jsonify({"error": "Failed to send email", "details": err}), 500

    return jsonify({"message": "Email sent", "to": recipients, "subject": subject})

# -------------------- SMTP Health --------------------
@app.get("/smtp/health")
def smtp_health():
    status = _smtp_config_status()
    if not status["configured"]:
        return jsonify({"status": "not-configured", **status})

    do_test = str(request.args.get("test", "0")).strip().lower() in ("1", "true", "yes", "y")
    if not do_test:
        return jsonify({"status": "configured", **status})

    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", 587))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    use_ssl_flag = str(_env("SMTP_USE_SSL", "false")).strip().lower() == "true"
    timeout = int(_env("SMTP_TIMEOUT", 15))

    try:
        if use_ssl_flag or port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as server:
                code, resp = server.login(user, password)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                code, resp = server.login(user, password)
        return jsonify({
            "status": "ok",
            "connectivity": "ok",
            "server_code": int(code) if isinstance(code, int) else code,
            "server_resp": resp.decode() if isinstance(resp, (bytes, bytearray)) else resp
        })
    except smtplib.SMTPAuthenticationError as e:
        return jsonify({
            "status": "fail",
            "connectivity": "auth-failed",
            "smtp_code": getattr(e, "smtp_code", None),
            "smtp_error": e.smtp_error.decode() if isinstance(e.smtp_error, (bytes, bytearray)) else getattr(e, "smtp_error", str(e)),
        }), 401
    except Exception as e:
        return jsonify({"status": "fail", "connectivity": "error", "error": str(e)}), 500

# -------------------- Utility --------------------
@app.post("/reset")
def reset_all():
    """
    Clear all in-memory data. Optional ADMIN_TOKEN protection via:
      - Header: X-Admin-Token
      - Query:  ?token=
    """
    admin_token = _env("ADMIN_TOKEN")
    if admin_token:
        provided = request.headers.get("X-Admin-Token") or request.args.get("token")
        if provided != admin_token:
            return jsonify({"error": "Forbidden"}), 403

    students.clear(); timetable.clear(); attendance.clear(); diary.clear()
    shared_homework.clear(); daily_report.clear(); behaviors.clear()
    return jsonify({"message": "All data cleared"})

# -------------------- Main --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=(ENV != "production"))