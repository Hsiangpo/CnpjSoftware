from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv


DEFAULT_LLM_BASE_URLS = [
    "https://api.gpteamservices.com/v1",
    "https://api-hk.gpteamservices.com/v1",
    "https://api-us.gpteamservices.com/v1",
    "https://api-jp.gpteamservices.com/v1",
]
DEFAULT_PROVIDER_ORDER = ["brasilapi", "cnpjbiz"]
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_SYSTEM_CONCURRENCY = 3
DEFAULT_CNPJ_BIZ_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
_MANAGED_ENV_VARS = [
    "LLM_API_KEY",
    "LLM_BASE_URLS",
    "LLM_MODEL",
    "LLM_FALLBACK_MODELS",
    "LLM_TIMEOUT_SECONDS",
    "SYSTEM_CONCURRENCY",
    "CNPJ_PROVIDER_ORDER",
    "CNPJ_BIZ_REQUEST_DELAY_SECONDS",
    "CNPJ_BIZ_USER_AGENT",
    "BLURPATH_PROXY_HOST",
    "BLURPATH_PROXY_PORT",
    "BLURPATH_PROXY_PORTS",
    "BLURPATH_PROXY_PROTOCOL",
    "BLURPATH_PROXY_USERNAME",
    "BLURPATH_PROXY_PASSWORD",
    "BLURPATH_PROXY_NODES",
    "BLURPATH_PROXY_REGION",
    "BLURPATH_PROXY_SESSION_TIME_MINUTES",
    "BLURPATH_PROXY_USERNAME_TEMPLATE",
]


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def env_file_path() -> Path:
    value = os.getenv("CNPJ_TOOL_ENV_FILE", "").strip()
    if value:
        return Path(value)
    return project_root() / ".env"


def checkpoint_dir_path() -> Path:
    value = os.getenv("CNPJ_TOOL_CHECKPOINT_DIR", "").strip()
    if value:
        return Path(value)
    return project_root() / "tmp" / "checkpoints"


def input_dir_path() -> Path:
    value = os.getenv("CNPJ_TOOL_INPUT_DIR", "").strip()
    if value:
        return Path(value)
    return project_root() / "cnpj"


def output_dir_path() -> Path:
    value = os.getenv("CNPJ_TOOL_OUTPUT_DIR", "").strip()
    if value:
        return Path(value)
    return project_root() / "output"


def _load_env_file() -> None:
    path = env_file_path()
    if path.exists():
        if os.getenv("CNPJ_TOOL_ENV_FILE", "").strip():
            for key in _MANAGED_ENV_VARS:
                os.environ.pop(key, None)
        load_dotenv(path, override=True)


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default)


