# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (Python 3.11+ required)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Configure (copy .env.example to .env and fill in values)
cp .env.example .env

# Run the app
python3 run.py                    # opens browser at http://127.0.0.1:8765
# or directly:
python3 -m uvicorn cnpj_tool.server:app --host 127.0.0.1 --port 8765

# Run all tests (use -q to suppress passing test output)
python3 -m pytest -q

# Run a specific test file
python3 -m pytest tests/test_providers.py -q

# Build Windows executable
powershell -File scripts/build_windows.ps1
```

## Architecture

This is a **CNPJ batch analysis tool** — it reads Brazilian company registration numbers (CNPJ) from source files, fetches company data from public sources, identifies the highest-ranking responsible party, and writes enriched output files.

### Core pipeline (`cnpj_tool/`)

**Entry point:** `run.py` starts a Uvicorn server with `cnpj_tool.server:app` (FastAPI) on `127.0.0.1:8765` and auto-opens a browser.

**Server** (`server.py`): All HTTP endpoints live here — health, settings, source/output file listing, job CRUD, cancel, retry. The `create_app()` factory builds the FastAPI instance with a lifespan that cleans up browser sessions on shutdown. Lazy-initializes `CompanyAnalyzer`, `JobStore`, and `CheckpointStore` on `app.state`.

**Analysis engine** (`analysis.py`): `CompanyAnalyzer` is the core. `analyze_one()` fetches company data → runs LLM analysis (if configured) → falls back to rule-based role ranking. `analyze_many()` handles concurrency via `ThreadPoolExecutor`, supports cancellation (`should_stop`), deduplication, caching existing results, and per-result callbacks for checkpoint persistence. Rule-based ranking (`choose_rule_based_responsible`) uses `ROLE_RANKS` — a tiered list from "presidente" (100) down to "sócio" (50).

**Provider chain** (`providers.py`): `build_company_client()` wires up a multi-source fetch chain:
1. `BrasilAPIClient` — public REST API, falls back to proxy on rate limits
2. `ReceitaWSClient` — alternative REST API, same proxy fallback pattern
3. `CnpjBizBrowserClient` — Playwright-based browser scraper for cnpj.biz

Each provider tries the next on failure. Results are wrapped in a `CachedCompanyClient` (thread-safe, in-memory cache by normalized CNPJ).

**Browser scraper** (`browser_scraper.py` + `parser.py`): `CnpjBizBrowserClient` uses Playwright with per-thread browser contexts and proxy rotation via Blurpath. `parser.py` (`parse_company_page`) extracts structured `CompanyData` from cnpj.biz HTML using BeautifulSoup — registration fields, location, QSA (sócios/administradores), CNAE, branches.

**LLM integration** (`llm.py`): `LLMClient` is an OpenAI-compatible client using `curl_cffi`. Supports multiple `base_urls` (tried in order with per-session lock+fallback logic), multiple `fallback_models`, and thread-local sessions.

**Data models** (`models.py`): All are `@dataclass` with `to_dict()`/`from_dict()` for JSON serialization. `BatchResult` is the top-level unit — wraps input CNPJ, status, `CompanyData`, `ResponsibleResult`, error, and `provider_trace`. `is_business_success()` determines if a result counts as successful (considers `partial_success` with rule-fallback names as success).

**Configuration** (`config.py`): `load_settings()` reads `.env` (via `python-dotenv`) and returns a frozen `Settings` dataclass. `update_runtime_settings()` writes changes back to `.env` — the UI's settings PUT endpoint calls this, then resets `app.state.analyzer` so it's rebuilt on next use.

**Checkpoints** (`checkpoints.py`): `CheckpointStore` persists results to `tmp/checkpoints/` as JSON. Supports `build_upload_id()` (hash of filename + CNPJs for dedup), `register_upload()` with full metadata, `upsert_result()`, and `materialize_output()` to `.xlsx`/`.csv`. Handles resume state for interrupted jobs.

**Jobs** (`jobs.py`): In-memory `JobStore` with `Job` dataclass. Jobs track status (`queued` → `running` → `completed`/`failed`/`cancelled`), input CNPJs, results, and cancel state.

**Importer** (`importer.py`): Parses `.txt`, `.csv`, `.xlsx` source files into `UploadDetails` (CNPJ list + row references for Excel). Excel parsing preserves `sheet_name`/`row_number` per CNPJ for accurate output mapping.

### Key design decisions

- **Checkpoint-then-flush**: Results are checkpointed per-CNPJ immediately, but output files are materialized in batches (controlled by `OUTPUT_FLUSH_BATCH_SIZE` and `OUTPUT_FLUSH_INTERVAL_SECONDS`) to reduce I/O.
- **Provider trace**: Every fetch includes a `provider_trace` list (`ProviderTraceEntry`) recording which providers were tried and why they failed. This is surfaced in the UI and output.
- **No persistence for jobs**: Jobs live in memory only — restarting the server loses the queue. Checkpoints survive because they're on disk.
- **Proxy rotation**: Browser scraper rotates proxy configs per thread; API clients try each proxy sequentially on rate-limit/error responses.
- **Static files**: Frontend is served from `static/` (mounted at `/static`), with `index.html` at the root. The PyInstaller spec bundles `static/` as data.

### Directory contract (gitignored)

- `cnpj/` — input files to process
- `output/` — generated result files
- `tmp/checkpoints/` — local checkpoint and resume state
