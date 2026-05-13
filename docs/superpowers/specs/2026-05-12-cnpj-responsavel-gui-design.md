# CNPJ Responsible Finder Design

## Goal

Build a local GUI tool that accepts pasted CNPJ lists or uploaded text/table files, reads public company pages from `cnpj.biz`, and uses the configured LLM to identify the highest responsible person for each company.

## Inputs

The GUI accepts:

- Pasted text containing one or more CNPJ values.
- `.txt` and `.csv` files containing CNPJ values anywhere in the text.
- `.xlsx` files where CNPJ values may appear in any cell.

CNPJ values are normalized to 14 digits, validated with official CNPJ check digits, and kept in original input order. Duplicate CNPJ values are fetched once and then copied back to duplicate rows.

## Data Source

The runtime fetch path is now multi-source and prioritizes public API providers for stability:

```text
BrasilAPI -> ReceitaWS -> cnpj.biz
```

`cnpj.biz` remains the canonical browser link for output rows and an optional fallback fetch source, using the stable detail URL:

```text
https://cnpj.biz/<14 digit CNPJ>
```

Chrome MCP exploration confirmed `cnpj.biz` detail pages are server-rendered HTML and contain the expected business fields, but Cloudflare protection makes it unsuitable as the only production source.

## Extracted Fields

The backend extracts:

- CNPJ and source URL
- legal name, trade name, registration date, legal nature, company size, capital, type, status, registration status date
- masked email and phone values when present
- address fields: street, district, ZIP code, city, state
- primary CNAE and secondary CNAE text
- raw QSA text and parsed candidate rows
- responsible qualification text when available
- branch summary and branch links when present
- page summary from the `Sobre` section

Contact values may differ by provider. API providers usually return structured phones and address fields directly; `cnpj.biz` may still show masked contacts.

## Responsible-Person Analysis

The backend sends structured extracted data to the configured LLM:

- API key: `LLM_API_KEY` in `.env`
- candidate base URLs: `LLM_BASE_URLS` in `.env`
- primary model: `doubao-seed-2-0-mini-260215`
- fallback model chain: configured by `LLM_FALLBACK_MODELS` and currently defaults to `gpt-5.4-mini`

At startup or first use, the app tests the configured base URLs and selects the fastest available endpoint. It then preflights the primary model; if that model is unavailable, it tries the configured fallback models before dropping to the local rule engine. Results record whether they came from the primary LLM, a fallback model, or the local rule fallback.

Role ranking for fallback is:

```text
Presidente > Diretor Presidente > Diretor > Administrador Judicial > Administrador > Sócio-Administrador > Sócio > other roles
```

When several people share the highest role, the result returns all of them as same-level responsible candidates instead of inventing a single winner.

## Cloudflare and Rate Limits

Chrome MCP exploration found Cloudflare Turnstile on `cnpj.biz`. To keep the tool stable without depending on access-control bypass, the production runtime prefers public API providers and only falls back to `cnpj.biz` if earlier providers fail.

The batch runner processes deduplicated CNPJ values sequentially with a short delay and per-CNPJ error isolation. If the configured LLM is unavailable, the runtime performs a single short preflight check, disables remote analysis for that batch, and uses the local role-ranking fallback instead of timing out on every row.

## GUI

The app is a local browser GUI served by FastAPI. The first screen is the working tool:

- input panel for pasted CNPJ values and file upload
- controls to start a batch, clear input, and export results
- live job status area
- results table with company, responsible person, role, confidence, status, evidence, and link

The interface is operational and dense, designed for repeated batch work rather than a marketing landing page.

## Packaging

The project includes a Windows PyInstaller path:

- `run.py` starts the local server and opens the GUI in the default browser.
- `packaging/CnpjResponsavelTool.spec` includes static frontend assets.
- `scripts/build_windows.ps1` creates a venv, installs dependencies, and builds a one-file `.exe`.

Because this workspace is Linux, the Windows `.exe` should be built on Windows for reliable output.

## Verification

Automated tests cover:

- CNPJ extraction, formatting, check-digit validation, and deduplication.
- HTML parser behavior for registration fields, QSA candidates, branches, and masked contacts.
- file import for text, CSV, and XLSX inputs.
- rule fallback ranking and tie behavior.

Manual verification covers:

- FastAPI server starts.
- GUI loads in a browser.
- A batch can be submitted and polled.
- Public API fetch returns structured QSA data for real CNPJ values.
- Multi-source fallback returns company data without depending on `cnpj.biz`.
- Direct detail-page fetch still detects success, not found, and Cloudflare challenge states when that fallback path is reached.
