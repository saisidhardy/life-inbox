# Life Inbox 📥

[![CI/CD Pipeline](https://github.com/saisidhardy/life-inbox/actions/workflows/ci.yml/badge.svg)](https://github.com/saisidhardy/life-inbox/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/Production%20Deployment-Render%20Online-009688.svg)](https://life-inbox.onrender.com)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57.svg)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/saisidhardy/life-inbox)

> **Capture first. Organize the whole inbox with AI when you are ready.**

🌐 **Primary Production Deployment:** [https://life-inbox.onrender.com](https://life-inbox.onrender.com)

Life Inbox is an AI-powered personal dashboard and second-brain productivity system. It lets you capture messy, unstructured notes, reminders, thoughts, checklists, and ideas at the speed of thought—then uses OpenAI (or an offline deterministic organizer) to turn your stream of notes into structured categories, actionable tasks, and a clear priority dashboard.

---

## ✨ Power Features

- **⚡ Instant Quick Capture**: Jot down thoughts with `Ctrl+Enter` or tap structured quick-capture templates:
  - 📞 **Meeting Note** (`#meeting with [Name]`)
  - 💡 **Idea** (`💡 #idea [Title]`)
  - 🛒 **Checklist** (`#checklist To Do / Buy`)
  - 📚 **Resource / Learning** (`📚 #learning`)
- **☑️ Interactive In-Note Checklists**: Write `- [ ] task` or `- [x] done`. Checkboxes render as interactive toggles; clicking a checkbox updates the note in the database in real-time.
- **🏷️ Smart Auto-Tagging (#tags)**: Any `#tag` written in a note becomes an interactive badge pill. Click any tag to filter your inbox. Top tags aggregate live on your Dashboard.
- **🔗 Safe URL Links & Code Blocks**: Web links are validated and rendered safely (strictly preventing XSS and attribute injection), and backticked text is rendered with monospaced code blocks.
- **💾 Data Ownership (Export & Import)**:
  - **Export to Markdown**: Download all notes and action items as a clean `.md` document ready for **Obsidian**, **Notion**, or **Apple Notes**.
  - **Export to JSON**: Complete database snapshot.
  - **Hardened Batch Import**: Paste multiple notes separated by `---` with single-transaction rollback on failure, note length validation, and automatic SQLite database backup before write.
- **🔒 Single-User Token Authentication**: Configurable `APP_TOKEN` protects all `/api/*` routes. Frontend prompts on 401, saves to `localStorage`, and provides a header quick-access Auth modal.
- **🛡️ AI Spend & Rate Protection**: Per-client sliding-window rate limiting and service-wide daily caps on `/api/analyze` to prevent runaway LLM costs.
- **🤖 Intelligent Inbox Organization**: Organizes all saved notes together using OpenAI into structured buckets, prioritized action items, and deduplicated to-dos.
- **⚡ Offline Fallback Engine**: Works 100% locally even without an OpenAI API key using a deterministic rule-based organization engine.
- **✅ Persistent Task Management**: Extracted action items become trackable tasks with full lifecycle support (`open`, `completed`, `dismissed`, `reopened`). Tasks preserve source links back to original notes and prevent duplication across re-analyses.
- **🎨 Modern Responsive UI**:
  - Dark / Light mode toggle with persistent local storage
  - Desktop sidebar + mobile-optimized bottom navigation
  - Dashboard analytics overview (total notes, pending tasks, analysis timestamps, tag cloud)
  - Inline note editing with keyboard support (`Escape` to cancel)
  - Smooth card animations, non-blocking toasts, and skeleton loading states
- **📱 PWA-Ready**: Includes web application manifest and vector icons for installability on mobile and desktop.
- **🐳 Production Ready**: Fully containerized with Docker, automated CI/CD pipeline via GitHub Actions, and 1-click Render blueprint with persistent disk.

---

## ⚙️ Environment Variables

Configure application settings via environment variables or a `.env` file (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_TOKEN` | Recommended (Prod) | *(empty/disabled)* | Secret token protecting all `/api/*` endpoints except `/api/health`. Auto-generated on Render. |
| `DATABASE_URL` | No | `sqlite:///data/life_inbox.db` | SQLAlchemy database URL. |
| `OPENAI_API_KEY` | Optional | *(empty/offline)* | API key for OpenAI analysis. Falls back to offline deterministic rule engine if unset. |
| `OPENAI_MODEL` | No | `gpt-5-mini` | OpenAI chat completion model name. |
| `ANALYZE_RATE_LIMIT_PER_MINUTE` | No | `5` | Sliding-window request cap per client IP on `/api/analyze`. |
| `ANALYZE_DAILY_CAP` | No | `50` | Service-wide daily spend cap for `/api/analyze`. |
| `PORT` | No | `8000` | HTTP port for the web server. Auto-detected in Docker & PaaS. |

---

## 🚀 Quick Start (Local Development)

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

### 3. Optional: Configure Environment

```bash
cp .env.example .env
# Edit .env with your preferred APP_TOKEN and OPENAI_API_KEY
```

### 4. Start the Application

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

---

## 🌐 Production Deployment

### Option 1: Render Blueprint (Primary Production Deployment)

Deploy a resilient, production-ready instance with a persistent SQLite disk in one click:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/saisidhardy/life-inbox)

**How it works:**
- Render automatically parses [`render.yaml`](render.yaml).
- Provisons a Python 3.12 service with persistent disk mounted at `/opt/render/project/src/data` (1 GB).
- Automatically applies database migrations (`alembic upgrade head`) on each build.
- Automatically generates a cryptographically secure `APP_TOKEN` so your instance is protected immediately upon launch.
- Configures health check monitoring on `/api/health`.

### Option 2: Production Docker Container

Run Life Inbox with Docker and a persistent volume mount:

```bash
# 1. Build the Docker image
docker build -t life-inbox:latest .

# 2. Run the container with persistent data volume and environment variables
docker run -d \
  --name life-inbox-app \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e APP_TOKEN="your-secure-token" \
  -e OPENAI_API_KEY="sk-..." \
  -e ANALYZE_RATE_LIMIT_PER_MINUTE=5 \
  -e ANALYZE_DAILY_CAP=50 \
  --restart unless-stopped \
  life-inbox:latest
```

The container automatically runs database migrations on startup, binds to `$PORT` (default 8000), and executes periodic health checks via `HEALTHCHECK`.

### Option 3: Development Cloudflare Tunnel (Dev / Demo Only)

For rapid local testing without opening router ports or deploying to cloud infrastructure:

```bash
# 1. Start local server
python -m uvicorn app.main:app --port 8000

# 2. In a separate terminal, launch a temporary Cloudflare tunnel
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the generated `https://*.trycloudflare.com` URL to test your local instance on mobile or share with collaborators.

---

## 🧪 Automated Testing

Life Inbox includes 76 automated tests across unit, integration, migration, and security suites:

```bash
# Run the entire test suite
python -m pytest tests/ -v

# Run linting
python -m ruff check app/ tests/ scripts/
```

Test coverage includes:
- **API Suite** (`tests/test_api.py`): Item creation, case-insensitive search, updates, markdown/JSON export, batch import, and AI mock validation.
- **Migration Suite** (`tests/test_migrations.py`): Schema evolution (0001–0006), legacy database adoption, and task consolidation.
- **Security Suite** (`tests/test_security.py`): Single-user token auth, header/query extraction, rate-limiting sliding windows, daily spend caps, XSS payload neutralization, import length bounds, and transactional rollbacks.

All tests run completely offline without consuming external API credits.

---

## 📁 Project Architecture

```text
life-inbox/
├── .github/
│   └── workflows/ci.yml       # GitHub Actions CI/CD (matrix test + Docker build/health check)
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI routes, security & structured logging middleware
│   ├── auth.py                # APP_TOKEN verification, bearer/header parsing, constant-time digest
│   ├── rate_limit.py          # Sliding-window rate limiting & daily spend cap
│   ├── database.py            # SQLAlchemy models, SQLite engine, batch imports & backup rotation
│   ├── organizer.py           # AI prompt orchestration & deterministic fallback engine
│   ├── schemas.py             # Pydantic validation schemas
│   ├── static/
│   │   ├── app.js             # Reactive frontend logic, checklists, tags, auth prompt, & state
│   │   ├── styles.css         # Complete CSS custom property theming, templates, & animations
│   │   ├── favicon.svg        # Vector app favicon
│   │   ├── icon-192.svg       # PWA icon 192x192
│   │   ├── icon-512.svg       # PWA icon 512x512
│   │   └── manifest.json      # Web app manifest for PWA installation
│   └── templates/
│       └── index.html         # Semantic HTML5 template with quick templates & auth config
├── migrations/
│   ├── env.py                 # Alembic environment configuration
│   └── versions/              # Applied database migrations (0001 - 0006)
├── tests/
│   ├── test_api.py            # API endpoint integration, export, import, & error tests
│   ├── test_migrations.py     # Database schema evolution and rollback tests
│   └── test_security.py       # Authentication, rate limiting, XSS, & import rollback tests
├── Dockerfile                 # Production multi-stage container with dynamic port & migrations
├── .dockerignore
├── Procfile                   # Process file for PaaS deployment
├── render.yaml                # Render Infrastructure-as-Code Blueprint with persistent disk
├── pyproject.toml             # Modern Python project configuration
├── requirements.txt           # Python package dependencies
└── README.md
```

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
