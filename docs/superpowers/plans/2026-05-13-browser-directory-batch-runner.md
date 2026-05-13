# Browser Directory Batch Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cnpj.biz HTTP fallback with a browser-backed provider and switch the app from ad hoc upload/download to fixed `./cnpj` input discovery and `./output` result materialization.

**Architecture:** Keep the top-level provider chain small: `BrasilAPI -> cnpjbiz.browser`. The browser provider owns long-lived Playwright sessions per worker thread and reuses the existing HTML parser. The web app stops accepting manual uploads in the main flow and instead lists source files from `./cnpj`, creates resumable jobs from a selected file, and writes finished output files into `./output`.

**Tech Stack:** FastAPI, curl_cffi, Playwright, openpyxl, existing checkpoint/job infrastructure

---

### Task 1: Lock the new source-file job flow with tests

**Files:**
- Modify: `tests/test_server.py`
- Modify: `tests/test_providers.py`

- [ ] Add failing server tests for listing root `cnpj/` files and creating a job from a selected source file.
- [ ] Run the targeted tests and confirm they fail for the expected missing behavior.
- [ ] Add a failing provider test that proves `cnpjbiz` now resolves to a browser-backed fetcher rather than the old HTTP client.
- [ ] Re-run the targeted tests and confirm the provider-path failure is real.

### Task 2: Add filesystem source discovery and fixed output paths

**Files:**
- Modify: `cnpj_tool/config.py`
- Create: `cnpj_tool/source_files.py`
- Modify: `cnpj_tool/checkpoints.py`
- Modify: `cnpj_tool/jobs.py`
- Modify: `cnpj_tool/server.py`

- [ ] Add config helpers/defaults for `./cnpj` and `./output`, with env overrides only for tests.
- [ ] Implement source-file enumeration and safe source-file loading from the root `cnpj/` directory.
- [ ] Extend job metadata to carry source filename and output path.
- [ ] Add server endpoints that list available source files and create jobs from `source_name`.
- [ ] Materialize finished output files into `./output` after job completion.

### Task 3: Add the browser-backed cnpj.biz provider

**Files:**
- Create: `cnpj_tool/browser_scraper.py`
- Modify: `cnpj_tool/providers.py`
- Add/Modify: `tests/test_browser_scraper.py`
- Modify: `tests/test_providers.py`

- [ ] Write failing browser-provider tests for proxy assignment, HTML extraction, and challenge/timeout handling.
- [ ] Implement a synchronous Playwright provider with thread-local browser state, round-robin proxy-port assignment, one fresh page per fetch, and parser reuse.
- [ ] Switch `build_company_client()` so `cnpjbiz` resolves to the browser provider.
- [ ] Change the default provider order to `brasilapi,cnpjbiz`.

### Task 4: Replace the manual upload/download UI with directory selection

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `tests/test_server.py`

- [ ] Remove the primary manual input/upload/download controls from the UI.
- [ ] Add source-file listing, selection, run/start, and output-path display.
- [ ] Keep existing job polling/result rendering, but drive it from selected source files.
- [ ] Update page tests to assert the new file-selection UI instead of the old upload controls.

### Task 5: Verify and tighten the changed flow

**Files:**
- Modify: any touched files above as needed

- [ ] Run targeted tests for server/providers/browser scraper until green.
- [ ] Run the full pytest suite and fix regressions.
- [ ] Run `python3 -m compileall cnpj_tool run.py` and `node --check static/app.js`.
- [ ] Restart the local app only if required by the implementation and then smoke-test `/api/source-files` and one directory-backed job.
