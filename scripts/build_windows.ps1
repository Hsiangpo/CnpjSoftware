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
& .\.venv\Scripts\pyinstaller.exe --noconfirm packaging\CnpjResponsavelTool.spec

Write-Host "Build complete: dist\CnpjResponsavelTool.exe"
