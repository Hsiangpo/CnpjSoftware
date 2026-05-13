from cnpj_tool.config import load_settings


def test_load_settings_parses_blurpath_proxy_port_pool(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BLURPATH_PROXY_HOST=blurpath.net",
                "BLURPATH_PROXY_PORT=15121",
                "BLURPATH_PROXY_PORTS=15121,15129,15133",
                "BLURPATH_PROXY_PROTOCOL=socks5",
                "BLURPATH_PROXY_USERNAME=acct",
                "BLURPATH_PROXY_PASSWORD=pass",
                "BLURPATH_PROXY_NODES=",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CNPJ_TOOL_ENV_FILE", str(env_path))

    settings = load_settings()

    assert settings.blurpath_proxy_port == 15121
    assert settings.blurpath_proxy_ports == [15121, 15129, 15133]
    assert settings.blurpath_proxy_protocol == "socks5"
    assert settings.blurpath_proxy_configured is True


def test_load_settings_parses_blurpath_proxy_nodes(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BLURPATH_PROXY_HOST=",
                "BLURPATH_PROXY_USERNAME=",
                "BLURPATH_PROXY_PASSWORD=",
                "BLURPATH_PROXY_PORTS=",
                "BLURPATH_PROXY_NODES=http://acct-zone-resi-region-BR-st--city--session-abcd-sessionTime-10:pass@blurpath.net:15129|socks5://acct-zone-resi-region-BR-session-wxyz:pass@blurpath.net:15121",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CNPJ_TOOL_ENV_FILE", str(env_path))

    settings = load_settings()

    assert settings.blurpath_proxy_host == "blurpath.net"
    assert settings.blurpath_proxy_port == 15129
    assert settings.blurpath_proxy_ports == [15129, 15121]
    assert settings.blurpath_proxy_protocol == "http"
    assert settings.blurpath_proxy_username.startswith("acct-zone-resi-region-BR")
    assert settings.blurpath_proxy_password == "pass"
    assert [node.protocol for node in settings.blurpath_proxy_nodes] == ["http", "socks5"]
    public = settings.to_public_dict()
    assert "<redacted>" in public["blurpath_proxy_nodes"][0]
    assert "pass" not in str(public["blurpath_proxy_nodes"])


def test_load_settings_parses_cnpjbiz_browser_identity(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("CNPJ_BIZ_USER_AGENT=Mozilla/5.0 Chrome/146\n", encoding="utf-8")
    monkeypatch.setenv("CNPJ_TOOL_ENV_FILE", str(env_path))

    settings = load_settings()

    assert settings.cnpj_biz_user_agent == "Mozilla/5.0 Chrome/146"
