import run as run_module


def test_wait_for_app_polls_health_endpoint(monkeypatch):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(run_module.urllib.request, "urlopen", fake_urlopen)

    assert run_module.wait_for_app("http://127.0.0.1:9999", timeout_seconds=1) is True
    assert calls == [("http://127.0.0.1:9999/api/health", 1.0)]


def test_open_browser_when_ready_opens_local_frontend(monkeypatch):
    opened = []

    monkeypatch.setattr(run_module, "wait_for_app", lambda: True)
    monkeypatch.setattr(run_module.webbrowser, "open", opened.append)

    run_module.open_browser_when_ready()

    assert opened == [run_module.APP_URL]
