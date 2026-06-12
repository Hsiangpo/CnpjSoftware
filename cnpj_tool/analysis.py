from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

from .cnpj import dedupe_preserve_order, format_cnpj, normalize_cnpj
from .models import BatchResult, Candidate, CompanyData, ResponsibleResult
from .name_search import CompanySearchResult, build_query_variants, pick_best_match


ROLE_RANKS = [
    ("presidente", 100),
    ("diretor presidente", 98),
    ("diretor", 90),
    ("administrador judicial", 85),
    ("administrador", 80),
    ("sócio-administrador", 70),
    ("socio-administrador", 70),
    ("sócio administrador", 70),
    ("socio administrador", 70),
    ("sócio", 50),
    ("socio", 50),
]


def _rank_role(role: str) -> int:
    normalized = (role or "").casefold()
    for marker, rank in ROLE_RANKS:
        if marker in normalized:
            return rank
    return 10


def choose_rule_based_responsible(candidates: list[Candidate]) -> ResponsibleResult:
    if not candidates:
        return ResponsibleResult(
            names=[],
            role="",
            confidence=0.0,
            reasoning="Nenhum candidato foi encontrado no Quadro de Sócios e Administradores.",
            analysis_source="rule_fallback",
            candidates=[],
        )

    best_rank = max(_rank_role(candidate.role) for candidate in candidates)
    best = [candidate for candidate in candidates if _rank_role(candidate.role) == best_rank]
    confidence = 0.72 if len(best) > 1 else 0.84
    role = best[0].role
    if best_rank >= 90:
        confidence = 0.9 if len(best) == 1 else 0.78

    return ResponsibleResult(
        names=[candidate.name for candidate in best],
        role=role,
        confidence=confidence,
        reasoning="Resultado gerado pela hierarquia de cargos extraída do QSA quando a análise por IA não está disponível.",
        analysis_source="rule_fallback",
        candidates=best,
    )


