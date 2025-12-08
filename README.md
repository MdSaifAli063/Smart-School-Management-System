# 🏫 Smart School Management System

[![status](https://img.shields.io/badge/status-active-brightgreen)](README.md) [![python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![flask](https://img.shields.io/badge/flask-%3E%3D1.1.2-orange)](https://flask.palletsprojects.com/) [![license](https://img.shields.io/badge/license-MIT-blueviolet)](LICENSE)

A lightweight, demo-friendly school management system built with Flask. Manage students, timetables, attendance, homework/diary, daily reports, behavior logs and parent notifications.

Why use this project?

- ✅ Quick to run — in-memory demo data for core features.
- 🧩 Teacher accounts persist in MongoDB (optional).
- 📣 Email preview & send via SMTP.
- 🔧 Minimal UI + simple REST endpoints for rapid prototyping.

### Preview
  

---

## Table of Contents

- Features 
- Architecture & Data Model
- Quick Start (local)
- Docker & Production
- API Examples
- Testing
- Troubleshooting
- Contributing
- License

---

## ✨ Features 

### 👩‍🏫 Teacher Authentication

- Register & login with email/password
- Passwords hashed with bcrypt
- Sessions persisted in MongoDB (optional)
- Token-based API access

### 🧑‍🎓 Student Management

- Add/update/list students
- Store parent contact emails
- Blood group, address, parent names
- Auto-create empty diary on student add

### 📅 Timetable Management

- Create timetable per grade/day
- Auto-insert breaks (short, lunch, games)
- **Immutable once saved** (locks to prevent accidental changes)
- View by grade or grade+day

### ✅ Attendance Tracking

- Mark attendance per student/day/subject
- Auto-fill from timetable subjects
- Store Present/Absent/N/A status
- View attendance history by student

### 📝 Homework & Diary

- Set shared homework per day (all students)
- Per-student diary with completion tracking
- Mark homework Pending/Completed
- View diary by student or student+day

### 🍱 Daily Reports

- Log lunch + daily activities per student/date
- Store activity + remarks
- View report history

### ⭐ Behavior Tracking

- Record behavior with teacher/classmates ratings
- Add notes/comments
- View all records per student

### 📧 Parent Notifications (SMTP)

- Generate formatted email with student summary
- Include attendance, diary, daily report, behavior
- **Preview mode** to inspect before sending
- Optional custom recipient list or use saved parent emails

### 🔧 Admin Tools

- `/reset` endpoint to clear all in-memory data
- Protected by optional ADMIN_TOKEN
- `/healthz` for app health check
- `/smtp/health` for email config status

---

## Architecture & Data Model

### High-level Architecture

```
┌─────────────────────────────────────────┐
│          Browser / Client               │
│  (home.html, index.html, login.html)   │
└────────────────┬────────────────────────┘
                 │ HTTP / REST
┌────────────────▼────────────────────────┐
│     Flask App (app.py)                  │
│  - Auth routes                          │
│  - Student / Timetable / Attendance API │
│  - Homework / Diary / Reports / Behavior│
│  - Notifications (SMTP)                 │
└────────────────┬───────────┬────────────┘
                 │           │
        ┌────────▼──┐   ┌────▼──────────┐
        │  MongoDB  │   │  SMTP Server  │
        │ (Teachers)│   │ (Email Send)  │
        └───────────┘   └───────────────┘
```

### Data Model (in-memory + MongoDB)

- **students**: { roll_no: { Name, Grade, ParentEmails[], ... } }
- **timetable**: { grade_key: { Day: [ { Time, Subject, Teacher, Room }, ... ] } }
- **attendance**: { roll_no: { Day: [ { Subject, Status } ] } }
- **diary**: { roll_no: { Day: [ { Subject, Homework, Status } ] } }
- **shared_homework**: { Day: [ { Subject, Homework } ] }
- **daily_report**: { roll_no: { date: { Lunch, Activities[] } } }
- **behaviors**: { roll_no: [ { With Teacher, With Classmates, Note } ] }
- **teachers** (Mongo): { \_id, name, email, password(bcrypt) }

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

2. Create `.env` (DO NOT commit):

   ```
   FLASK_SECRET_KEY=change-me-in-production
   MONGODB_URI=mongodb://localhost:27017
   MONGODB_DB=school_app
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_USER=user@example.com
   SMTP_PASS=supersecret
   SMTP_FROM=notifications@example.com
   SMTP_USE_SSL=false
   ADMIN_TOKEN=your-secret-admin-token
   ENV=development
   ```

3. Run:

   ```bash
   python app.py
   ```

4. Open:
   - Public landing: http://localhost:5000/
   - Dashboard (requires login): http://localhost:5000/index
   - Health check: http://localhost:5000/healthz

---

## 📦 Docker & Production

**Dockerfile:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FLASK_ENV=production
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
```

**docker-compose.yml (dev):**

```yaml
version: "3.8"
services:
  app:
    build: .
    ports: ["5000:5000"]
    env_file: .env
    depends_on: ["mongo"]
  mongo:
    image: mongo:6
    volumes: ["mongodata:/data/db"]
volumes:
  mongodata:
```

**Production notes:**

- Use gunicorn or uvicorn + reverse proxy (nginx).
- Enable HTTPS and secure cookies.
- Store secrets in env or secret manager.
- Move school data to persistent DB (Mongo).
- Set `FLASK_ENV=production` and `DEBUG=False`.

---

## 🧭 API Examples (with sample responses)

**1. Register teacher**

```http
POST /api/auth/register
Content-Type: application/json

{
  "name": "Ms. Iyer",
  "email": "iyer@example.com",
  "password": "s3cret123"
}
```

Response (201):

```json
{ "ok": true, "id": "605c2e5f..." }
```

**2. Add student**

```http
POST /students
{
  "roll_no": "101",
  "name": "Alice Kumar",
  "age": "10",
  "grade": "4A",
  "gender": "Female",
  "fathers_name": "Rohan",
  "mothers_name": "Meera",
  "blood_group": "A+",
  "address": "123 Maple St",
  "parent_email": "mom@example.com"
}
```

Response (201):

```json
{ "message": "Student added", "student": { "Name": "Alice Kumar", "ParentEmails": ["mom@example.com"], ... } }
```

**3. Preview notification**

```http
POST /notify/parents
{ "roll_no": "101", "preview_only": true }
```

Response:

```json
{
  "message": "Preview generated (email not sent).",
  "subject": "Update for Alice Kumar (Roll 101)",
  "body": "Student Update\nName: Alice Kumar\nRoll No: 101\n...",
  "to": ["mom@example.com"]
}
```

**4. Send notification**

```http
POST /notify/parents
{ "roll_no": "101" }
```

Response (success):

```json
{
  "message": "Email sent",
  "to": ["mom@example.com"],
  "subject": "Update for Alice Kumar (Roll 101)"
}
```

---

## 🧪 Testing

**Setup test environment:**

```bash
pip install pytest pytest-flask
```

**Run tests:**

```bash
pytest tests/ -v
```

**Sample test structure:**

```python
# tests/test_auth.py
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_register(client):
    res = client.post('/api/auth/register', json={
        'name': 'Test', 'email': 'test@example.com', 'password': 'pass123'
    })
    assert res.status_code == 201
    assert res.json['ok']
```

---

## 🛠 Troubleshooting

### SMTP Issues

- Check `/smtp/health` endpoint (add `?test=1` to attempt connection).
- Verify SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env.
- For 2FA: use app-specific passwords provided by your email provider.
- TLS vs SSL: use port 465 + SMTP_USE_SSL=true or port 587 + STARTTLS.

### MongoDB Connection Issues

- Ensure MongoDB is running locally: `mongod` or use Atlas connection string.
- Check MONGODB_URI syntax (should start with `mongodb://` or `mongodb+srv://`).
- Verify credentials if using Atlas.

### Port Already in Use

- Change PORT in .env or pass `PORT=5001 python app.py`.

### Demo Data Lost After Restart

- In-memory stores clear on restart. Use persistent DB for production.

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork → branch → PR to main
2. Add tests for new features
3. Follow PEP 8 style guide
4. Document API changes in README

---

## 📜 License

MIT © 2025

For questions, open an issue or contact the maintainer.
