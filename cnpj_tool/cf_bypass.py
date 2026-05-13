from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from curl_cffi import requests


def _new_session_id(length: int = 4) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _is_generated_blurpath_username(value: str) -> bool:
    text = (value or "").strip().casefold()
    if not text:
        return False
    markers = [
        "-zone-",
        "-session-",
        "-sessiontime-",
        "-st--city--",
    ]
    return any(marker in text for marker in markers)


@dataclass(frozen=True)
class BlurpathProxyConfig:
    host: str
    port: int
    username: str
    password: str
    region: str = "BR"
    protocol: str = "http"
    session_time_minutes: int = 10
    username_template: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.username and self.password)

    def session_username(self, session_id: str) -> str:
        if self.username_template:
            return self.username_template.format(
                username=self.username,
                region=self.region,
                session=session_id,
                session_time=self.session_time_minutes,
            )
        if "{session}" in self.username:
            return self.username.format(
                region=self.region,
                session=session_id,
                session_time=self.session_time_minutes,
            )
        if _is_generated_blurpath_username(self.username):
            return self.username
        if self.protocol.casefold() == "socks5":
            return f"{self.username}-zone-resi-region-{self.region}-session-{session_id}"
        return (
            f"{self.username}-zone-resi-region-{self.region}-st--city--"
            f"session-{session_id}-sessionTime-{self.session_time_minutes}"
        )

    def proxy_url(self, session_id: str, host: str | None = None) -> str:
        username = quote(self.session_username(session_id), safe="")
        password = quote(self.password, safe="")
        scheme = "socks5" if self.protocol.casefold() == "socks5" else "http"
        return f"{scheme}://{username}:{password}@{host or self.host}:{self.port}"

    def requests_proxies(self, session_id: str) -> dict[str, str]:
        proxy_url = self.proxy_url(session_id)
        return {"http": proxy_url, "https": proxy_url}


def build_playwright_proxy(config: BlurpathProxyConfig, session_id: str) -> dict[str, str]:
    scheme = "socks5" if config.protocol.casefold() == "socks5" else "http"
    return {
        "server": f"{scheme}://{config.host}:{config.port}",
        "username": config.session_username(session_id),
        "password": config.password,
    }


def probe_blurpath_proxy(
    config: BlurpathProxyConfig,
    *,
    session_id: str | None = None,
    session: Any | None = None,
    timeout_seconds: float = 10,
    probe_url: str = "https://api.ipify.org",
    impersonate: str = "chrome136",
) -> dict[str, Any]:
    result = {
        "provider": "blurpath",
        "ok": False,
        "region": config.region or "RANDOM",
        "port": config.port,
        "protocol": config.protocol,
        "status_code": None,
        "ip": "",
        "error": "",
    }
    if not config.configured:
        result["error"] = "Blurpath proxy is not configured"
        return result

    client = session or requests.Session()
    try:
        response = client.get(
            probe_url,
            proxies=config.requests_proxies(session_id or _new_session_id()),
            timeout=timeout_seconds,
            impersonate=impersonate,
        )
    except Exception as exc:
        result["error"] = str(exc).replace(config.username, "<redacted>").replace(config.password, "<redacted>")
        return result

    result["status_code"] = response.status_code
    if 200 <= response.status_code < 400:
        result["ok"] = True
        result["ip"] = str(response.text or "").strip()[:128]
    else:
        result["error"] = f"HTTP {response.status_code}"
    return result
