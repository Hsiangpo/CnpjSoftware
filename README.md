# CNPJ Batch Analysis Tool

Local batch tool for loading CNPJ source files from `./cnpj`, extracting company data, identifying the highest-ranking responsible party, and writing results to `./output`.

The current runtime flow is:

- `BrasilAPI` first
- fallback to `cnpj.biz` browser scraping
- `LLM` analysis first when configured
- local rule fallback when `LLM` analysis fails

## What It Does

- Reads `.txt`, `.csv`, and `.xlsx` source files from `./cnpj`
- Deduplicates CNPJ values for processing while preserving row-level export
- Runs batch jobs with queue support from the local web UI
- Uses `Playwright + Blurpath` for browser-backed fallback when public API data is insufficient
- Writes enriched results to `./output`
- Persists checkpoints in `./tmp/checkpoints`

## Directory Contract

- `cnpj/`: input files to process
- `output/`: generated result files
- `tmp/checkpoints/`: local checkpoint and resume state

These runtime directories are ignored by git.

## Requirements

- Python 3.11+
- Chromium available for Playwright
- Linux desktop or similar local environment for browser automation and file opening actions

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Important variables:

- `LLM_API_KEY`: required if you want LLM-based responsible-party analysis
- `LLM_MODEL`: default `gpt-5.4-mini`
- `SYSTEM_CONCURRENCY`: batch worker count
- `CNPJ_PROVIDER_ORDER`: default `brasilapi,cnpjbiz`
- `BLURPATH_PROXY_*`: required for the browser fallback path

The app also exposes runtime settings in the UI through `/api/settings`.

## Running the App

Start the local server:

```bash
python3 run.py
```

This starts the app on:

`http://127.0.0.1:8765`

You can also run it directly with Uvicorn:

```bash
python3 -m uvicorn cnpj_tool.server:app --host 127.0.0.1 --port 8765
```

## Typical Workflow

1. Put one or more source files into `./cnpj`
2. Start the server
3. Open `http://127.0.0.1:8765`
4. Queue one or more files
5. Review progress, provider usage, proxy port, success rate, and ETA
6. Re-run abnormal items if needed
7. Open results from `./output`

## Output

Output filenames are generated from the source filename:

- `.xlsx` input -> `*-responsaveis.xlsx`
- `.txt` / `.csv` input -> `*-responsaveis.csv`
- failed retry jobs -> `*-failed-retry.csv`

The enriched exports include responsible-party fields, status, analysis source, model, reasoning, and provider trace.

## HTTP Endpoints

Main local endpoints:

- `GET /api/health`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/source-files`
- `GET /api/output-files`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/jobs/{job_id}/retry-failed`

## Tests

Run the test suite:

```bash
python3 -m pytest -q
```

## Packaging

Windows packaging assets live under:

- `packaging/CnpjResponsavelTool.spec`
- `scripts/build_windows.ps1`

## Notes

- This repo does not store local input files, output files, `.env`, or checkpoints.
- Current responsible-party output may contain multiple names when the source data lists multiple people with the same highest role. That is current behavior, not an export bug.
