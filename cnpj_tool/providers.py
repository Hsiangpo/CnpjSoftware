from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from curl_cffi import requests

from .cf_bypass import BlurpathProxyConfig
from .cnpj import format_cnpj, normalize_cnpj, validate_cnpj
from .models import Candidate, CompanyData, ProviderTraceEntry
from .scraper import CnpjBizError, CnpjBizNotFoundError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class ProviderError(CnpjBizError):
    status = "fetch_error"


def _should_proxy_retry_status(status_code: int) -> bool:
    return status_code in {403, 423, 429} or status_code >= 500


def _proxy_trace_entry(
    config: BlurpathProxyConfig,
    *,
    attempt: int,
    stage: str,
    error: str,
    code: str = "",
) -> dict[str, Any]:
    return {
        "provider": "blurpath",
        "stage": stage,
        "code": code,
        "region": config.region or "RANDOM",
        "port": config.port,
        "proxy_format": config.protocol,
        "attempt": attempt,
        "error": error,
    }


def _provider_trace_entry(provider: str, exc: Exception) -> ProviderTraceEntry:
    return ProviderTraceEntry(
        provider=provider,
        status=str(getattr(exc, "status", "fetch_error") or "fetch_error"),
        error=str(exc),
    )


def _provider_trace_entries(provider: str, exc: Exception) -> list[ProviderTraceEntry]:
    status = str(getattr(exc, "status", "fetch_error") or "fetch_error")
    entries = [_provider_trace_entry(provider, exc)]
    for item in getattr(exc, "clearance_trace", []) or []:
        nested_provider = _safe_string(item.get("provider")) if isinstance(item, dict) else ""
        if not nested_provider:
            continue
        region = _safe_string(item.get("region"))
        port = _safe_string(item.get("port"))
        proxy_format = _safe_string(item.get("proxy_format"))
        stage = _safe_string(item.get("stage"))
        attempt = _safe_string(item.get("attempt"))
        code = _safe_string(item.get("code"))
        error = _safe_string(item.get("error"))
        attempt_text = f" attempt={attempt}" if attempt else ""
        stage_text = f" stage={stage}" if stage else ""
        code_text = f" code={code}" if code else ""
        entries.append(
            ProviderTraceEntry(
                provider=f"{provider}.{nested_provider}",
                status=status,
                error=f"region={region} port={port} format={proxy_format}{attempt_text}{stage_text}{code_text} error={error}",
            )
        )
    return entries


def canonical_company_url(cnpj: str) -> str:
    return f"https://cnpj.biz/{normalize_cnpj(cnpj)}"


def _safe_string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _compose_cnae(code: Any, description: Any) -> str:
    left = _safe_string(code)
    right = _safe_string(description)
    if left and right:
        return f"{left} - {right}"
    return left or right


def _parse_receitaws_role(value: str) -> str:
    text = _safe_string(value)
    if "-" not in text:
        return text
    parts = text.split("-", 1)
    if parts[0].isdigit():
        return parts[1].strip()
    return text


def _looks_like_not_found_message(message: str) -> bool:
    lowered = _safe_string(message).casefold()
    markers = [
        "not found",
        "não encontrado",
        "nao encontrado",
        "não existe",
        "nao existe",
        "inexistente",
    ]
    return any(marker in lowered for marker in markers)


def _build_qsa_text(candidates: list[Candidate]) -> str:
    return "\n".join(f"{candidate.name} - {candidate.role}" for candidate in candidates if candidate.name)


def _with_source(company: CompanyData, *, provider: str, proxy_port: int = 0) -> CompanyData:
    company.source_provider = provider
    company.source_proxy_port = proxy_port
    return company


def _phones_from_brasilapi(data: dict[str, Any]) -> list[str]:
    phones: list[str] = []
    for key in ("ddd_telefone_1", "ddd_telefone_2"):
        value = _safe_string(data.get(key))
        if value:
            phones.append(value)
    return phones


