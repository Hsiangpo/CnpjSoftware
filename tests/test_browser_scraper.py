from cnpj_tool.cf_bypass import BlurpathProxyConfig


def test_browser_client_fetches_company_html_through_playwright_proxy(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    launch_calls = []

    class FakePage:
        def goto(self, url, wait_until, timeout):
            self.url = url
            return type("Response", (), {"status": 200})()

        def content(self):
            return """
            <main>
              <h1>Empresa Teste 03.541.629/0001-37</h1>
              <h2>Informações de Registro</h2>
              CNPJ: 03.541.629/0001-37 Razão Social: Empresa Teste Situação: Ativa
              <h2>Quadro de Sócios e Administradores</h2>
              Maria Teste - Sócio-Administrador<br>
            </main>
            """

        def title(self):
            return "Empresa Teste"

        def wait_for_timeout(self, timeout_ms):
            return None

        def close(self):
            return None

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            self.context_kwargs = kwargs
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_calls.append(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(
        proxy_configs=[
            BlurpathProxyConfig(
                host="blurpath.net",
                port=15121,
                username="acct",
                password="secret",
            )
        ],
        user_agent="Mozilla/5.0 Chrome/146",
    )

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "Empresa Teste"
    assert company.source_provider == "cnpjbiz.browser"
    assert company.source_proxy_port == 15121
    assert launch_calls[0]["proxy"]["server"] == "http://blurpath.net:15121"
    assert "executable_path" not in launch_calls[0]


def test_browser_client_uses_custom_executable_path_when_provided(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    launch_calls = []

    class FakeBrowser:
        def new_context(self, **kwargs):
            raise RuntimeError("stop after launch")

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_calls.append(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(executable_path="C:/Browser/chrome.exe", max_retries=1)

    try:
        client.fetch_html("03.541.629/0001-37")
    except browser_module.CnpjBizError:
        pass
    else:
        raise AssertionError("expected CnpjBizError")

    assert launch_calls[0]["executable_path"] == "C:/Browser/chrome.exe"


def test_browser_client_rotates_to_next_proxy_after_timeout(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    launch_ports = []

    class TimeoutPage:
        def goto(self, url, wait_until, timeout):
            raise TimeoutError("page timeout")

        def close(self):
            return None

    class SuccessPage:
        def goto(self, url, wait_until, timeout):
            return type("Response", (), {"status": 200})()

        def content(self):
            return """
            <main>
              <h1>Empresa Teste 03.541.629/0001-37</h1>
              <h2>Informações de Registro</h2>
              CNPJ: 03.541.629/0001-37 Razão Social: Empresa Teste Situação: Ativa
              <h2>Quadro de Sócios e Administradores</h2>
              Maria Teste - Sócio-Administrador<br>
            </main>
            """

        def title(self):
            return "Empresa Teste"

        def wait_for_timeout(self, timeout_ms):
            return None

        def close(self):
            return None

    class FakeContext:
        def __init__(self, page):
            self.page = page

        def new_page(self):
            return self.page

        def close(self):
            return None

    class FakeBrowser:
        def __init__(self, page):
            self.page = page

        def new_context(self, **kwargs):
            return FakeContext(self.page)

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_ports.append(kwargs["proxy"]["server"])
            if len(launch_ports) == 1:
                return FakeBrowser(TimeoutPage())
            return FakeBrowser(SuccessPage())

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(
        proxy_configs=[
            BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret"),
            BlurpathProxyConfig(host="blurpath.net", port=15129, username="acct", password="secret"),
        ],
        user_agent="Mozilla/5.0 Chrome/146",
        max_retries=2,
    )

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "Empresa Teste"
    assert launch_ports == [
        "http://blurpath.net:15121",
        "http://blurpath.net:15129",
    ]


def test_browser_client_accepts_page_that_self_recovers_after_initial_403(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    class RecoveringPage:
        def __init__(self):
            self.contents = [
                "<html><title>Just a moment...</title><div>challenge-platform</div></html>",
                """
                <main>
                  <h1>Empresa Teste 03.541.629/0001-37</h1>
                  <h2>Informações de Registro</h2>
                  CNPJ: 03.541.629/0001-37 Razão Social: Empresa Teste Situação: Ativa
                  <h2>Quadro de Sócios e Administradores</h2>
                  Maria Teste - Sócio-Administrador<br>
                </main>
                """,
            ]

        def goto(self, url, wait_until, timeout):
            return type("Response", (), {"status": 403})()

        def content(self):
            if len(self.contents) > 1:
                return self.contents.pop(0)
            return self.contents[0]

        def wait_for_timeout(self, timeout_ms):
            return None

        def close(self):
            return None

    class FakeContext:
        def new_page(self):
            return RecoveringPage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")],
        user_agent="Mozilla/5.0 Chrome/146",
        challenge_wait_seconds=2,
    )

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "Empresa Teste"


def test_browser_client_stops_playwright_when_launch_fails(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    stop_calls = []

    class FakeChromium:
        def launch(self, **kwargs):
            raise RuntimeError("launch failed")

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            stop_calls.append("stop")

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")],
        user_agent="Mozilla/5.0 Chrome/146",
        max_retries=1,
    )

    try:
        client.fetch_html("03.541.629/0001-37")
    except browser_module.CnpjBizError as exc:
        assert "launch failed" in str(exc)
    else:
        raise AssertionError("expected CnpjBizError")

    assert stop_calls == ["stop"]


def test_browser_client_close_releases_registered_browser_state(monkeypatch):
    import cnpj_tool.browser_scraper as browser_module

    closed = []

    class FakePage:
        def goto(self, url, wait_until, timeout):
            return type("Response", (), {"status": 200})()

        def content(self):
            return """
            <main>
              <h1>Empresa Teste 03.541.629/0001-37</h1>
              <h2>Informações de Registro</h2>
              CNPJ: 03.541.629/0001-37 Razão Social: Empresa Teste Situação: Ativa
              <h2>Quadro de Sócios e Administradores</h2>
              Maria Teste - Sócio-Administrador<br>
            </main>
            """

        def wait_for_timeout(self, timeout_ms):
            return None

        def close(self):
            return None

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            closed.append("context")

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            closed.append("browser")

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            closed.append("playwright")

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "sync_playwright", lambda: FakeSyncPlaywright())

    client = browser_module.CnpjBizBrowserClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")],
        user_agent="Mozilla/5.0 Chrome/146",
    )

    company = client.fetch_company("03.541.629/0001-37")
    assert company.legal_name == "Empresa Teste"

    client.close()

    assert closed == ["context", "browser", "playwright"]
