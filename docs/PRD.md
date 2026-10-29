# Product Requirements Document (PRD)

**Product Name:** Life Inbox  
**Target Profile:** AI Product Manager / AI Technical Founder  
**Stage:** Production v1.0  
**Repository:** [https://github.com/saisidhardy/life-inbox](https://github.com/saisidhardy/life-inbox)  
**Live Production URL:** [https://life-inbox.onrender.com](https://life-inbox.onrender.com)  

---

## 1. Executive Summary

Personal knowledge management tools suffer from a fundamental paradox: **the more cognitive overhead required to categorize, tag, and file a note upfront, the less likely a user is to capture it in the moment**. When friction is introduced at capture time, users default to ephemeral scratchpads (Apple Notes, Slack DMs to oneself, text files), fragmenting knowledge and losing actionable commitments.

**Life Inbox** solves this problem by decoupling **capture** from **organization**:
1. Users capture thoughts, meeting snippets, grocery lists, and brain dumps in raw, unstructured text with zero friction.
2. An asynchronous AI processing layer automatically extracts taxonomy categories, hashtags, prioritized action items, and temporal deadlines into validated JSON schemas.
3. Natural-language retrieval ("Ask Your Inbox") answers queries with exact citations to source notes without requiring manual folder hierarchies.
4. Embedded AI telemetry measures prompt token consumption, latency, and estimated cost per call to maintain strict unit economics.

---

## 2. Problem Statement & User Personas

### 2.1 The Problem
- **Cognitive Filing Burden:** Traditional tools (Notion, Obsidian, Jira) require users to choose databases, select properties, and organize folders before writing. This creates capture hesitation.
- **Action Item Decay:** To-do items embedded in unstructured notes ("Need to send pitch deck to Alex by Friday") get buried and forgotten.
- **Retrieval Blindspots:** Keyword search fails when users recall the concept or decision but not the exact phrase or date.
- **Uncontrolled AI Costs:** Prototype AI apps often lack token budgeting, latency tracing, and structured evaluation benchmarks, making them unviable for production.

### 2.2 Target Persona: The "High-Velocity Operator"
- **Role:** Startup Founders, Product Managers, Senior Engineers, and Knowledge Workers.
- **Behaviors:** Context-switches between 10+ projects daily; takes rapid notes during meetings; creates voice memos on the go.
- **Core Need:** A single trusted receptacle where capture is instant, and synthesis/action extraction happens autonomously with deterministic fallback.

---

## 3. Goals & Non-Goals

### 3.1 Primary Goals (In Scope)
- **Frictionless Capture:** Capture raw text or templates in $< 100\text{ ms}$ with keyboard-first shortcuts (`Ctrl+Enter`).
- **Structured Auto-Processing:** Transform unstructured text into validated Pydantic objects (`category`, `suggested_tags`, `extracted_tasks`, `summary`) with retry and fallback guarantees.
- **Grounded Natural-Language Search:** Answer ad-hoc questions over inbox notes with explicit markdown citations (`[Note #ID]`).
- **Deterministic Offline Mode:** 100% of core note-taking, search, and rule-based heuristics function without internet or OpenAI API keys.
- **Rigorous Evaluation Suite:** Benchmark prompt performance against a 28-sample dataset across task precision, recall, priority accuracy, due-date accuracy, latency, and cost.
- **Hardened Single-Tenant Security:** Token authentication (`APP_TOKEN`), sliding-window rate limiting, strict XSS sanitization, and atomic transactional database backups.

### 3.2 Non-Goals (Explicitly Out of Scope for v1.0)
- **Multi-Tenant Team Collaboration:** Multi-seat RBAC, team workspaces, and real-time multiplayer editing add architectural bloat before single-user PMF is validated.
- **Heavy Vector Database Infrastructure:** Pinecone, Qdrant, or Chroma require external operational dependencies. For individual inboxes ($< 50\text{k}$ notes), pure-Python BM25 / token scoring provides $< 5\text{ ms}$ retrieval with zero infrastructure overhead.
- **Arbitrary File / PDF Attachments:** v1.0 focuses exclusively on high-speed text, markdown, and structured checklist processing.
- **Mobile Native App:** A responsive PWA with offline caching fulfills mobile quick-capture requirements without App Store review cycles.

---

## 4. Product Capabilities & Functional Specifications

### 4.1 Frictionless Capture & Real-time Formatting
- **Keyboard Shortcuts:** `Ctrl+Enter` instantly saves notes.
- **Quick-Capture Templates:** One-click insertion for Meeting Notes, Ideas, Checklists, and Learning items.
- **Interactive In-Note Checklists:** Syntax `- [ ] task` renders as an interactive checkbox; toggling updates database state without note rewriting.
- **Safe Linkification & Sanitization:** All raw text is strictly escaped via HTML entities before regex linkification to eliminate XSS vectors.

### 4.2 Structured AI Auto-Processing Pipeline
- **Endpoint:** `POST /api/items/{id}/auto-process` and `POST /api/process-note`
- **Taxonomy Categories:** `Work`, `Personal`, `Shopping`, `Ideas`, `Finance`, `Health`.
- **Task Extraction Schema:**
  ```json
  {
    "category": "Work",
    "suggested_tags": ["#work", "#roadmap"],
    "extracted_tasks": [
      {
        "title": "Send updated pitch deck to Alex",
        "priority": "High",
        "due_date": "Friday"
      }
    ],
    "summary": "Meeting with Sarah & Mark regarding Q4 mobile redesign roadmap."
  }
  ```
- **Error Handling & Fallback:** Validated against `NoteAutoAnalysis` Pydantic model. If the provider returns malformed JSON, the system triggers one automatic retry; if parsing fails again, it falls back to a deterministic regex engine without throwing a 500 error.

### 4.3 "Ask Your Inbox" (Natural-Language Retrieval)
- **Endpoint:** `POST /api/ask`
- **Retrieval Engine:** Pure-Python BM25 ranker over user notes. Scores term frequency, document frequency, and note freshness.
- **Citation Grounding:** Synthesizes answer using top-$k$ notes ($k=5$) and formats exact citations: `[Note #4] ("Meeting with Sarah...")`. Prevents ungrounded model hallucinations.

### 4.4 Weekly AI Digest
- **Endpoint:** `GET /api/digest/weekly`
- **Output:** Identifies pending high-priority action items, notes untouched for $> 7\text{ days}$ (stale items), recurring tag themes, and recommends 3 concrete focus actions for the upcoming week.

### 4.5 AI Telemetry & Observability
- **Database Table:** `ai_metrics`
- **Tracked Parameters:** `operation`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `estimated_cost_usd`, `status`.
- **Dashboard Widget:** Live summary displaying total calls, token count, cumulative cost ($USD$), and average latency.

---

## 5. Non-Functional Specifications

| Category | Specification | Verification Method |
|---|---|---|
| **API Latency** | Local SQLite CRUD operations $< 15\text{ ms}$; BM25 search $< 10\text{ ms}$ | Automated test benchmarks |
| **Availability** | Production deploy on Render with persistent disk & zero-downtime healthcheck | Render HTTP monitor on `/api/health` |
| **Security** | Constant-time token verification (`APP_TOKEN`) on `/api/*` routes | Suite in `tests/test_security.py` |
| **XSS Hardening** | Neutralize `<script>`, `onerror=`, and `javascript:` URLs | Automated browser payload tests |
| **Cost Protection** | Sliding window cap (5 req/min) & daily cap (50 req/day) per client | In-memory limiter tests |
| **Portability** | Full JSON / Markdown export; hardened batch import with pre-write DB snapshot | Import/Export test cases |

---

## 6. Evaluation Framework & Quality Targets

To ensure continuous model reliability across prompt or model upgrades, all releases must be validated against `evals/dataset.json` (28 diverse test notes).

| Metric | Baseline Target | Production Target (Strategy B) | Achieved Result |
|---|---|---|---|
| **Valid JSON Rate** | $\ge 95\%$ | $100\%$ | **100.0%** |
| **Category Accuracy** | $\ge 80\%$ | $\ge 90\%$ | **96.4%** |
| **Task Precision** | $\ge 80\%$ | $\ge 85\%$ | **90.2%** |
| **Task Recall** | $\ge 50\%$ | $\ge 85\%$ | **90.2%** |
| **Task F1 Score** | $\ge 0.60$ | $\ge 0.85$ | **0.9024** |
| **Priority Accuracy** | $\ge 60\%$ | $\ge 80\%$ | **86.5%** |
| **Due Date Accuracy** | $\ge 50\%$ | $\ge 75\%$ | **83.8%** |

---

## 7. Strategic Product Roadmap

### v1.1: Audio Quick-Capture & Local Speech-to-Text
- Integrate browser Web Audio API with local/server Whisper transcription.
- Voice memo auto-capture with ambient noise filtering.

### v1.2: Calendar & Email Bi-Directional Webhooks
- Webhook trigger for calendar events to auto-generate pre-meeting notes.
- Dispatch extracted high-priority tasks to external task managers (Todoist / Linear) via webhook.

### v2.0: Multi-Modal Contextual Recall
- Image & diagram OCR capture.
- Vector semantic embedding layer hybrid-indexed with BM25 for $> 500\text{k}$ note scale.
