from fastapi.testclient import TestClient

from cnpj_tool.server import create_app


def test_removed_legacy_endpoints_return_404(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("CNPJ_TOOL_ENV_FILE", str(env_path))
    client = TestClient(create_app(auto_run_jobs=False))

    for method, path in [
        ("get", "/api/cf-bypass/preflight"),
        ("get", "/api/cf-bypass/proxy-preflight"),
        ("post", "/api/cf-bypass/challenge-diagnostic"),
        ("post", "/api/parse-file"),
        ("get", "/api/jobs/missing/download.csv"),
        ("get", "/api/jobs/missing/download.json"),
        ("get", "/api/jobs/missing/download.xlsx"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404


def test_proxy_preflight_endpoint_replaces_legacy_cf_bypass_route(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BLURPATH_PROXY_HOST=blurpath.net",
                "BLURPATH_PROXY_PORTS=15121,15129",
                "BLURPATH_PROXY_USERNAME=acct",
                "BLURPATH_PROXY_PASSWORD=pass",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CNPJ_TOOL_ENV_FILE", str(env_path))
    client = TestClient(create_app(auto_run_jobs=False))

    response = client.get("/api/proxy-preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["proxy_configured"] is True
    assert payload["ports"] == [15121, 15129]
