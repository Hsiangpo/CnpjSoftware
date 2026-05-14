from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from cnpj_tool.server import app


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