def _phones_from_receitaws(data: dict[str, Any]) -> list[str]:
    raw = _safe_string(data.get("telefone"))
    if not raw:
        return []
    return [item.strip() for item in raw.split(" / ") if item.strip()]


def parse_brasilapi_company(data: dict[str, Any]) -> CompanyData:
    cnpj = normalize_cnpj(_safe_string(data.get("cnpj")))
    if not validate_cnpj(cnpj):
        raise ProviderError("BrasilAPI returned an invalid CNPJ payload")

    candidates = [
        Candidate(
            name=_safe_string(item.get("nome_socio")),
            role=_safe_string(item.get("qualificacao_socio")),
            cnpj=cnpj,
        )
        for item in data.get("qsa") or []
        if _safe_string(item.get("nome_socio"))
    ]

    return CompanyData(
        cnpj=cnpj,
        formatted_cnpj=format_cnpj(cnpj),
        url=canonical_company_url(cnpj),
        page_title="BrasilAPI",
        legal_name=_safe_string(data.get("razao_social")),
        trade_name=_safe_string(data.get("nome_fantasia")),
        opening_date=_safe_string(data.get("data_inicio_atividade")),
        size=_safe_string(data.get("porte")),
        legal_nature=_safe_string(data.get("natureza_juridica")),
        mei_option=_safe_string(data.get("opcao_pelo_mei")),
        simples_option=_safe_string(data.get("opcao_pelo_simples")),
        capital=_safe_string(data.get("capital_social")),
        company_type=_safe_string(data.get("descricao_identificador_matriz_filial")),
        status=_safe_string(data.get("descricao_situacao_cadastral") or data.get("situacao_cadastral")),
        status_date=_safe_string(data.get("data_situacao_cadastral")),
        email=_safe_string(data.get("email")),
        phones=_phones_from_brasilapi(data),
        street=" ".join(
            part
            for part in [
                _safe_string(data.get("descricao_tipo_de_logradouro")),
                _safe_string(data.get("logradouro")),
                _safe_string(data.get("numero")),
                _safe_string(data.get("complemento")),
            ]
            if part
        ),
        district=_safe_string(data.get("bairro")),
        zip_code=_safe_string(data.get("cep")),
        city=_safe_string(data.get("municipio")),
        state=_safe_string(data.get("uf")),
        primary_cnae=_compose_cnae(data.get("cnae_fiscal"), data.get("cnae_fiscal_descricao")),
        secondary_cnaes=[
            _compose_cnae(item.get("codigo"), item.get("descricao"))
            for item in data.get("cnaes_secundarios") or []
            if _compose_cnae(item.get("codigo"), item.get("descricao"))
        ],
        qsa_text=_build_qsa_text(candidates),
        responsible_qualification=_safe_string(data.get("qualificacao_do_responsavel")),
        candidates=candidates,
    )


