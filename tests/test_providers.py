from cnpj_tool.cf_bypass import BlurpathProxyConfig
from cnpj_tool.models import CompanyData
from cnpj_tool.providers import (
    BrasilAPIClient,
    CachedCompanyClient,
    ReceitaWSClient,
    build_company_client,
    MultiSourceCompanyClient,
    ProviderError,
    parse_brasilapi_company,
    parse_receitaws_company,
)
from cnpj_tool.scraper import CnpjBizBlockedError, CnpjBizError, CnpjBizNotFoundError


def test_parse_brasilapi_company_maps_qsa_candidates():
    company = parse_brasilapi_company(
        {
            "cnpj": "03541629000137",
            "razao_social": "ORGANIZACOES MARQUES CENTER LTDA",
            "nome_fantasia": "ORGANIZACOES MARQUES CENTER",
            "data_inicio_atividade": "1999-11-18",
            "porte": "DEMAIS",
            "natureza_juridica": "206-2 - Sociedade Empresária Limitada",
            "capital_social": "120000.00",
            "descricao_situacao_cadastral": "ATIVA",
            "data_situacao_cadastral": "2005-11-03",
            "ddd_telefone_1": "3835331000",
            "email": "financeiro@example.com",
            "logradouro": "RUA UM",
            "bairro": "CENTRO",
            "cep": "39200000",
            "municipio": "CURVELO",
            "uf": "MG",
            "cnae_fiscal": 4711302,
            "cnae_fiscal_descricao": "Comércio varejista de mercadorias em geral",
            "cnaes_secundarios": [
                {"codigo": 4721104, "descricao": "Padaria"},
            ],
            "qsa": [
                {
                    "nome_socio": "CARLOS MARQUES MOREIRA",
                    "qualificacao_socio": "Sócio-Administrador",
                },
                {
                    "nome_socio": "POLIANA APARECIDA MOREIRA",
                    "qualificacao_socio": "Sócio-Administrador",
                },
            ],
            "qualificacao_do_responsavel": "49",
        }
    )

    assert company.cnpj == "03541629000137"
    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert company.trade_name == "ORGANIZACOES MARQUES CENTER"
    assert company.primary_cnae == "4711302 - Comércio varejista de mercadorias em geral"
    assert company.secondary_cnaes == ["4721104 - Padaria"]
    assert [candidate.name for candidate in company.candidates] == [
        "CARLOS MARQUES MOREIRA",
        "POLIANA APARECIDA MOREIRA",
    ]
    assert company.candidates[0].role == "Sócio-Administrador"


def test_parse_receitaws_company_strips_role_codes():
    company = parse_receitaws_company(
        {
            "cnpj": "03.541.629/0001-37",
            "nome": "ORGANIZACOES MARQUES CENTER LTDA",
            "fantasia": "ORGANIZACOES MARQUES CENTER",
            "abertura": "18/11/1999",
            "porte": "DEMAIS",
            "natureza_juridica": "206-2 - Sociedade Empresária Limitada",
            "capital_social": "120000.00",
            "situacao": "ATIVA",
            "data_situacao": "03/11/2005",
            "telefone": "(38) 3533-1000",
            "email": "financeiro@example.com",
            "logradouro": "RUA UM",
            "bairro": "CENTRO",
            "cep": "39200-000",
            "municipio": "CURVELO",
            "uf": "MG",
            "atividade_principal": [
                {
                    "code": "47.11-3-02",
                    "text": "Comércio varejista de mercadorias em geral",
                }
            ],
            "atividades_secundarias": [
                {"code": "47.21-1-04", "text": "Padaria"},
            ],
            "qsa": [
                {"nome": "CARLOS MARQUES MOREIRA", "qual": "49-Sócio-Administrador"},
                {"nome": "POLIANA APARECIDA MOREIRA", "qual": "49-Sócio-Administrador"},
            ],
        }
    )

    assert company.cnpj == "03541629000137"
    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert company.primary_cnae == "47.11-3-02 - Comércio varejista de mercadorias em geral"
    assert company.secondary_cnaes == ["47.21-1-04 - Padaria"]
    assert company.candidates[0].role == "Sócio-Administrador"
    assert company.candidates[1].name == "POLIANA APARECIDA MOREIRA"


