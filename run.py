from __future__ import annotations

import os
import sys
from pathlib import Path


def _configure_playwright_browsers() -> None:
    """Point Playwright at a real browser cache before it is imported.

    In a PyInstaller bundle the default browser lookup resolves inside the
    temporary ``_MEIxxxx`` extraction directory, which never contains the
    downloaded browsers — so the headless scraper fails with "Executable
    doesn't exist". Prefer a sibling ``ms-playwright`` folder shipped next to
    the executable (self-contained), then fall back to the per-user install.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if not getattr(sys, "frozen", False):
        return  # running from source: the default cache works
    candidates = [Path(sys.executable).resolve().parent / "ms-playwright"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "ms-playwright")
    for path in candidates:
        if path.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
            return


_configure_playwright_browsers()

import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
import webbrowser  # noqa: E402

import uvicorn  # noqa: E402

from cnpj_tool.server import app  # noqa: E402


APP_HOST = "127.0.0.1"
APP_PORT = 8765
APP_URL = f"http://{APP_HOST}:{APP_PORT}"


def wait_for_app(url: str = APP_URL, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{url.rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if 200 <= response.status < 500:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return False


def open_browser_when_ready() -> None:
    wait_for_app()
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")