class CompanyAnalyzer:
    def __init__(
        self,
        fetch_company: Callable[[str], CompanyData],
        analyze_with_llm: Callable[[CompanyData], ResponsibleResult] | None = None,
        request_delay_seconds: float = 0.8,
        max_concurrency: int = 1,
        search_companies: Callable[[str], list[CompanySearchResult]] | None = None,
    ) -> None:
        self.fetch_company = fetch_company
        self.analyze_with_llm = analyze_with_llm
        self.request_delay_seconds = request_delay_seconds
        self.max_concurrency = max(1, max_concurrency)
        self.search_companies = search_companies

    def close(self) -> None:
        for candidate in (self.fetch_company, self.search_companies):
            owner = getattr(candidate, "__self__", None)
            close = getattr(owner, "close", None) if owner is not None else None
            if callable(close):
                close()

    def analyze_one(self, cnpj: str) -> BatchResult:
        try:
            company = self.fetch_company(cnpj)
        except Exception as exc:
            return BatchResult(
                input_cnpj=format_cnpj(cnpj),
                normalized_cnpj=cnpj,
                status=getattr(exc, "status", "fetch_error"),
                error=str(exc),
                provider_trace=list(getattr(exc, "provider_trace", []) or []),
            )
        if self.analyze_with_llm:
            try:
                responsible = self.analyze_with_llm(company)
                return BatchResult(
                    input_cnpj=format_cnpj(cnpj),
                    normalized_cnpj=cnpj,
                    status="success",
                    company=company,
                    responsible=responsible,
                )
            except Exception as exc:
                fallback = choose_rule_based_responsible(company.candidates)
                fallback.reasoning = f"LLM falhou ({exc}); foi usada a hierarquia local de cargos."
                status = "success" if any(name.strip() for name in fallback.names) else "partial_success"
                return BatchResult(
                    input_cnpj=format_cnpj(cnpj),
                    normalized_cnpj=cnpj,
                    status=status,
                    company=company,
                    responsible=fallback,
                    error=str(exc),
                )

        return BatchResult(
            input_cnpj=format_cnpj(cnpj),
            normalized_cnpj=cnpj,
            status="success",
            company=company,
            responsible=choose_rule_based_responsible(company.candidates),
        )

    def analyze_many(
        self,
        cnpjs: list[str],
        existing_results: list[BatchResult] | None = None,
        on_result: Callable[[BatchResult], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[BatchResult]:
        normalized_inputs = [normalize_cnpj(cnpj) for cnpj in cnpjs]
        unique = dedupe_preserve_order(normalized_inputs)
        cache: dict[str, BatchResult] = {
            result.normalized_cnpj: result
            for result in (existing_results or [])
            if result.normalized_cnpj
        }
        pending = [cnpj for cnpj in unique if cnpj not in cache]

        if self.max_concurrency == 1:
            for index, cnpj in enumerate(pending):
                if should_stop and should_stop():
                    break
                cache[cnpj] = self.analyze_one(cnpj)
                if on_result:
                    on_result(cache[cnpj])
                if index < len(pending) - 1 and self.request_delay_seconds > 0:
                    time.sleep(self.request_delay_seconds)
            return [cache[cnpj] for cnpj in normalized_inputs if cnpj in cache]

        executor = ThreadPoolExecutor(max_workers=self.max_concurrency)
        stopped_early = False
        try:
            next_index = 0
            futures = {}

            def submit_next() -> None:
                nonlocal next_index
                if should_stop and should_stop():
                    return
                if next_index >= len(pending):
                    return
                cnpj = pending[next_index]
                next_index += 1
                futures[executor.submit(self.analyze_one, cnpj)] = cnpj

            for _ in range(min(self.max_concurrency, len(pending))):
                submit_next()

            while futures:
                if should_stop and should_stop():
                    stopped_early = True
                    for future in futures:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return [cache[cnpj] for cnpj in normalized_inputs if cnpj in cache]
                try:
                    future = next(as_completed(tuple(futures), timeout=0.1))
                except TimeoutError:
                    continue
                cnpj = futures.pop(future)
                cache[cnpj] = future.result()
                if on_result:
                    on_result(cache[cnpj])
                submit_next()
        finally:
            if not stopped_early:
                executor.shutdown(wait=True, cancel_futures=False)
        return [cache[cnpj] for cnpj in normalized_inputs if cnpj in cache]

    def analyze_one_by_name(self, query) -> BatchResult:
        name = str(getattr(query, "company_name", "") or "").strip()
        meta = {
            "query_name": name,
            "website": str(getattr(query, "website", "") or ""),
            "email": str(getattr(query, "email", "") or ""),
            "responsible_hint": str(getattr(query, "responsible_hint", "") or ""),
            "row_number": int(getattr(query, "row_number", 0) or 0),
            "sheet_name": str(getattr(query, "sheet_name", "") or ""),
            "matched_company_name": "",
            "matched_cnpj": "",
            "confidence": 0.0,
            "candidate_count": 0,
            "query_used": "",
        }
        if not name:
            return BatchResult(
                input_cnpj="", normalized_cnpj="", status="not_found",
                error="Nome da empresa ausente", name_meta=meta,
            )
        if self.search_companies is None:
            return BatchResult(
                input_cnpj="", normalized_cnpj="", status="fetch_error",
                error="Busca por nome indisponível", name_meta=meta,
            )

        candidates: list[CompanySearchResult] = []
        match = None
        used_query = name
        last_error: Exception | None = None
        for variant in build_query_variants(name):
            try:
                results = self.search_companies(variant)
            except Exception as exc:
                last_error = exc
                continue
            if results and not candidates:
                candidates = results
            found = pick_best_match(results, name, meta["website"], meta["email"])
            if found is not None:
                candidates = results
                match = found
                used_query = variant
                break

        if match is None:
            if last_error is not None and not candidates:
                return BatchResult(
                    input_cnpj="", normalized_cnpj="",
                    status=getattr(last_error, "status", "fetch_error"), error=str(last_error),
                    provider_trace=list(getattr(last_error, "provider_trace", []) or []),
                    name_meta={**meta, "candidate_count": len(candidates)},
                )
            meta["candidate_count"] = len(candidates)
            return BatchResult(
                input_cnpj="", normalized_cnpj="", status="not_found",
                error="Nenhuma empresa correspondente encontrada" if candidates else "Busca sem resultados",
                name_meta=meta,
            )

        meta["candidate_count"] = len(candidates)
        meta["matched_company_name"] = match.result.name
        meta["matched_cnpj"] = match.result.cnpj
        meta["confidence"] = match.confidence
        meta["query_used"] = used_query
        result = self.analyze_one(match.result.cnpj)
        result.name_meta = meta
        return result

    def analyze_many_by_name(
        self,
        queries: list,
        on_result: Callable[[BatchResult], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[BatchResult]:
        return self._map_concurrent(list(queries), self.analyze_one_by_name, on_result, should_stop)

    def _map_concurrent(
        self,
        items: list,
        worker: Callable[[object], BatchResult],
        on_result: Callable[[BatchResult], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[BatchResult]:
        results: list = [None] * len(items)
        if self.max_concurrency == 1:
            for index, item in enumerate(items):
                if should_stop and should_stop():
                    break
                results[index] = worker(item)
                if on_result:
                    on_result(results[index])
                if index < len(items) - 1 and self.request_delay_seconds > 0:
                    time.sleep(self.request_delay_seconds)
            return [item for item in results if item is not None]

        executor = ThreadPoolExecutor(max_workers=self.max_concurrency)
        stopped_early = False
        try:
            next_index = 0
            futures = {}

            def submit_next() -> None:
                nonlocal next_index
                if should_stop and should_stop():
                    return
                if next_index >= len(items):
                    return
                index = next_index
                next_index += 1
                futures[executor.submit(worker, items[index])] = index

            for _ in range(min(self.max_concurrency, len(items))):
                submit_next()

            while futures:
                if should_stop and should_stop():
                    stopped_early = True
                    for future in futures:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return [item for item in results if item is not None]
                try:
                    future = next(as_completed(tuple(futures), timeout=0.1))
                except TimeoutError:
                    continue
                index = futures.pop(future)
                results[index] = future.result()
                if on_result:
                    on_result(results[index])
                submit_next()
        finally:
            if not stopped_early:
                executor.shutdown(wait=True, cancel_futures=False)
        return [item for item in results if item is not None]
