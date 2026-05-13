from __future__ import annotations

import threading
import webbrowser

import uvicorn

from cnpj_tool.server import app


def open_browser() -> None:
    webbrowser.open("http://127.0.0.1:8765")


if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