def test_brasilapi_client_retries_with_proxy_after_rate_limit():
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.headers = {}

        def json(self):
            return self._payload

    class FakeSession:
        def get(self, url, headers, timeout, impersonate, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return FakeResponse(429, {"message": "Too many requests"})
            return FakeResponse(
                200,
                {
                    "cnpj": "03541629000137",
                    "razao_social": "ORGANIZACOES MARQUES CENTER LTDA",
                    "qsa": [],
                },
            )

    client = BrasilAPIClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")]
    )
    client.session = FakeSession()

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert company.source_provider == "brasilapi.proxy"
    assert company.source_proxy_port == 15121
    assert calls[0] == {}
    assert "proxies" in calls[1]
    assert "15121" in calls[1]["proxies"]["https"]


def test_brasilapi_client_does_not_proxy_retry_not_found():
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = ""
            self.headers = {}

        def json(self):
            return {}

    class FakeSession:
        def get(self, url, headers, timeout, impersonate, **kwargs):
            calls.append(kwargs)
            return FakeResponse(404)

    client = BrasilAPIClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")]
    )
    client.session = FakeSession()

    try:
        client.fetch_company("03.541.629/0001-37")
    except CnpjBizNotFoundError as exc:
        assert "BrasilAPI did not find CNPJ" in str(exc)
    else:
        raise AssertionError("expected CnpjBizNotFoundError")

    assert calls == [{}]


def test_receitaws_client_retries_with_proxy_after_rate_limit():
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.headers = {}

        def json(self):
            return self._payload

    class FakeSession:
        def get(self, url, headers, timeout, impersonate, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return FakeResponse(429, {"message": "Too many requests"})
            return FakeResponse(
                200,
                {
                    "cnpj": "03.541.629/0001-37",
                    "nome": "ORGANIZACOES MARQUES CENTER LTDA",
                    "qsa": [],
                    "atividade_principal": [],
                    "atividades_secundarias": [],
                },
            )

    client = ReceitaWSClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15129, username="acct", password="secret")]
    )
    client.session = FakeSession()

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert company.source_provider == "receitaws.proxy"
    assert company.source_proxy_port == 15129
    assert calls[0] == {}
    assert "proxies" in calls[1]
    assert "15129" in calls[1]["proxies"]["https"]


def test_brasilapi_client_retries_with_proxy_after_403():
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.headers = {}

        def json(self):
            return self._payload

    class FakeSession:
        def get(self, url, headers, timeout, impersonate, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return FakeResponse(403, {"message": "Forbidden"})
            return FakeResponse(
                200,
                {
                    "cnpj": "03541629000137",
                    "razao_social": "ORGANIZACOES MARQUES CENTER LTDA",
                    "qsa": [],
                },
            )

    client = BrasilAPIClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret")]
    )
    client.session = FakeSession()

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert calls[0] == {}
    assert "proxies" in calls[1]


