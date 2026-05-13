# CNPJ Responsible Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local GUI tool that batch-analyzes CNPJ values from pasted text or files and identifies the highest responsible person from `cnpj.biz` data using the configured LLM.

**Architecture:** FastAPI serves static frontend assets and JSON APIs. Backend modules handle CNPJ normalization, file import, cnpj.biz fetching/parsing, LLM selection/analysis, and in-memory batch jobs. Tests cover parser and business logic with HTML fixtures and fake clients.

**Tech Stack:** Python 3.10+, FastAPI, curl_cffi, BeautifulSoup, openpyxl, python-dotenv, pytest, vanilla HTML/CSS/JS, PyInstaller for Windows packaging.

---

## File Structure

- `cnpj_tool/cnpj.py`: extract, normalize, format, validate, and deduplicate CNPJ values.
- `cnpj_tool/importer.py`: parse `.txt`, `.csv`, and `.xlsx` uploads.
- `cnpj_tool/parser.py`: parse `cnpj.biz` detail HTML into structured company data.
- `cnpj_tool/scraper.py`: fetch direct detail pages with `curl_cffi`, retries, rate-limit handling, and Cloudflare detection.
- `cnpj_tool/llm.py`: choose fastest LLM base URL and produce strict responsible-person analysis.
- `cnpj_tool/analysis.py`: coordinate scraping, parsing, LLM analysis, fallback ranking, and batch deduplication.
- `cnpj_tool/jobs.py`: in-memory job creation, polling, and background processing.
- `cnpj_tool/server.py`: FastAPI app and API routes.
- `static/index.html`, `static/styles.css`, `static/app.js`: GUI.
- `tests/`: automated tests for core behavior.
- `run.py`: local app launcher.
- `packaging/CnpjResponsavelTool.spec` and `scripts/build_windows.ps1`: Windows packaging.

## Tasks

### Task 1: Project Scaffolding and Tests

- [ ] Create dependency files, `.gitignore`, `.env`, `.env.example`, and package directories.
- [ ] Write failing tests for CNPJ extraction/validation, file import, HTML parsing, and fallback ranking.
- [ ] Run `python3 -m pytest` and verify tests fail because modules are missing.

### Task 2: Core Data Parsing

- [ ] Implement `cnpj_tool/cnpj.py` until CNPJ tests pass.
- [ ] Implement `cnpj_tool/importer.py` until upload parsing tests pass.
- [ ] Implement `cnpj_tool/parser.py` until HTML fixture tests pass.
- [ ] Run focused tests and then the full test suite.

### Task 3: Fetching and Analysis

- [ ] Implement `cnpj_tool/scraper.py` with direct detail-page fetching, retries, blocked-page detection, and optional cookie support.
- [ ] Implement `cnpj_tool/llm.py` with fastest base URL selection and strict JSON extraction.
- [ ] Implement `cnpj_tool/analysis.py` with duplicate reuse and rule fallback.
- [ ] Run unit tests and a small mocked batch test.

### Task 4: FastAPI and GUI

- [ ] Implement `cnpj_tool/jobs.py` and `cnpj_tool/server.py`.
- [ ] Build static GUI with paste input, file upload, job polling, result table, and CSV export.
- [ ] Run server locally and verify the page loads.

### Task 5: Packaging and Verification

- [ ] Add `run.py`, PyInstaller spec, and Windows build script.
- [ ] Install dependencies.
- [ ] Run `pytest`.
- [ ] Start local server and test `/api/health`.
- [ ] Run a small real fetch smoke test; if Cloudflare blocks direct fetches, verify the tool reports `blocked_by_cloudflare` instead of empty success.
