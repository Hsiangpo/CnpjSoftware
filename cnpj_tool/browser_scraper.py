from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import sync_playwright

from .cf_bypass import BlurpathProxyConfig, build_playwright_proxy
from .cnpj import normalize_cnpj, validate_cnpj
from .name_search import CompanySearchResult, parse_search_results
from .name_search import search_url as build_search_url
from .parser import parse_company_page
from .scraper import (
    CnpjBizBlockedError,
    CnpjBizError,
    CnpjBizNotFoundError,
    DEFAULT_USER_AGENT,
    is_cloudflare_challenge,
)
@dataclass
class _BrowserThreadState:
    playwright: Any
    browser: Any
    context: Any
    proxy_index: int
    session_id: str


class CnpjBizBrowserClient:
    def __init__(
        self,
        *,
        proxy_configs: list[BlurpathProxyConfig] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 25,
        challenge_wait_seconds: float = 8,
        max_retries: int = 2,
        executable_path: str | None = None,
        headless: bool = True,
    ) -> None:
        self.proxy_configs = list(proxy_configs or [])
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout_seconds = timeout_seconds
        self.challenge_wait_seconds = challenge_wait_seconds
        self.max_retries = max(1, int(max_retries or 1))
        self.executable_path = (executable_path or "").strip()
        self.headless = headless
        self._local = threading.local()
        self._lock = threading.Lock()
        self._next_proxy_index = 0
        self._states: dict[int, _BrowserThreadState] = {}

    def detail_url(self, cnpj: str) -> str:
        digits = normalize_cnpj(cnpj)
        if not validate_cnpj(digits):
            raise ValueError("Invalid CNPJ")
        return f"https://cnpj.biz/{digits}"

    def _assign_proxy_index(self) -> int:
        if not self.proxy_configs:
            return 0
        with self._lock:
            index = self._next_proxy_index % len(self.proxy_configs)
            self._next_proxy_index += 1
        return index

    def _thread_state(self) -> _BrowserThreadState:
        state = getattr(self._local, "state", None)
        if state is None:
            state = self._create_thread_state()
            self._local.state = state
            with self._lock:
                self._states[threading.get_ident()] = state
        return state

    def _create_thread_state(self, proxy_index: int | None = None) -> _BrowserThreadState:
        index = proxy_index if proxy_index is not None else self._assign_proxy_index()
        playwright = None
        browser = None
        context = None
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        session_id = uuid.uuid4().hex[:8]
        if self.proxy_configs:
            config = self.proxy_configs[index % len(self.proxy_configs)]
            launch_kwargs["proxy"] = build_playwright_proxy(config, session_id)
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                user_agent=self.user_agent,
                locale="pt-BR",
                extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"},
            )
            return _BrowserThreadState(
                playwright=playwright,
                browser=browser,
                context=context,
                proxy_index=index,
                session_id=session_id,
            )
        except Exception:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            raise

    def _close_state(self, state: _BrowserThreadState | None) -> int | None:
        if state is None:
            return None
        next_index = state.proxy_index + 1
        try:
            state.context.close()
        except Exception:
            pass
        try:
            state.browser.close()
        except Exception:
            pass
        try:
            state.playwright.stop()
        except Exception:
            pass
        return next_index

    def _close_thread_state(self, thread_id: int | None = None) -> int | None:
        current_thread_id = threading.get_ident() if thread_id is None else thread_id
        with self._lock:
            state = self._states.pop(current_thread_id, None)
        local_state = getattr(self._local, "state", None)
        if local_state is state:
            self._local.state = None
        return self._close_state(state)

    def _rotate_thread_state(self) -> None:
        thread_id = threading.get_ident()
        next_index = self._close_thread_state(thread_id)
        if next_index is not None:
            state = self._create_thread_state(proxy_index=next_index)
            self._local.state = state
            with self._lock:
                self._states[thread_id] = state

    def _fetch_html_once(self, url: str) -> str:
        page = None
        try:
            state = self._thread_state()
            page = state.context.new_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(self.timeout_seconds * 1000),
            )
            status_code = int(getattr(response, "status", 200) or 200)
            if status_code == 404:
                raise CnpjBizNotFoundError(f"CNPJ not found: {url.rsplit('/', 1)[-1]}")
            deadline = time.monotonic() + self.challenge_wait_seconds
            while True:
                html = page.content()
                if not is_cloudflare_challenge(html):
                    if status_code >= 500:
                        raise CnpjBizError(f"cnpj.biz returned HTTP {status_code}")
                    if status_code != 200 and status_code not in {401, 403, 423}:
                        raise CnpjBizError(f"cnpj.biz returned HTTP {status_code}")
                    return html
                if time.monotonic() >= deadline:
                    raise CnpjBizBlockedError("Cloudflare challenge persisted in browser session")
                page.wait_for_timeout(1000)
        except (CnpjBizBlockedError, CnpjBizError, CnpjBizNotFoundError):
            raise
        except Exception as exc:
            raise CnpjBizError(str(exc)) from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def fetch_html(self, cnpj: str) -> str:
        return self._fetch_url_with_retry(self.detail_url(cnpj))

    def _fetch_url_with_retry(self, url: str) -> str:
        last_error: Exception | None = None
        attempts = max(self.max_retries, len(self.proxy_configs) or 1)
        for attempt in range(attempts):
            try:
                return self._fetch_html_once(url)
            except CnpjBizNotFoundError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    break
                self._rotate_thread_state()
        if isinstance(last_error, Exception):
            raise last_error
        raise CnpjBizError("Failed to fetch cnpj.biz page in browser")

    def search_url(self, name: str) -> str:
        return build_search_url(name)

    def search_companies(self, name: str) -> list[CompanySearchResult]:
        query = (name or "").strip()
        if not query:
            return []
        try:
            html = self._fetch_url_with_retry(self.search_url(query))
        except CnpjBizNotFoundError:
            return []
        return parse_search_results(html)

    def fetch_company(self, cnpj: str):
        url = self.detail_url(cnpj)
        company = parse_company_page(self.fetch_html(cnpj), url)
        company.source_provider = "cnpjbiz.browser"
        state = getattr(self._local, "state", None)
        if state is not None and self.proxy_configs:
            company.source_proxy_port = self.proxy_configs[state.proxy_index % len(self.proxy_configs)].port
        return company

    def close(self) -> None:
        with self._lock:
            thread_ids = list(self._states.keys())
        for thread_id in thread_ids:
            self._close_thread_state(thread_id)