def test_receitaws_client_retries_with_proxy_after_body_error():
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.headers = {}

        def json(self):
            return self._payload

    class FakeSession:
        def get(self, url, headers, timeout, impersonate, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return FakeResponse(200, {"status": "ERROR", "message": "temporary upstream issue"})
            return FakeResponse(
                200,
                {
                    "cnpj": "03.541.629/0001-37",
                    "nome": "ORGANIZACOES MARQUES CENTER LTDA",
                    "qsa": [],
                    "atividade_principal": [],
                    "atividades_secundarias": [],
                },
            )

    client = ReceitaWSClient(
        proxy_configs=[BlurpathProxyConfig(host="blurpath.net", port=15129, username="acct", password="secret")]
    )
    client.session = FakeSession()

    company = client.fetch_company("03.541.629/0001-37")

    assert company.legal_name == "ORGANIZACOES MARQUES CENTER LTDA"
    assert calls[0] == {}
    assert "proxies" in calls[1]


def test_multisource_client_falls_back_to_next_provider():
    expected = CompanyData(
        cnpj="03541629000137",
        formatted_cnpj="03.541.629/0001-37",
        url="https://example.test/company/03541629000137",
        legal_name="ORGANIZACOES MARQUES CENTER LTDA",
    )

    def first_provider(_: str) -> CompanyData:
        raise ProviderError("temporary upstream failure")

    def second_provider(_: str) -> CompanyData:
        return expected

    client = MultiSourceCompanyClient(
        providers=[
            ("first", first_provider),
            ("second", second_provider),
        ]
    )

    company = client.fetch_company("03541629000137")

    assert company is expected


def test_multisource_client_keeps_not_found_when_every_provider_misses():
    def first_provider(_: str) -> CompanyData:
        raise CnpjBizNotFoundError("missing in first provider")

    def second_provider(_: str) -> CompanyData:
        raise CnpjBizNotFoundError("missing in second provider")

    client = MultiSourceCompanyClient(
        providers=[
            ("first", first_provider),
            ("second", second_provider),
        ]
    )

    try:
        client.fetch_company("03541629000137")
    except CnpjBizNotFoundError as exc:
        assert "second provider" in str(exc)
    else:
        raise AssertionError("expected CnpjBizNotFoundError")


def test_multisource_client_attaches_provider_trace_to_final_failure():
    def first_provider(_: str) -> CompanyData:
        raise ProviderError("BrasilAPI failed with HTTP 429")

    def second_provider(_: str) -> CompanyData:
        raise CnpjBizBlockedError("cnpj.biz returned HTTP 403")

    client = MultiSourceCompanyClient(
        providers=[
            ("brasilapi", first_provider),
            ("cnpjbiz", second_provider),
        ]
    )

    try:
        client.fetch_company("03541629000137")
    except CnpjBizBlockedError as exc:
        assert [item.provider for item in exc.provider_trace] == ["brasilapi", "cnpjbiz"]
        assert [item.status for item in exc.provider_trace] == ["fetch_error", "blocked_by_cloudflare"]
        assert exc.provider_trace[0].error == "BrasilAPI failed with HTTP 429"
        assert exc.provider_trace[1].error == "cnpj.biz returned HTTP 403"
    else:
        raise AssertionError("expected CnpjBizBlockedError")


def test_multisource_client_expands_local_blurpath_request_trace():
    def provider(_: str) -> CompanyData:
        error = CnpjBizError("local blurpath timeout")
        error.clearance_trace = [
            {
                "provider": "blurpath",
                "stage": "request",
                "code": "",
                "region": "BR",
                "port": 15129,
                "proxy_format": "http",
                "attempt": 1,
                "error": "local blurpath timeout",
            }
        ]
        raise error

    client = MultiSourceCompanyClient(providers=[("cnpjbiz", provider)])

    try:
        client.fetch_company("03541629000137")
    except CnpjBizError as exc:
        assert [item.provider for item in exc.provider_trace] == [
            "cnpjbiz",
            "cnpjbiz.blurpath",
        ]
        assert [item.status for item in exc.provider_trace] == [
            "fetch_error",
            "fetch_error",
        ]
        assert exc.provider_trace[1].error == "region=BR port=15129 format=http attempt=1 stage=request error=local blurpath timeout"
    else:
        raise AssertionError("expected CnpjBizError")


def test_build_company_client_respects_provider_order():
    client = build_company_client(
        provider_order=["cnpjbiz", "brasilapi"],
    )

    assert [name for name, _fetcher in client.providers] == [
        "cnpjbiz.browser",
        "brasilapi",
    ]


def test_build_company_client_uses_browser_backed_cnpjbiz_provider(monkeypatch):
    import cnpj_tool.browser_scraper as browser_scraper_module
    from cnpj_tool.cf_bypass import BlurpathProxyConfig

    proxy_configs_seen = []
    browser_identities = []

    class FakeBrowserClient:
        def __init__(self, *, proxy_configs, user_agent, timeout_seconds, max_retries):
            proxy_configs_seen.append(proxy_configs)
            browser_identities.append(user_agent)

        def fetch_company(self, cnpj):
            return CompanyData(cnpj=cnpj, formatted_cnpj=cnpj, url=f"https://cnpj.biz/{cnpj}")

    monkeypatch.setattr(browser_scraper_module, "CnpjBizBrowserClient", FakeBrowserClient)
    client = build_company_client(
        provider_order=["cnpjbiz"],
        cnpj_biz_proxy_configs=[
            BlurpathProxyConfig(host="blurpath.net", port=15121, username="acct", password="secret"),
        ],
        cnpj_biz_user_agent="Mozilla/5.0 Chrome/146",
    )

    client.fetch_company("03541629000137")
    client.fetch_company("21746991000126")

    assert len(proxy_configs_seen) == 1
    assert proxy_configs_seen[0][0].port == 15121
    assert browser_identities == ["Mozilla/5.0 Chrome/146"]


def test_cached_company_client_reuses_previous_success():
    expected = CompanyData(
        cnpj="03541629000137",
        formatted_cnpj="03.541.629/0001-37",
        url="https://example.test/company/03541629000137",
        legal_name="ORGANIZACOES MARQUES CENTER LTDA",
    )
    calls = {"count": 0}

    def fetcher(_: str) -> CompanyData:
        calls["count"] += 1
        return expected

    client = CachedCompanyClient(fetcher)

    first = client.fetch_company("03.541.629/0001-37")
    second = client.fetch_company("03541629000137")

    assert first is expected
    assert second is expected
    assert calls["count"] == 1
