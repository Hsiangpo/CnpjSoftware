from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

from .cnpj import dedupe_preserve_order, format_cnpj, normalize_cnpj
from .models import BatchResult, Candidate, CompanyData, ResponsibleResult


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
    ) -> None:
        self.fetch_company = fetch_company
        self.analyze_with_llm = analyze_with_llm
        self.request_delay_seconds = request_delay_seconds
        self.max_concurrency = max(1, max_concurrency)

    def close(self) -> None:
        owner = getattr(self.fetch_company, "__self__", None)
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
