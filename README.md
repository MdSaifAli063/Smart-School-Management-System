# 🏫 Smart School — Unified School Management

[![status](https://img.shields.io/badge/status-active-brightgreen)](README.md) [![python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![flask](https://img.shields.io/badge/flask-%3E%3D1.1.2-orange)](https://flask.palletsprojects.com/) [![license](https://img.shields.io/badge/license-MIT-blueviolet)](LICENSE)

A lightweight, demo-friendly school management system built with Flask. Manage students, timetables, attendance, homework/diary, daily reports, behavior logs and parent notifications.

Why use this project?

- ✅ Quick to run — in-memory demo data for core features.
- 🧩 Teacher accounts persist in MongoDB (optional).
- 📣 Email preview & send via SMTP.
- 🔧 Minimal UI + simple REST endpoints for rapid prototyping.

---

## ✨ Features

- Authentication for teachers (register/login)
- Student registry with parent contacts
- Timetable per grade (locked once saved)
- Attendance (auto-fill from timetable)
- Homework/diary + completion tracking
- Daily activity reports (lunch + activities)
- Behavior logs per student
- Email notifications with preview
- `/reset` endpoint to clear demo data (admin token optional)

---

## 🚀 Quick Start (local)

Prerequisites:

- Python 3.8+
- (Optional) MongoDB for teacher persistence

1. Clone and create virtualenv:

   ```bash
   git clone <repo> "d:/School Sheduler"
   cd "d:/School Sheduler"
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

2. Create a .env (DO NOT commit):

   ```
   FLASK_SECRET_KEY=change-me
   MONGODB_URI=mongodb://localhost:27017
   MONGODB_DB=school_app
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_USER=user@example.com
   SMTP_PASS=supersecret
   SMTP_FROM=notifications@example.com
   SMTP_USE_SSL=false
   ADMIN_TOKEN=some-admin-token
   ```

3. Run:

   ```bash
   python app.py
   ```

4. Open:
   - Public landing: http://localhost:5000/
   - Dashboard: http://localhost:5000/index (requires login)

---

## 🔑 Important env variables

- FLASK_SECRET_KEY — session secret
- MONGODB_URI, MONGODB_DB — Mongo connection (optional; local fallback exists)
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM — for email sending
- SMTP_USE_SSL — "true" or "false"
- ADMIN_TOKEN — protects /reset (optional)

---

## 🧭 Quick API examples

Preview generated email (no send):

```bash
curl -X POST http://localhost:5000/notify/parents \
  -H "Content-Type: application/json" \
  -d '{"roll_no":"101","preview_only":true}'
```

Send notification (SMTP must be configured):

```bash
curl -X POST http://localhost:5000/notify/parents \
  -H "Content-Type: application/json" \
  -d '{"roll_no":"101"}'
```

Auth:

- POST /api/auth/register -> { name, email, password }
- POST /api/auth/login -> { email, password }
- GET /api/auth/me -> session info

Reset demo data (admin):

```bash
curl -X POST "http://localhost:5000/reset?token=YOUR_ADMIN_TOKEN"
```

---

## 🔎 Health & Debug

- App health: GET /healthz
- SMTP config: GET /smtp/health (add ?test=1 to attempt login)

---

## 📝 Notes

- School data (students, timetables, diary, etc.) is in-memory for demo; restart clears it unless you persist elsewhere.
- Teacher accounts persist in MongoDB when MONGODB_URI is provided.
- Do not commit secrets — .gitignore includes env ignores.

---

## 🤝 Contributing

PRs and issues welcome. Keep changes focused and include tests when applicable.

---

## 📜 License

MIT © 2025

If you want Docker, CI badges or deployment snippets for a specific host, tell me which target and I’ll add them.
