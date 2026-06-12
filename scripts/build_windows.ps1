$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    $python = $env:CNPJ_TOOL_PYTHON
    if (-not $python) {
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not $python) {
        $python = (Get-Command py -ErrorAction SilentlyContinue).Source
    }
    if (-not $python) {
        $candidate = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312-IronMail\python.exe"
        if (Test-Path $candidate) {
            $python = $candidate
        }
    }
    if (-not $python) {
        throw "Python was not found. Set CNPJ_TOOL_PYTHON to a Python 3.11+ executable path."
    }
    & $python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
& .\.venv\Scripts\pyinstaller.exe --noconfirm packaging\CnpjResponsavelTool.spec

# Ship the headless browser next to the exe so the frozen build is
# self-contained. run.py sets PLAYWRIGHT_BROWSERS_PATH to this folder. The full
# desktop/headed chromium build is excluded because the scraper runs headless.
$browsers = Join-Path $env:LOCALAPPDATA "ms-playwright"
if (Test-Path $browsers) {
    robocopy $browsers "dist\ms-playwright" /E /XD "$browsers\chromium-1217" /NFL /NDL /NJH /NP /MT:16 /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -lt 8) { Write-Host "Bundled headless browser into dist\ms-playwright" }
    $global:LASTEXITCODE = 0
} else {
    Write-Warning "ms-playwright not found; run 'playwright install chromium' so the exe can launch a browser."
}

Write-Host "Build complete: dist\CnpjResponsavelTool.exe (+ dist\ms-playwright)"