def parse_receitaws_company(data: dict[str, Any]) -> CompanyData:
    if _safe_string(data.get("status")).upper() == "ERROR":
        message = _safe_string(data.get("message")) or "ReceitaWS returned an error"
        if _looks_like_not_found_message(message):
            raise CnpjBizNotFoundError(message)
        raise ProviderError(message)

    cnpj = normalize_cnpj(_safe_string(data.get("cnpj")))
    if not validate_cnpj(cnpj):
        raise ProviderError("ReceitaWS returned an invalid CNPJ payload")

    candidates = [
        Candidate(
            name=_safe_string(item.get("nome")),
            role=_parse_receitaws_role(_safe_string(item.get("qual"))),
            cnpj=cnpj,
        )
        for item in data.get("qsa") or []
        if _safe_string(item.get("nome"))
    ]

    primary = ""
    if data.get("atividade_principal"):
        item = data["atividade_principal"][0]
        primary = _compose_cnae(item.get("code"), item.get("text"))

    return CompanyData(
        cnpj=cnpj,
        formatted_cnpj=format_cnpj(cnpj),
        url=canonical_company_url(cnpj),
        page_title="ReceitaWS",
        legal_name=_safe_string(data.get("nome")),
        trade_name=_safe_string(data.get("fantasia")),
        opening_date=_safe_string(data.get("abertura")),
        size=_safe_string(data.get("porte")),
        legal_nature=_safe_string(data.get("natureza_juridica")),
        simples_option=_safe_string(data.get("simples")),
        mei_option=_safe_string(data.get("simei")),
        capital=_safe_string(data.get("capital_social")),
        company_type=_safe_string(data.get("tipo")),
        status=_safe_string(data.get("situacao")),
        status_date=_safe_string(data.get("data_situacao")),
        email=_safe_string(data.get("email")),
        phones=_phones_from_receitaws(data),
        street=" ".join(
            part
            for part in [
                _safe_string(data.get("logradouro")),
                _safe_string(data.get("numero")),
                _safe_string(data.get("complemento")),
            ]
            if part
        ),
        district=_safe_string(data.get("bairro")),
        zip_code=_safe_string(data.get("cep")),
        city=_safe_string(data.get("municipio")),
        state=_safe_string(data.get("uf")),
        primary_cnae=primary,
        secondary_cnaes=[
            _compose_cnae(item.get("code"), item.get("text"))
            for item in data.get("atividades_secundarias") or []
            if _compose_cnae(item.get("code"), item.get("text"))
        ],
        qsa_text=_build_qsa_text(candidates),
        candidates=candidates,
    )


