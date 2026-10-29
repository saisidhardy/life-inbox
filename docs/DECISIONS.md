# Architecture Decision Records (ADR)

This log documents the key architectural choices, strategic tradeoffs, and deliberately rejected alternatives in **Life Inbox**.

---

## Index of Decisions

- [ADR-001: SQLite with Persistent Disk vs Managed PostgreSQL](#adr-001-sqlite-with-persistent-disk-vs-managed-postgresql)
- [ADR-002: Pure-Python BM25 Ranker vs Heavy Vector Database](#adr-002-pure-python-bm25-ranker-vs-heavy-vector-database)
- [ADR-003: Provider Abstraction with Deterministic Offline Fallback](#adr-003-provider-abstraction-with-deterministic-offline-fallback)
- [ADR-004: Two-Tier Schema Validation and Self-Healing Fallback](#adr-004-two-tier-schema-validation-and-self-healing-fallback)
- [ADR-005: Single-User Token Authentication (`APP_TOKEN`)](#adr-005-single-user-token-authentication-app_token)
- [ADR-006: Embedded AI Telemetry at the Persistence Layer](#adr-006-embedded-ai-telemetry-at-the-persistence-layer)
- [ADR-007: Defense-in-Depth HTML Sanitization over Heavy Libraries](#adr-007-defense-in-depth-html-sanitization-over-heavy-libraries)
- [ADR-008: Pre-Write Database Snapshot for Batch Imports](#adr-008-pre-write-database-snapshot-for-batch-imports)

---

## ADR-001: SQLite with Persistent Disk vs Managed PostgreSQL

### Context
A note-taking system needs fast writes, minimal operational complexity, and durable storage across restarts. Managed relational databases (e.g. AWS RDS, Render Postgres) introduce network hops, higher monthly baseline costs ($7–$15/mo), and connection pool management overhead.

### Decision
Use **SQLite** with Write-Ahead Logging (WAL enabled) mounted on a persistent disk volume (`/opt/render/project/src/data`).

### Consequences & Tradeoffs
- **Pros:** Zero network latency for reads/writes ($< 1\text{ ms}$ query latency), zero monthly database infrastructure bill, trivial point-in-time file backups (`sqlite3` / file copy), zero connection pool limits.
- **Cons:** Single-writer limitation. Unsuitable for multi-region concurrent writes, which is an accepted non-goal for a personal second brain.

---

## ADR-002: Pure-Python BM25 Ranker vs Heavy Vector Database

### Context
To support the "Ask Your Inbox" natural-language retrieval feature, we evaluated whether to integrate a vector database (Pinecone, Chroma, Qdrant) with OpenAI embedding models (`text-embedding-3-small`).

### Decision
Implement an in-memory, pure-Python **BM25 ranker** with text normalization and reciprocal document frequency scoring.

### Consequences & Tradeoffs
- **Pros:** Zero additional binary or cloud dependencies. Requires zero embedding generation cost per note captured ($\$0.00$ ingestion cost). Query latency is $< 3\text{ ms}$ over typical personal volumes ($< 20\text{k}$ notes). Operates 100% offline.
- **Cons:** Does not capture cross-vocabulary semantic synonyms (e.g., searching "automobile" when the note says "car") unless tokens overlap or are re-queried. Accepted because users search notes using vocabulary they authored.

---

## ADR-003: Provider Abstraction with Deterministic Offline Fallback

### Context
Relying strictly on an external LLM provider creates single-point-of-failure risks during provider outages, rate limit exhaustions, or local development without API keys.

### Decision
Define a uniform `BaseAIProvider` interface with two concrete implementations:
1. `OpenAIProvider`: Calls OpenAI chat completions with structured JSON formatting.
2. `MockAIProvider`: High-accuracy offline heuristic analyzer driven by regex action-verb parsing and date normalization.
Factory function `get_ai_provider()` automatically detects API key presence and gracefully degrades to `MockAIProvider`.

### Consequences & Tradeoffs
- **Pros:** The entire test suite and CI pipeline run in $< 10\text{ seconds}$ without network access or consuming API tokens. The application remains fully functional during airplane/offline mode.
- **Cons:** Heuristics require ongoing tuning to capture conversational speech nuances (mitigated by our 28-sample evaluation benchmark).

---

## ADR-004: Two-Tier Schema Validation and Self-Healing Fallback

### Context
LLMs frequently produce invalid JSON, subtle syntax truncations, or unrequested markdown code wrappers (` ```json `), resulting in runtime 500 errors if parsed naively.

### Decision
Enforce a two-tier extraction pipeline:
1. **Pydantic Validation:** Output is parsed through strict models (`NoteAutoAnalysis`, `ExtractedTask`).
2. **Self-Healing Retry & Fallback:** If the first completion fails validation, trigger one schema-enforced retry. If the retry fails, parse via the offline deterministic fallback.

### Consequences & Tradeoffs
- **Pros:** Guaranteed $100\%$ valid JSON rate. Zero 500 Internal Server Errors exposed to users due to model malformations.
- **Cons:** In rare retry cases, latency increases by $1\times$ LLM roundtrip.

---

## ADR-005: Single-User Token Authentication (`APP_TOKEN`)

### Context
The application is deployed to a public URL (`https://life-inbox.onrender.com`). Exposing unsecured CRUD routes allows unauthorized scrapers or malicious payload injections. Traditional OAuth2 / multi-user sign-up stacks add unnecessary user friction.

### Decision
Implement a single-tenant bearer/header token authentication model (`APP_TOKEN`):
- All `/api/*` endpoints (except `/api/health`) require authentication.
- Supports `Authorization: Bearer <token>`, `X-App-Token: <token>`, or `?token=<token>`.
- Verification uses `hmac.compare_digest` to prevent timing attacks.
- Frontend prompts user once via an Auth modal and caches securely in `localStorage`.

### Consequences & Tradeoffs
- **Pros:** Instant setup via single environment variable; eliminates user database tables and password recovery infrastructure; completely blocks unauthenticated scrapers.
- **Cons:** Single-tenant only (by design for this product stage).

---

## ADR-006: Embedded AI Telemetry at the Persistence Layer

### Context
AI-powered products must track unit economics (tokens per operation, cost per user, latency percentiles) to avoid unexpected bills and monitor model performance regressions.

### Decision
Create a dedicated `ai_metrics` SQLite table managed via Alembic migrations. Every AI invocation (`auto_process`, `ask_inbox`, `weekly_digest`) records prompt tokens, completion tokens, latency ($ms$), calculated USD cost, and status.

### Consequences & Tradeoffs
- **Pros:** Complete transparency in the UI dashboard. Live unit economics available via `GET /api/ai/metrics`. Facilitates ROI decisions on prompt optimizations.
- **Cons:** Minor disk write per AI call ($< 1\text{ ms}$).

---

## ADR-007: Defense-in-Depth HTML Sanitization over Heavy Libraries

### Context
Users paste arbitrary snippets into notes, including markdown links, code blocks, and checklists. Naive `innerHTML` rendering introduces cross-site scripting (XSS) risks.

### Decision
Implement a strict two-pass rendering pipeline in vanilla JavaScript:
1. **Pass 1 (Escaping):** Pass all untrusted text through `esc()` (`replace(/[&<>"']/g)` to HTML entities).
2. **Pass 2 (Controlled Formatting):** Apply strict regular expressions exclusively for checkboxes, backtick code snippets, and verified `http(s)://` URLs (rejecting `javascript:`, `data:`, or event handler injection).

### Consequences & Tradeoffs
- **Pros:** Zero external client-side dependencies (e.g. DOMPurify). Fast, predictable, and audited with explicit XSS automated test suites.
- **Cons:** Rich HTML markup (tables, embedded iframes) is unsupported (aligned with product goals).

---

## ADR-008: Pre-Write Database Snapshot for Batch Imports

### Context
Users importing bulk notes from other systems (Obsidian, Notion, Google Keep) may submit corrupt or oversized payloads that could pollute or corrupt existing state midway through an import.

### Decision
1. Limit imports to a maximum of $100$ notes and $50,000$ characters per note.
2. Execute a full point-in-time SQLite database snapshot (`life_inbox_pre_import_*.db`) before executing writes.
3. Wrap all insertions in a single atomic database transaction with rollback on failure.

### Consequences & Tradeoffs
- **Pros:** Guaranteed zero partial-import states. Users have a physical backup file on disk in case of accidental overwrite.
- **Cons:** Import operation requires disk space equal to one database copy ($< 10\text{ MB}$ for personal usage).