def _parse_int_csv_env(name: str, default: list[int]) -> list[int]:
    value = os.getenv(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return list(default)
    return [int(item) for item in items]


def _normalize_proxy_ports(items: list[int], default: list[int]) -> list[int]:
    ports: list[int] = []
    for item in items:
        value = int(item)
        if value <= 0:
            raise ValueError(f"Unsupported Blurpath proxy port: {item}")
        if value not in ports:
            ports.append(value)
    return ports or list(default)


def _resolve_active_proxy_ports(nodes: list["BlurpathProxyNode"], configured_ports: list[int]) -> list[int]:
    available_ports = [node.port for node in nodes]
    if not configured_ports:
        return list(available_ports)
    ports = _normalize_proxy_ports(configured_ports, available_ports)
    for port in ports:
        if port not in available_ports:
            raise ValueError(f"Unsupported Blurpath proxy port: {port}")
    return ports


def _parse_multi_separator_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    items: list[str] = []
    for chunk in value.replace("\r", "\n").replace("|", "\n").replace(",", "\n").splitlines():
        text = chunk.strip()
        if text:
            items.append(text)
    return items


@dataclass(frozen=True)
class BlurpathProxyNode:
    host: str
    port: int
    username: str
    password: str
    protocol: str = "http"


def _parse_blurpath_proxy_node(value: str) -> BlurpathProxyNode:
    text = (value or "").strip()
    if not text:
        raise ValueError("BLURPATH_PROXY_NODES contains an empty entry")
    if "://" in text:
        parsed = urlsplit(text)
        protocol = parsed.scheme.strip().casefold() or "http"
        if protocol == "https":
            protocol = "http"
        if protocol not in {"http", "socks5"}:
            raise ValueError(f"Unsupported Blurpath proxy protocol: {parsed.scheme}")
        if not parsed.hostname or not parsed.port or parsed.username is None or parsed.password is None:
            raise ValueError("BLURPATH_PROXY_NODES URL entries must include host, port, username, and password")
        return BlurpathProxyNode(
            host=parsed.hostname,
            port=int(parsed.port),
            username=unquote(parsed.username),
            password=unquote(parsed.password),
            protocol=protocol,
        )

    parts = [part.strip() for part in text.split(":")]
    protocol = "http"
    if len(parts) == 5 and parts[0].casefold() in {"http", "https", "socks5"}:
        protocol = parts[0].casefold()
        if protocol == "https":
            protocol = "http"
        parts = parts[1:]
    if len(parts) != 4:
        raise ValueError(
            "BLURPATH_PROXY_NODES entries must be host:port:username:password, "
            "protocol:host:port:username:password, or protocol://username:password@host:port"
        )
    host, port, username, password = parts
    return BlurpathProxyNode(
        host=host,
        port=int(port),
        username=username,
        password=password,
        protocol=protocol,
    )


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_urls: list[str]
    llm_model: str
    llm_fallback_models: list[str]
    llm_timeout_seconds: float
    system_concurrency: int
    cnpj_provider_order: list[str]
    cnpj_biz_request_delay_seconds: float
    cnpj_biz_user_agent: str
    blurpath_proxy_host: str
    blurpath_proxy_port: int
    blurpath_proxy_ports: list[int]
    blurpath_proxy_protocol: str
    blurpath_proxy_username: str
    blurpath_proxy_password: str
    blurpath_proxy_nodes: list[BlurpathProxyNode]
    blurpath_proxy_region: str
    blurpath_proxy_session_time_minutes: int
    blurpath_proxy_username_template: str
    checkpoint_dir: Path
    input_dir: Path
    output_dir: Path

    @property
    def blurpath_proxy_configured(self) -> bool:
        if self.blurpath_proxy_nodes:
            return True
        return bool(
            self.blurpath_proxy_host
            and self.blurpath_proxy_ports
            and self.blurpath_proxy_username
            and self.blurpath_proxy_password
        )

    def to_public_dict(self) -> dict:
        data = asdict(self)
        data["checkpoint_dir"] = str(self.checkpoint_dir)
        data["input_dir"] = str(self.input_dir)
        data["output_dir"] = str(self.output_dir)
        data["llm_api_key"] = "<set>" if self.llm_api_key else ""
        data["blurpath_proxy_password"] = "<set>" if self.blurpath_proxy_password else ""
        data["blurpath_proxy_nodes"] = [
            f"{node.protocol}://<redacted>@{node.host}:{node.port}"
            for node in self.blurpath_proxy_nodes
        ]
        return data


def load_settings() -> Settings:
    _load_env_file()
    blurpath_region = os.getenv("BLURPATH_PROXY_REGION")
    blurpath_port = int(os.getenv("BLURPATH_PROXY_PORT", "15121") or "15121")
    configured_proxy_ports = _parse_int_csv_env("BLURPATH_PROXY_PORTS", [])
    blurpath_proxy_nodes = [
        _parse_blurpath_proxy_node(item)
        for item in _parse_multi_separator_env("BLURPATH_PROXY_NODES")
    ]
    first_proxy_node = blurpath_proxy_nodes[0] if blurpath_proxy_nodes else None
    active_proxy_ports = (
        _resolve_active_proxy_ports(blurpath_proxy_nodes, configured_proxy_ports)
        if blurpath_proxy_nodes
        else (configured_proxy_ports or [blurpath_port])
    )
    return Settings(
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_urls=[item.rstrip("/") for item in _parse_csv_env("LLM_BASE_URLS", DEFAULT_LLM_BASE_URLS)],
        llm_model=os.getenv("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        llm_fallback_models=_parse_csv_env("LLM_FALLBACK_MODELS", []),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        system_concurrency=max(1, int(os.getenv("SYSTEM_CONCURRENCY", str(DEFAULT_SYSTEM_CONCURRENCY)) or DEFAULT_SYSTEM_CONCURRENCY)),
        cnpj_provider_order=[item.casefold() for item in _parse_csv_env("CNPJ_PROVIDER_ORDER", DEFAULT_PROVIDER_ORDER)],
        cnpj_biz_request_delay_seconds=float(os.getenv("CNPJ_BIZ_REQUEST_DELAY_SECONDS", "0")),
        cnpj_biz_user_agent=os.getenv("CNPJ_BIZ_USER_AGENT", DEFAULT_CNPJ_BIZ_USER_AGENT).strip() or DEFAULT_CNPJ_BIZ_USER_AGENT,
        blurpath_proxy_host=os.getenv("BLURPATH_PROXY_HOST", "") or (first_proxy_node.host if first_proxy_node else ""),
        blurpath_proxy_port=active_proxy_ports[0],
        blurpath_proxy_ports=active_proxy_ports,
        blurpath_proxy_protocol=(
            first_proxy_node.protocol
            if first_proxy_node
            else (os.getenv("BLURPATH_PROXY_PROTOCOL", "http").strip().casefold() or "http")
        ),
        blurpath_proxy_username=os.getenv("BLURPATH_PROXY_USERNAME", "") or (first_proxy_node.username if first_proxy_node else ""),
        blurpath_proxy_password=os.getenv("BLURPATH_PROXY_PASSWORD", "") or (first_proxy_node.password if first_proxy_node else ""),
        blurpath_proxy_nodes=blurpath_proxy_nodes,
        blurpath_proxy_region="BR" if blurpath_region is None else blurpath_region,
        blurpath_proxy_session_time_minutes=int(os.getenv("BLURPATH_PROXY_SESSION_TIME_MINUTES", "10") or "10"),
        blurpath_proxy_username_template=os.getenv("BLURPATH_PROXY_USERNAME_TEMPLATE", ""),
        checkpoint_dir=checkpoint_dir_path(),
        input_dir=input_dir_path(),
        output_dir=output_dir_path(),
    )


def update_env_settings(updates: dict[str, str]) -> None:
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = {key: value for key, value in updates.items()}
    new_lines: list[str] = []

    for line in existing_lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def update_runtime_settings(
    *,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
    llm_fallback_models: list[str] | None = None,
    system_concurrency: int | None = None,
    blurpath_proxy_ports: list[int] | None = None,
    blurpath_proxy_host: str | None = None,
    blurpath_proxy_protocol: str | None = None,
    blurpath_proxy_username: str | None = None,
    blurpath_proxy_password: str | None = None,
    blurpath_proxy_region: str | None = None,
    blurpath_proxy_session_time_minutes: int | None = None,
) -> Settings:
    updates: dict[str, str] = {}
    current_settings = load_settings() if (
        blurpath_proxy_ports is not None
        or blurpath_proxy_host is not None
        or blurpath_proxy_protocol is not None
        or blurpath_proxy_username is not None
        or blurpath_proxy_password is not None
        or blurpath_proxy_region is not None
        or blurpath_proxy_session_time_minutes is not None
    ) else None
    if llm_api_key is not None and llm_api_key.strip() != "<set>":
        updates["LLM_API_KEY"] = llm_api_key
    if llm_model is not None:
        updates["LLM_MODEL"] = llm_model
    if llm_fallback_models is not None:
        updates["LLM_FALLBACK_MODELS"] = ",".join(item.strip() for item in llm_fallback_models if item.strip())
    if system_concurrency is not None:
        updates["SYSTEM_CONCURRENCY"] = str(max(1, system_concurrency))
    if blurpath_proxy_ports is not None:
        assert current_settings is not None
        default_ports = current_settings.blurpath_proxy_ports or [current_settings.blurpath_proxy_port]
        ports = _normalize_proxy_ports(blurpath_proxy_ports, default_ports)
        if current_settings.blurpath_proxy_nodes:
            for port in ports:
                if port not in {node.port for node in current_settings.blurpath_proxy_nodes}:
                    raise ValueError(f"Unsupported Blurpath proxy port: {port}")
        updates["BLURPATH_PROXY_PORTS"] = ",".join(str(port) for port in ports)
        updates["BLURPATH_PROXY_PORT"] = str(ports[0])
    direct_proxy_updated = False
    if blurpath_proxy_host is not None:
        updates["BLURPATH_PROXY_HOST"] = blurpath_proxy_host.strip()
        direct_proxy_updated = True
    if blurpath_proxy_protocol is not None:
        protocol = (blurpath_proxy_protocol.strip().casefold() or "http")
        if protocol == "https":
            protocol = "http"
        if protocol not in {"http", "socks5"}:
            raise ValueError(f"Unsupported Blurpath proxy protocol: {blurpath_proxy_protocol}")
        updates["BLURPATH_PROXY_PROTOCOL"] = protocol
        direct_proxy_updated = True
    if blurpath_proxy_username is not None:
        updates["BLURPATH_PROXY_USERNAME"] = blurpath_proxy_username.strip()
        direct_proxy_updated = True
    if blurpath_proxy_password is not None and blurpath_proxy_password.strip() != "<set>":
        updates["BLURPATH_PROXY_PASSWORD"] = blurpath_proxy_password
        direct_proxy_updated = True
    if blurpath_proxy_region is not None:
        updates["BLURPATH_PROXY_REGION"] = blurpath_proxy_region.strip().upper()
        direct_proxy_updated = True
    if blurpath_proxy_session_time_minutes is not None:
        updates["BLURPATH_PROXY_SESSION_TIME_MINUTES"] = str(max(1, int(blurpath_proxy_session_time_minutes)))
        direct_proxy_updated = True
    if direct_proxy_updated:
        updates["BLURPATH_PROXY_NODES"] = ""
    if updates:
        update_env_settings(updates)
    return load_settings()