@dataclass
class BrasilAPIClient:
    timeout_seconds: float = 20
    proxy_configs: list[BlurpathProxyConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self._session_type = type(self.session)
        self._local = threading.local()

    def _get_session(self):
        if not isinstance(self.session, self._session_type):
            return self.session
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _fetch_via_proxy(self, digits: str) -> CompanyData:
        last_error: Exception | None = None
        trace: list[dict[str, Any]] = []
        for attempt, config in enumerate(self.proxy_configs, start=1):
            session_id = uuid.uuid4().hex[:8]
            try:
                response = self._get_session().get(
                    f"https://brasilapi.com.br/api/cnpj/v1/{digits}",
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
                    timeout=self.timeout_seconds,
                    impersonate="chrome136",
                    proxies=config.requests_proxies(session_id),
                )
            except Exception as exc:
                trace.append(
                    _proxy_trace_entry(
                        config,
                        attempt=attempt,
                        stage="request",
                        error=str(exc),
                    )
                )
                last_error = ProviderError(str(exc))
                continue
            if response.status_code == 404:
                raise CnpjBizNotFoundError(f"BrasilAPI did not find CNPJ {digits}")
            if response.status_code == 200:
                return _with_source(parse_brasilapi_company(response.json()), provider="brasilapi.proxy", proxy_port=config.port)
            if _should_proxy_retry_status(response.status_code):
                error = (
                    "BrasilAPI rate limited the request"
                    if response.status_code == 429
                    else f"BrasilAPI failed with HTTP {response.status_code}"
                )
                trace.append(
                    _proxy_trace_entry(
                        config,
                        attempt=attempt,
                        stage="response",
                        code=f"HTTP_{response.status_code}",
                        error=error,
                    )
                )
                last_error = ProviderError(error)
                continue
            raise ProviderError(f"BrasilAPI failed with HTTP {response.status_code}")
        if last_error is None:
            last_error = ProviderError("BrasilAPI proxy fallback failed")
        last_error.clearance_trace = trace
        raise last_error

    def fetch_company(self, cnpj: str) -> CompanyData:
        digits = normalize_cnpj(cnpj)
        try:
            response = self._get_session().get(
                f"https://brasilapi.com.br/api/cnpj/v1/{digits}",
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout_seconds,
                impersonate="chrome136",
            )
        except Exception as exc:
            if self.proxy_configs:
                return self._fetch_via_proxy(digits)
            raise ProviderError(str(exc)) from exc
        if response.status_code == 404:
            raise CnpjBizNotFoundError(f"BrasilAPI did not find CNPJ {digits}")
        if _should_proxy_retry_status(response.status_code):
            if self.proxy_configs:
                return self._fetch_via_proxy(digits)
            if response.status_code == 429:
                raise ProviderError("BrasilAPI rate limited the request")
            raise ProviderError(f"BrasilAPI failed with HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"BrasilAPI failed with HTTP {response.status_code}")
        return _with_source(parse_brasilapi_company(response.json()), provider="brasilapi.direct")


@dataclass
class ReceitaWSClient:
    timeout_seconds: float = 20
    proxy_configs: list[BlurpathProxyConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self._session_type = type(self.session)
        self._local = threading.local()

    def _get_session(self):
        if not isinstance(self.session, self._session_type):
            return self.session
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _fetch_via_proxy(self, digits: str) -> CompanyData:
        last_error: Exception | None = None
        trace: list[dict[str, Any]] = []
        for attempt, config in enumerate(self.proxy_configs, start=1):
            session_id = uuid.uuid4().hex[:8]
            try:
                response = self._get_session().get(
                    f"https://www.receitaws.com.br/v1/cnpj/{digits}",
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
                    timeout=self.timeout_seconds,
                    impersonate="chrome136",
                    proxies=config.requests_proxies(session_id),
                )
            except Exception as exc:
                trace.append(
                    _proxy_trace_entry(
                        config,
                        attempt=attempt,
                        stage="request",
                        error=str(exc),
                    )
                )
                last_error = ProviderError(str(exc))
                continue
            if response.status_code == 404:
                raise CnpjBizNotFoundError(f"ReceitaWS did not find CNPJ {digits}")
            if response.status_code == 200:
                try:
                    return _with_source(parse_receitaws_company(response.json()), provider="receitaws.proxy", proxy_port=config.port)
                except CnpjBizNotFoundError:
                    raise
                except ProviderError as exc:
                    trace.append(
                        _proxy_trace_entry(
                            config,
                            attempt=attempt,
                            stage="payload",
                            error=str(exc),
                            code="BODY_ERROR",
                        )
                    )
                    last_error = exc
                    continue
            if _should_proxy_retry_status(response.status_code):
                error = (
                    "ReceitaWS rate limited the request"
                    if response.status_code == 429
                    else f"ReceitaWS failed with HTTP {response.status_code}"
                )
                trace.append(
                    _proxy_trace_entry(
                        config,
                        attempt=attempt,
                        stage="response",
                        code=f"HTTP_{response.status_code}",
                        error=error,
                    )
                )
                last_error = ProviderError(error)
                continue
            raise ProviderError(f"ReceitaWS failed with HTTP {response.status_code}")
        if last_error is None:
            last_error = ProviderError("ReceitaWS proxy fallback failed")
        last_error.clearance_trace = trace
        raise last_error

    def fetch_company(self, cnpj: str) -> CompanyData:
        digits = normalize_cnpj(cnpj)
        try:
            response = self._get_session().get(
                f"https://www.receitaws.com.br/v1/cnpj/{digits}",
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout_seconds,
                impersonate="chrome136",
            )
        except Exception as exc:
            if self.proxy_configs:
                return self._fetch_via_proxy(digits)
            raise ProviderError(str(exc)) from exc
        if response.status_code == 404:
            raise CnpjBizNotFoundError(f"ReceitaWS did not find CNPJ {digits}")
        if _should_proxy_retry_status(response.status_code):
            if self.proxy_configs:
                return self._fetch_via_proxy(digits)
            if response.status_code == 429:
                raise ProviderError("ReceitaWS rate limited the request")
            raise ProviderError(f"ReceitaWS failed with HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"ReceitaWS failed with HTTP {response.status_code}")
        try:
            return _with_source(parse_receitaws_company(response.json()), provider="receitaws.direct")
        except CnpjBizNotFoundError:
            raise
        except ProviderError:
            if self.proxy_configs:
                return self._fetch_via_proxy(digits)
            raise


@dataclass
class MultiSourceCompanyClient:
    providers: list[tuple[str, Callable[[str], CompanyData]]]

    def fetch_company(self, cnpj: str) -> CompanyData:
        last_error: Exception | None = None
        saw_not_found = False
        provider_trace: list[ProviderTraceEntry] = []
        for name, fetcher in self.providers:
            try:
                return fetcher(cnpj)
            except CnpjBizNotFoundError as exc:
                provider_trace.extend(_provider_trace_entries(name, exc))
                last_error = exc
                saw_not_found = True
                continue
            except Exception as exc:
                provider_trace.extend(_provider_trace_entries(name, exc))
                last_error = exc
                continue
        if saw_not_found and isinstance(last_error, CnpjBizNotFoundError):
            last_error.provider_trace = provider_trace
            raise last_error
        if last_error:
            last_error.provider_trace = provider_trace
            raise last_error
        error = ProviderError("No company providers are configured")
        error.provider_trace = []
        raise error


class CachedCompanyClient:
    def __init__(
        self,
        fetcher: Callable[[str], CompanyData],
        providers: list[tuple[str, Callable[[str], CompanyData]]] | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.providers = providers or []
        self.search_companies: Callable[[str], list] | None = None
        self.search_browser: Any | None = None
        self._cache: dict[str, CompanyData] = {}
        self._lock = threading.Lock()

    def fetch_company(self, cnpj: str) -> CompanyData:
        digits = normalize_cnpj(cnpj)
        with self._lock:
            cached = self._cache.get(digits)
        if cached:
            return cached
        company = self.fetcher(digits)
        with self._lock:
            self._cache[digits] = company
        return company

    def close(self) -> None:
        seen: set[int] = set()
        for _name, fetcher in self.providers:
            owner = getattr(fetcher, "__self__", None)
            if owner is None:
                continue
            owner_id = id(owner)
            if owner_id in seen:
                continue
            seen.add(owner_id)
            close = getattr(owner, "close", None)
            if callable(close):
                close()
        browser = self.search_browser
        if browser is not None and id(browser) not in seen:
            close = getattr(browser, "close", None)
            if callable(close):
                close()


def build_company_client(
    provider_order: list[str],
    cnpj_biz_proxy_configs: list[BlurpathProxyConfig] | None = None,
    cnpj_biz_user_agent: str = "",
) -> MultiSourceCompanyClient:
    from .browser_scraper import CnpjBizBrowserClient
    from .scraper import DEFAULT_USER_AGENT

    cnpjbiz_browser = CnpjBizBrowserClient(
        proxy_configs=cnpj_biz_proxy_configs or [],
        user_agent=cnpj_biz_user_agent or DEFAULT_USER_AGENT,
        timeout_seconds=25,
        max_retries=max(2, len(cnpj_biz_proxy_configs or []) or 1),
    )

    builders: dict[str, Callable[[], Callable[[str], CompanyData]]] = {
        "brasilapi": lambda: BrasilAPIClient(proxy_configs=cnpj_biz_proxy_configs or []).fetch_company,
        "receitaws": lambda: ReceitaWSClient(proxy_configs=cnpj_biz_proxy_configs or []).fetch_company,
        "cnpjbiz": lambda: cnpjbiz_browser.fetch_company,
    }
    provider_labels = {
        "brasilapi": "brasilapi",
        "receitaws": "receitaws",
        "cnpjbiz": "cnpjbiz.browser",
    }
    providers: list[tuple[str, Callable[[str], CompanyData]]] = []
    for item in provider_order:
        key = (item or "").strip().casefold()
        if key in builders:
            providers.append((provider_labels.get(key, key), builders[key]()))
    multi_source = MultiSourceCompanyClient(providers=providers)
    client = CachedCompanyClient(multi_source.fetch_company, providers=providers)
    client.search_companies = getattr(cnpjbiz_browser, "search_companies", None)
    client.search_browser = cnpjbiz_browser
    return client
