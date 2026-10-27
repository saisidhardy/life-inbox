# Life Inbox 📥

[![CI/CD Pipeline](https://github.com/saisidhardy/life-inbox/actions/workflows/ci.yml/badge.svg)](https://github.com/saisidhardy/life-inbox/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57.svg)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/saisidhardy/life-inbox)

> **Capture first. Organize the whole inbox with AI when you are ready.**

Life Inbox is an AI-powered personal dashboard and productivity system. It lets you capture messy, unstructured notes, reminders, thoughts, and ideas at the speed of thought—then uses OpenAI (or an offline deterministic organizer) to turn your stream of notes into structured categories, actionable tasks, and a clear priority dashboard.

---

## ✨ Features

- **⚡ Instant Quick Capture**: Jot down thoughts, tasks, and ideas with a single click or keyboard shortcut (`Ctrl+Enter`).
- **🤖 Intelligent Inbox Organization**: Organizes all saved notes together using OpenAI into structured buckets, prioritized action items, and deduplicated to-dos.
- **🛡️ Offline Fallback Mode**: Works 100% locally even without an OpenAI API key using a deterministic rule-based organization engine.
- **✅ Persistent Task Management**: Extracted action items become trackable tasks with full lifecycle support (`open`, `completed`, `dismissed`, `reopened`). Tasks preserve source links back to original notes and prevent duplication across re-analyses.
- **🔍 Fast Search & Filter**: Real-time multi-attribute search across raw text, categories, priority levels, and processing statuses with URL state synchronization.
- **🎨 Modern Responsive UI**:
  - Dark / Light mode toggle with persistent local storage
  - Desktop sidebar + mobile-optimized bottom navigation
  - Dashboard analytics overview (total notes, pending tasks, analysis timestamps)
  - Inline note editing with keyboard support (`Escape` to cancel)
  - Smooth card animations and non-blocking toast notifications
  - Skeleton loading states and clean empty-state illustrations
- **📱 PWA-Ready**: Includes web application manifest and vector icons for installability on mobile and desktop.
- **🐳 Production Ready**: Fully containerized with Docker, automated CI/CD pipeline via GitHub Actions, and 1-click cloud deployment.

---

## 🚀 Quick Start

### 1. Clone & Set Up

```bash
# Clone the repository
git clone https://github.com/saisidhardy/life-inbox.git
cd life-inbox

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Database Migrations

Life Inbox uses SQLite by default stored in `data/life_inbox.db`:

```bash
python -m alembic upgrade head
```

### 3. Optional: Configure OpenAI

If you want AI analysis instead of the deterministic fallback engine, set your API key:

```bash
# Linux / macOS
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-5-mini"

# Windows (PowerShell)
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_MODEL="gpt-5-mini"
```

### 4. Start the Application

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

---

## 🐳 Docker Deployment

Run Life Inbox anywhere using Docker in a single command:

```bash
# Build the Docker image
docker build -t life-inbox .

# Run the container with persistent data storage
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e OPENAI_API_KEY="your-optional-key" \
  --name life-inbox-app \
  life-inbox
```

Access the app at `http://localhost:8000`.

---

## 🌐 Cloud Hosting & Deployment

### Option 1: Render (Recommended - Free Tier)

1. Click the button below:

   [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/saisidhardy/life-inbox)

2. Connect your GitHub account and select this repository.
3. Render automatically detects `render.yaml` with:
   - Python 3.12 environment
   - Automatic migration execution (`alembic upgrade head`)
   - Persistent disk mounted at `/app/data`
   - Health check endpoint `/api/health`
4. (Optional) Provide your `OPENAI_API_KEY` in environment variables.
5. Click **Create Web Service**. Your app is live with free SSL!

### Option 2: Railway / Fly.io / Koyeb

Life Inbox contains a `Procfile` and `Dockerfile` making it compatible out-of-the-box with any modern PaaS:

```bash
# Railway
railway up

# Fly.io
fly launch
```

---

## 🧪 Automated Testing

Life Inbox features a comprehensive 56-test regression and migration suite:

```bash
python -m pytest tests/ -v
```

All tests execute against isolated in-memory or temporary SQLite databases and run entirely offline without consuming external API credits.

---

## 📁 Project Architecture

```text
life-inbox/
├── .github/
│   └── workflows/ci.yml       # GitHub Actions CI/CD pipeline
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI routes, middleware, and entrypoint
│   ├── database.py            # SQLAlchemy models, SQLite engine, query functions
│   ├── organizer.py           # AI prompt orchestration & deterministic fallback engine
│   ├── schemas.py             # Pydantic validation schemas
│   ├── static/
│   │   ├── app.js             # Modern reactive frontend logic & state management
│   │   ├── styles.css         # Complete CSS custom property theming & animations
│   │   ├── favicon.svg        # Vector app favicon
│   │   ├── icon-192.svg       # PWA icon 192x192
│   │   ├── icon-512.svg       # PWA icon 512x512
│   │   └── manifest.json      # Web app manifest for PWA installation
│   └── templates/
│       └── index.html         # Semantic HTML5 application template
├── migrations/
│   ├── env.py                 # Alembic environment configuration
│   └── versions/              # Applied database migrations (0001 - 0006)
├── tests/
│   ├── test_api.py            # API endpoint integration and error tests
│   └── test_migrations.py     # Database schema evolution and rollback tests
├── Dockerfile                 # Multi-stage container definition
├── .dockerignore
├── Procfile                   # Process file for PaaS deployment
├── render.yaml                # Render Infrastructure-as-Code Blueprint
├── pyproject.toml             # Modern Python project configuration
├── requirements.txt           # Python package dependencies
└── README.md
```

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
