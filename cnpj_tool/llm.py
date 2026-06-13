from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from curl_cffi import requests

from .models import CompanyData, ResponsibleResult


def extract_json_object(text: str) -> dict[str, Any]:
    content = (text or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()

    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(content[start : end + 1])


@dataclass
class LLMClient:
    api_key: str
    base_urls: list[str]
    model: str
    fallback_models: list[str] | None = None
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self._session_type = type(self.session)
        self._local = threading.local()
        self.selected_base_url: str | None = None
        self.selected_model: str | None = None
        self.disabled_error: str = ""
        self._model_lock = threading.Lock()

    def _get_session(self):
        if not isinstance(self.session, self._session_type):
            return self.session
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def select_base_url(self) -> str:
        if self.disabled_error:
            raise ValueError(self.disabled_error)
        if self.selected_base_url:
            return self.selected_base_url
        if not self.api_key:
            raise ValueError("LLM_API_KEY is missing")

        timings: list[tuple[float, str]] = []
        for base_url in self.base_urls:
            started = time.perf_counter()
            try:
                response = self._get_session().get(
                    f"{base_url.rstrip('/')}/models",
                    headers=self.headers(),
                    timeout=min(self.timeout_seconds, 8),
                    impersonate="chrome136",
                )
                if response.status_code < 500 and response.status_code != 401:
                    timings.append((time.perf_counter() - started, base_url.rstrip("/")))
            except Exception:
                continue

        if timings:
            self.selected_base_url = sorted(timings, key=lambda item: item[0])[0][1]
            return self.selected_base_url

        self.selected_base_url = self.base_urls[0].rstrip("/")
        return self.selected_base_url

    def candidate_models(self) -> list[str]:
        models = [self.model]
        for item in self.fallback_models or []:
            if item and item not in models:
                models.append(item)
        return models

    def _post_chat(self, model: str, messages: list[dict[str, str]], timeout_seconds: float) -> Any:
        base_url = self.select_base_url()
        return self._get_session().post(
            f"{base_url}/chat/completions",
            headers=self.headers(),
            json={
                "model": model,
                "temperature": 0,
                "messages": messages,
            },
            timeout=timeout_seconds,
            impersonate="chrome136",
        )

    def preflight(self, chat_timeout_seconds: float = 6) -> bool:
        last_error = "LLM preflight failed"
        for model in self.candidate_models():
            try:
                response = self._post_chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Return JSON only."},
                        {"role": "user", "content": '{"ping": true}'},
                    ],
                    timeout_seconds=min(self.timeout_seconds, chat_timeout_seconds),
                )
                if response.status_code >= 400:
                    last_error = f"LLM preflight failed for {model} with HTTP {response.status_code}"
                    continue
                self.selected_model = model
                self.disabled_error = ""
                return True
            except Exception as exc:
                last_error = str(exc)
                continue
        self.disabled_error = last_error
        return False

    def selected_analysis_source(self) -> str:
        if self.selected_model and self.selected_model != self.model:
            return "llm_fallback_model"
        return "llm"

    def _system_prompt(self) -> str:
        return (
            "Analyze Brazilian CNPJ company registry data. "
            "Return exactly one JSON object with keys: "
            "names (array of strings), role (string), confidence (number from 0 to 1). "
            "Do not return objects inside names. "
            "If several people share the highest role, return all names."
        )

    def _parse_result(self, content: str) -> tuple[list[str], str, float]:
        parsed = extract_json_object(content)
        names = parsed.get("names") or parsed.get("name") or []
        role = str(parsed.get("role", ""))
        confidence_value = parsed.get("confidence", 0.0)

        if isinstance(names, str):
            names = [names]
        elif isinstance(names, list) and names and isinstance(names[0], dict):
            role = role or str(names[0].get("role", ""))
            derived_names = [str(item.get("name", "")).strip() for item in names if str(item.get("name", "")).strip()]
            if parsed.get("confidence") is None and names[0].get("confidence") is not None:
                confidence_value = names[0].get("confidence", 0.0)
            names = derived_names

        confidence = float(confidence_value or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        return [str(name) for name in names], role, confidence

    def _analyze_with_retries(self, company: CompanyData) -> Any:
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                return self._post_chat(
                    model=self.selected_model or self.model,
                    messages=[
                        {"role": "system", "content": self._system_prompt()},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "cnpj": company.formatted_cnpj,
                                    "legal_name": company.legal_name,
                                    "trade_name": company.trade_name,
                                    "legal_nature": company.legal_nature,
                                    "qsa_text": company.qsa_text,
                                    "responsible_qualification": company.responsible_qualification,
                                    "candidates": [candidate.to_dict() for candidate in company.candidates],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    timeout_seconds=self.timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise ValueError("LLM analysis failed")

    def analyze_company(self, company: CompanyData) -> ResponsibleResult:
        if self.disabled_error:
            raise ValueError(self.disabled_error)
        if not self.api_key:
            raise ValueError("LLM_API_KEY is missing")
        if not self.selected_model:
            # Probe for a usable model once, under a lock. A reasoning model is
            # slow to answer even a ping, so several worker threads probing at
            # once would pile onto the endpoint and blow past a short timeout —
            # and the first such failure then disabled the LLM for the whole
            # run. One serialized probe with the full timeout avoids both traps.
            with self._model_lock:
                if self.disabled_error:
                    raise ValueError(self.disabled_error)
                if not self.selected_model and not self.preflight(
                    chat_timeout_seconds=self.timeout_seconds
                ):
                    raise ValueError(self.disabled_error or "No working LLM model is available")

        response = self._analyze_with_retries(company)
        if response.status_code >= 400:
            raise ValueError(f"LLM request failed with HTTP {response.status_code}: {response.text[:300]}")

        payload = response.json()
        content = (
            payload.get("choices", [{}])[0].get("message", {}).get("content")
            or payload.get("choices", [{}])[0].get("text")
            or ""
        )
        names, role, confidence = self._parse_result(content)
        return ResponsibleResult(
            names=names,
            role=role,
            confidence=confidence,
            reasoning="",
            analysis_source=self.selected_analysis_source(),
            model_used=self.selected_model or self.model,
            candidates=company.candidates,
        )
