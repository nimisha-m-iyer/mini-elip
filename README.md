# Mini-Elip: AI Job-Matching Agent on Telegram

Mini-Elip is a Telegram bot that reads your resume, searches a continuously updated index of real job postings, and returns 3 matches with a short reason for each. It learns from 👍/👎 feedback, remembers your preferences, answers follow-up questions through a tool-using LLM agent, and can send an opt-in daily digest.

It is a portfolio project built end to end on free tiers and open-weight models.

- **Live bot:** [@Nimisha_jobmatch_bot](https://t.me/Nimisha_jobmatch_bot) on Telegram
- **API:** https://mini-elip.onrender.com (`/healthz`, `/health`, `/search`)

> The live service runs on Render's free tier, so it sleeps when idle. The first message after a quiet period can take about a minute while it wakes up and loads its models.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [Tech stack](#tech-stack)
4. [Project status](#project-status)
5. [Bot commands](#bot-commands)
6. [How it works](#how-it-works)
7. [Repository structure](#repository-structure)
8. [Run it locally](#run-it-locally)
9. [Configuration](#configuration)
10. [Deployment](#deployment)
11. [Useful commands](#useful-commands)
12. [Design decisions and trade-offs](#design-decisions-and-trade-offs)
13. [Known limitations](#known-limitations)
14. [Roadmap](#roadmap)
15. [Privacy](#privacy)

---

## What it does

1. **Collects jobs.** It pulls public postings from Greenhouse, Lever and Ashby job boards (about 50 company boards) and stores them in Postgres. A first full ingest produced 9,348 jobs.
2. **Keeps the index fresh.** A nightly GitHub Actions job re-ingests incrementally. It embeds only new or changed jobs and marks vanished jobs as expired.
3. **Understands your resume.** You send a PDF (or paste the text). An open-weight LLM extracts a structured profile, which is validated with Pydantic.
4. **Finds matches.** Hybrid search (vector + full-text, fused with Reciprocal Rank Fusion) returns relevant jobs. Entry-level candidates are not shown Staff/Senior/Lead roles, and India-based candidates are matched to India locations first.
5. **Explains and learns.** Each match comes with a grounded one-sentence reason. 👍/👎 feedback shifts later results and hides jobs you have already seen.
6. **Chats.** You can say things like "only remote jobs" or "why does the first one fit me?". An agent with tools updates your saved preferences, runs searches and explains matches.
7. **Sends a daily digest** (opt-in) with 3 new matches each morning.

---

## Architecture

```
                 ┌──────────────────────────────────────────────┐
                 │   GitHub Actions                             │
                 │   02:00 IST  nightly-ingest (ingest + embed) │
                 │   09:00 IST  daily-digest                    │
                 └───────────────┬──────────────────────────────┘
                                 │ writes / reads
Greenhouse / Lever / Ashby       ▼
   public job APIs ───────►  Neon Postgres + pgvector
                             jobs · users · matches · feedback · events
                                 ▲
Telegram ──webhook──► Render (FastAPI + python-telegram-bot)
   user                          │
                                 ├─ resume PDF → text → LLM (Groq) → validated Profile
                                 ├─ hybrid search → top 3 → grounded reasons
                                 └─ agent with tools + per-user memory in Postgres
```

Local development uses Docker Compose with three containers: `db` (Postgres + pgvector), `app` (FastAPI) and `bot` (Telegram long polling). Production runs one container on Render in webhook mode.

---

## Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.11 |
| API | FastAPI, Uvicorn |
| Bot | python-telegram-bot 21.6 (polling locally, webhook in production) |
| Database | PostgreSQL 16 with pgvector (HNSW index) and a generated `tsvector` column (GIN index) |
| Embeddings | `BAAI/bge-small-en-v1.5` (384 dimensions) via fastembed, CPU only |
| Reranker | `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder via fastembed |
| LLM | `openai/gpt-oss-120b` (open-weight) served by Groq's OpenAI-compatible API. The model name is configurable. |
| Validation | Pydantic v2 |
| Ingestion | httpx, tenacity (retries), BeautifulSoup |
| PDF parsing | pypdf |
| Containers | Docker, Docker Compose |
| Hosting | Render (free web service), Neon (free Postgres) |
| Scheduling | GitHub Actions cron |

---

## Project status

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: Docker Compose, FastAPI `/health`, config via environment variables | Done |
| 1 | Ingestion: schema, 3 job sources, content-hash dedupe, soft-delete expiry, incremental embeddings | Done |
| 2 | Search: vector, full-text, RRF fusion, cross-encoder rerank | Done |
| 3 | Resume parsing: PDF → LLM → validated Pydantic profile | Done |
| 4 | Telegram bot v1 with location-aware matching and seniority filtering | Done |
| 5 | Deployment: Neon, Render (webhook mode), nightly GitHub Actions ingest | Done |
| 6 | Agent with tools, per-user memory, 👍/👎 feedback loop, daily digest | Done |
| 7 | Ghost/stale listing detection | Planned |
| 8 | Evaluation: labelled query-job pairs, P@3 and NDCG@3 for each search mode | Planned |
| 9 | Production quality: structured logs, rate limiting, tests, CI | Planned |
| 10 | Real-user usage metrics from the `events` table | In progress (friends are using the live bot) |
| 11 | Packaging: diagram, demo script, write-up | Planned |

No evaluation numbers are reported yet. The search modes are built so they can be compared fairly in Phase 8.

---

## Bot commands

| Command | What it does |
|---|---|
| `/start` | Welcome message and privacy notice |
| *(send a PDF)* | Parses your resume, shows the profile it understood, then sends 3 matches |
| *(paste resume text)* | Messages over 800 characters are treated as a pasted resume |
| `/matches` | 3 new matches from your saved profile. Jobs you have already seen are excluded. |
| `/settings` | Shows your preferences, digest status and feedback counts |
| `/digest on` / `/digest off` | Opt in or out of a daily message with 3 matches (about 9:00 IST) |
| `/delete` | Deletes your profile, preferences, matches, feedback and activity history |
| `/help` | Shows the welcome text |
| *(chat)* | Natural language such as "only remote jobs", "focus on data engineering" or "why does the first one fit me?" |

Each match card has **👍 Relevant** and **👎 Not for me** buttons.

---

## How it works

### 1. Ingestion (`scripts/ingest.py`, `scripts/embed.py`)

- Each source adapter in `app/fetchers.py` converts Greenhouse, Lever or Ashby responses into one common job shape.
- A SHA-256 hash of title, location and description decides what happened to each job:
  - **new** job: inserted.
  - **changed** job: updated and its embedding cleared.
  - **unchanged** job: only `last_seen_at` is refreshed.
  - **missing** job: marked with `expired_at` (soft delete, history is kept).
- Safety guards: a dead board is skipped, network errors and 429/5xx responses are retried with exponential backoff, and an empty response never expires a board's stored jobs.
- Writes are batched with `executemany`, and descriptions are truncated to 8,000 characters to keep inserts fast and the database small.
- `scripts/embed.py` embeds only rows where `embedding IS NULL`, in batches, and can be stopped and resumed.

### 2. Search (`app/search.py`)

Four modes share one code path:

| Mode | Method |
|---|---|
| `vector` | pgvector cosine search |
| `fts` | Postgres full-text search with an OR-style tsquery, ranked by `ts_rank_cd` |
| `hybrid` | Vector and full-text rankings fused with Reciprocal Rank Fusion (`Σ 1/(60 + rank)`) |
| `hybrid_rerank` | `hybrid`, then a cross-encoder rescoring of the top 30 candidates |

Filters: remote only, location terms, exclusion of senior-sounding titles, jobs already shown, and avoided companies.

### 3. Resume parsing (`app/profile.py`)

PDF text is extracted with pypdf, then sent to the LLM in JSON mode. The reply must pass `Profile.model_validate_json`. If it fails, the model gets its own output and the validation error and is asked to correct it, for up to 3 attempts. Scanned PDFs with almost no extractable text are rejected with a clear message.

### 4. Matching (`app/matching.py`)

- Intern and junior profiles exclude Staff, Senior, Lead, Research Scientist, PhD and similar titles.
- If the profile mentions an Indian location, results are filtered to Indian cities first. Without enough local jobs it falls back to anywhere, unless the user explicitly asked for a location or remote only.
- No company contributes more than 2 of the 3 results.
- With feedback history, the query vector is adjusted by Rocchio relevance feedback: moved toward liked jobs (weight 0.6) and away from disliked ones (weight 0.3). These weights are untuned.

### 5. Reasons (`app/explain.py`)

One LLM call writes a short reason for each of the 3 jobs from grounded facts (skills that literally appear in the posting). If the call fails or returns the wrong number of reasons, a deterministic "Mentions your skills: ..." reason is used instead.

### 6. Agent and memory (`app/agent.py`, `app/memory.py`)

The agent has four tools: `get_profile`, `search_jobs`, `update_preferences` and `explain_match`. Memory lives in Postgres, not in the chat context, and the system prompt is rebuilt from the database on every turn:

- **Preferences** (validated by a Pydantic model): remote only, locations, companies to avoid, focus area.
- **Matches shown**, to avoid repeats and to resolve "the first one".
- **Feedback** (👍/👎), used for re-ranking and for blocking a company after 2 dislikes.

Resume parsing is deliberately a pipeline step and not an LLM-chosen tool. Tool arguments are validated, tool errors are returned to the model so it can recover, the loop is capped at 4 steps, and job text is treated as untrusted data.

### 7. Daily digest (`scripts/digest.py`)

Runs in GitHub Actions at 09:00 IST, after the nightly ingest. It messages only users who ran `/digest on`, at most once per 20 hours each. If a user has blocked the bot, their digest is switched off automatically. The digest job runs on a runner with plenty of memory, so it uses `hybrid_rerank`.

---

## Repository structure

```
mini-elip/
├── app/
│   ├── main.py          # FastAPI app: /healthz, /health, /search, Telegram webhook
│   ├── bot.py           # Telegram handlers, buttons, polling entrypoint
│   ├── agent.py         # Tool-using agent loop and tool handlers
│   ├── memory.py        # Preferences, matches, feedback, Rocchio personalisation
│   ├── matching.py      # Profile + memory -> top matches
│   ├── search.py        # Vector / FTS / RRF / rerank search
│   ├── explain.py       # Grounded match reasons with deterministic fallback
│   ├── profile.py       # PDF text extraction, LLM profile parsing, Pydantic models
│   ├── llm.py           # Groq client (JSON mode and tool calling, retries)
│   ├── embeddings.py    # fastembed embedding model
│   ├── fetchers.py      # Greenhouse, Lever and Ashby adapters
│   ├── sources.py       # List of job boards to ingest
│   ├── formatting.py    # Message text and button layout
│   ├── users.py         # User, event and digest database helpers
│   ├── config.py        # Settings from environment variables
│   ├── db.py            # Postgres connection helper
│   └── migrate.py       # Applies sql/schema.sql
├── scripts/
│   ├── ingest.py        # Fetch and sync jobs
│   ├── embed.py         # Embed new or changed jobs
│   ├── digest.py        # Send the daily digest
│   ├── peek.py          # Inspect one job board without touching the database
│   ├── search_cli.py    # Try the search modes from the terminal
│   ├── parse_resume.py  # Parse a resume PDF and show matches
│   └── try_agent.py     # Chat with the agent from the terminal
├── sql/
│   ├── init.sql         # Enables pgvector (runs once on first DB creation)
│   └── schema.sql       # Tables and indexes (safe to re-run)
├── .github/workflows/
│   ├── nightly.yml      # 02:00 IST: migrate, ingest, embed
│   └── digest.yml       # 09:00 IST: daily digest
├── Dockerfile           # Bakes the ML models into the image
├── docker-compose.yml   # db + app + bot for local development
├── requirements.txt
├── .env.example
└── .dockerignore
```

### Database tables

| Table | Purpose |
|---|---|
| `jobs` | Job postings, `vector(384)` embedding, generated `tsvector`, `first_seen_at`, `last_seen_at`, `expired_at` |
| `users` | Telegram id, extracted profile (JSONB), preferences (JSONB), digest settings |
| `matches` | Which jobs were shown to which user, from which source, and the reason |
| `feedback` | 👍/👎 votes per user and job |
| `events` | Usage log (`start`, `resume_ok`, `matches_shown`, `feedback`, ...) used for real usage numbers |

---

## Run it locally

### Prerequisites

- Docker Desktop (running)
- Git
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Groq API key from [console.groq.com](https://console.groq.com)

### Steps

```bash
# 1. Clone
git clone https://github.com/nimisha-m-iyer/mini-elip.git
cd mini-elip

# 2. Create your env file, then edit it with your keys
cp .env.example .env            # PowerShell: Copy-Item .env.example .env

# 3. Start the database, API and bot (first build takes a few minutes)
docker compose up -d --build

# 4. Create the tables
docker compose exec app python -m app.migrate

# 5. Load jobs (a few minutes), then embed them (5-20 minutes on CPU)
docker compose exec app python -m scripts.ingest
docker compose exec app python -m scripts.embed
```

Then:

- Open http://localhost:8000/health. You should see `{"status":"ok","db":true,"pgvector":true}`.
- Open http://localhost:8000/docs to try the `/search` endpoint.
- Message your bot on Telegram. Locally it runs in polling mode.

Only one process can receive updates for a bot token. If the deployed webhook is active, stop the local bot with `docker compose stop bot`, or use a second bot token for development.

### Try things without Telegram

```bash
# Search with all four modes side by side
docker compose exec app python -m scripts.search_cli "python backend engineer" --compare

# Parse a resume (put a text-based PDF at data/resume.pdf first) and show matches
docker compose exec app python -m scripts.parse_resume data/resume.pdf

# Chat with the agent
docker compose exec app python -m scripts.try_agent "show me some jobs"
docker compose exec app python -m scripts.try_agent "I only want remote jobs from now on"

# Preview the digest without sending anything
docker compose exec app python -m scripts.digest --dry-run
```

---

## Configuration

All configuration comes from environment variables (see `.env.example`).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Yes | | Postgres connection string |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local only | `elip` | Credentials for the local Postgres container |
| `TELEGRAM_BOT_TOKEN` | For the bot | | Token from BotFather |
| `GROQ_API_KEY` | For resume parsing, reasons and the agent | | Groq API key |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Chat model served by Groq. Groq's model list changes, so this is configurable. |
| `WEBHOOK_BASE_URL` | Production | empty | Public URL of the service. When set, the app registers a Telegram webhook instead of polling. |
| `TELEGRAM_WEBHOOK_SECRET` | Production | empty | Secret Telegram sends with each webhook call. Letters, digits, `_` and `-` only. |
| `RERANK_ENABLED` | No | `true` | Set to `false` to skip the cross-encoder on low-memory hosts |
| `MODEL_CACHE_DIR` | No | `/models` | Where fastembed stores model files |

Never commit `.env`. It is listed in `.gitignore` and `.dockerignore`.

---

## Deployment

| Component | Where | Notes |
|---|---|---|
| Postgres + pgvector | Neon (free) | Direct connection string, not the pooler |
| API and bot | Render (free Docker web service) | Health check path `/healthz`, webhook mode |
| Nightly ingest | GitHub Actions | Runs `app.migrate`, `scripts.ingest`, `scripts.embed` |
| Daily digest | GitHub Actions | Runs `scripts.digest` |

Summary of the setup:

1. Create a Neon project, enable pgvector, run `python -m app.migrate` against it, and copy the local `jobs` table across with `pg_dump` and `pg_restore` (embeddings included) so that nothing has to be re-embedded.
2. Create a Render web service from this repo (Docker, free instance, health check `/healthz`). Set `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `GROQ_MODEL`, `TELEGRAM_WEBHOOK_SECRET`, `RERANK_ENABLED=false`, then `WEBHOOK_BASE_URL` once the service URL is known.
3. Add the GitHub secrets `DATABASE_URL`, `TELEGRAM_BOT_TOKEN` and `GROQ_API_KEY` for the two workflows.
4. Optionally ping `/healthz` every 5 minutes with an uptime monitor to reduce cold starts. `/healthz` does not touch the database, so it does not use up Neon's free compute hours.

Free-tier limits change, so check each provider's current limits.

---

## Useful commands

```bash
docker compose ps                          # container status
docker compose logs --since 5m bot         # recent bot logs
docker compose restart bot                 # the bot has no auto-reload
docker compose exec db psql -U elip -d elip -c "\dt"

# Index health
docker compose exec db psql -U elip -d elip -c "SELECT source, count(*) FROM jobs WHERE expired_at IS NULL GROUP BY source;"
docker compose exec db psql -U elip -d elip -c "SELECT count(*) FILTER (WHERE embedding IS NOT NULL AND expired_at IS NULL) AS searchable, count(*) FILTER (WHERE embedding IS NULL AND expired_at IS NULL) AS pending FROM jobs;"

# Aggregate usage (counts only)
docker compose exec db psql -U elip -d elip -c "SELECT kind, count(*) AS events, count(DISTINCT telegram_id) AS people FROM events GROUP BY kind ORDER BY events DESC;"
```

---

## Design decisions and trade-offs

- **Hybrid search with RRF.** Vector search finds paraphrases but can blur exact terms like "Kubernetes". Full-text search is precise on keywords but misses paraphrases. RRF fuses by rank position, so it avoids comparing incompatible score scales (cosine similarity vs. `ts_rank_cd`). Whether hybrid actually beats vector-only will be measured in Phase 8, not assumed.
- **Incremental, idempotent ingestion.** Content hashing means re-running ingestion is safe and only changed jobs are re-embedded, so a nightly cron stays cheap.
- **Soft deletes.** Expired jobs are kept with `expired_at`. This preserves history for ghost-listing detection in Phase 7.
- **Validated LLM output.** Every profile passes Pydantic validation with a bounded self-repair loop. Downstream code never sees malformed data.
- **Graceful degradation.** Reasons fall back to a deterministic version, a dead job board is skipped, and an empty API response never wipes data.
- **Memory in Postgres.** Agent memory survives restarts and cold starts and costs few tokens, since the prompt is rebuilt from the database each turn.
- **Reranker off on the live bot.** Render's free instance has about 512 MB of RAM. With both models loaded, the service exceeded the memory limit, so the live bot sets `RERANK_ENABLED=false` and runs hybrid search only. The digest and local runs can use the reranker. The quality cost of this choice will be measured in Phase 8.
- **Webhook in production, polling locally.** Render's free tier sleeps when idle, and an incoming Telegram request wakes it. The webhook checks Telegram's secret header.
- **Secrets hygiene.** Request logging for httpx is silenced because Telegram request URLs contain the bot token.
- **Blocking work in threads.** The bot is async, so DB, LLM and search calls run in worker threads to avoid freezing other users.

---

## Known limitations

- **Postgres has no true BM25.** The full-text side uses `ts_rank_cd`, a similar keyword-relevance approximation.
- **Seniority is handled by a title filter, not understood by the model.** Early on, the search returned Staff and Senior roles to an intern profile because it matched on topic only. The title filter fixes the obvious cases, but a mid-level role without a senior keyword can still appear.
- **Thin entry-level coverage in India.** In the first ingest, 616 active jobs were in India and only 33 of those had entry-level titles. This is a data coverage problem. More India-relevant boards would help.
- **Many boards are US companies.** Location filtering helps, but the pool of local jobs is small.
- **LLM extraction is not deterministic.** The same resume can produce a slightly different profile on different runs.
- **Text-based PDFs only.** Scanned or image PDFs are rejected with a clear message.
- **No connection pooling.** `get_conn()` opens a new connection per call. This is fine at current scale.
- **`/health` returns HTTP 200 even on error.** This is planned for Phase 9, along with rate limiting. `/search` is currently public and unauthenticated.
- **Feedback weights are untuned.** The Rocchio weights (0.6 and 0.3) are initial guesses, and no improvement from feedback is claimed yet.
- **No tests or CI yet.** These come in Phase 9.
- **Free-tier cold starts.** The first message after idle time can take around a minute.

---

## Roadmap

- **Phase 7: Ghost-listing detection.** Score listings using age, repost behaviour, duplicates and vague descriptions, built on the `first_seen_at`, `last_seen_at` and `expired_at` history. Filter out risky ones.
- **Phase 8: Evaluation.** Hand-labelled query-job pairs, precision@3 and NDCG@3 for vector vs. hybrid vs. hybrid + rerank, and an LLM-judge agreement check.
- **Phase 9: Production quality.** Structured JSON logs, retries, rate limiting, a proper 503 on `/health` failure, pytest tests and CI.
- **Phase 10: Real-user metrics.** Honest usage counts computed from the `events` table.
- **Phase 11: Packaging.** Architecture diagram, demo script and write-up.

---

## Privacy

- The text of a resume is sent to an AI provider (Groq) to extract your skills.
- The PDF itself is never stored. Only the extracted profile is saved: name, skills, education, experience summaries, and the roles and locations inferred from them.
- The database also stores your preferences, the jobs shown to you, your 👍/👎 votes and usage events.
- `/delete` removes your profile, preferences, matches, feedback and events.
- The repository is configured to keep `.env` and local `data/` (including test resumes) out of Git.

---

Built by Nimisha M Iyer.
