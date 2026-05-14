import threading
import time

from cnpj_tool.analysis import CompanyAnalyzer, choose_rule_based_responsible
from cnpj_tool.models import Candidate, CompanyData
from cnpj_tool.models import ResponsibleResult
from cnpj_tool.models import ProviderTraceEntry
from cnpj_tool.providers import ProviderError


def test_rule_based_responsible_prefers_presidente_over_diretor():
    result = choose_rule_based_responsible([
        Candidate(name="Edson Eduardo Fernandes", role="Diretor"),
        Candidate(name="Pasqual Marco Antonio Micali", role="Presidente"),
    ])

    assert result.names == ["Pasqual Marco Antonio Micali"]
    assert result.role == "Presidente"
    assert result.analysis_source == "rule_fallback"


def test_rule_based_responsible_keeps_same_level_ties():
    result = choose_rule_based_responsible([
        Candidate(name="Carlos Marques Moreira", role="Sócio-Administrador"),
        Candidate(name="Poliana Aparecida Moreira", role="Sócio-Administrador"),
        Candidate(name="Outro Socio", role="Sócio"),
    ])

    assert result.names == ["Carlos Marques Moreira", "Poliana Aparecida Moreira"]
    assert result.role == "Sócio-Administrador"
    assert result.confidence == 0.72


def test_analyze_many_accepts_formatted_cnpj_inputs():
    analyzer = CompanyAnalyzer(
        fetch_company=lambda cnpj: CompanyData(
            cnpj=cnpj,
            formatted_cnpj="03.541.629/0001-37",
            url="https://cnpj.biz/03541629000137",
            legal_name="ORGANIZACOES MARQUES CENTER LTDA",
            candidates=[Candidate(name="Carlos", role="Sócio-Administrador")],
        ),
        analyze_with_llm=None,
        request_delay_seconds=0,
    )

    results = analyzer.analyze_many(["03.541.629/0001-37", "03.541.629/0001-37"])

    assert len(results) == 2
    assert all(result.normalized_cnpj == "03541629000137" for result in results)


def test_analyze_many_uses_unified_concurrency_for_fetch_and_llm():
    active = 0
    max_active = 0
    lock = threading.Lock()

    def track_work():
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1

    def fetch_company(cnpj: str) -> CompanyData:
        track_work()
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj=f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}",
            url=f"https://cnpj.biz/{cnpj}",
            legal_name=f"Company {cnpj}",
            candidates=[Candidate(name=f"Pessoa {cnpj}", role="Sócio-Administrador")],
        )

    def analyze_with_llm(company: CompanyData) -> ResponsibleResult:
        track_work()
        return ResponsibleResult(
            names=[company.candidates[0].name],
            role="Sócio-Administrador",
            confidence=0.9,
            reasoning="ok",
            analysis_source="llm",
            model_used="gpt-5.4-mini",
        )

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=analyze_with_llm,
        request_delay_seconds=0,
        max_concurrency=2,
    )

    results = analyzer.analyze_many([
        "03.541.629/0001-37",
        "21.746.991/0001-26",
        "02.759.853/0001-37",
        "00.642.475/0001-81",
    ])

    assert len(results) == 4
    assert all(result.status == "success" for result in results)
    assert 1 < max_active <= 2


def test_analyze_one_counts_rule_fallback_with_name_as_success_after_llm_failure():
    def fetch_company(cnpj: str) -> CompanyData:
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj="03.541.629/0001-37",
            url=f"https://cnpj.biz/{cnpj}",
            legal_name="Empresa Teste",
            candidates=[Candidate(name="Maria Fallback", role="Socio-Administrador")],
        )

    def fail_llm(_company: CompanyData) -> ResponsibleResult:
        raise ValueError("LLM request failed with HTTP 403")

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=fail_llm,
        request_delay_seconds=0,
    )

    result = analyzer.analyze_one("03.541.629/0001-37")

    assert result.status == "success"
    assert result.error == "LLM request failed with HTTP 403"
    assert result.responsible
    assert result.responsible.analysis_source == "rule_fallback"
    assert result.responsible.names == ["Maria Fallback"]


def test_analyze_one_keeps_partial_success_when_rule_fallback_has_no_name_after_llm_failure():
    def fetch_company(cnpj: str) -> CompanyData:
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj="03.541.629/0001-37",
            url=f"https://cnpj.biz/{cnpj}",
            legal_name="Empresa Teste",
            candidates=[],
        )

    def fail_llm(_company: CompanyData) -> ResponsibleResult:
        raise ValueError("LLM request failed with HTTP 403")

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=fail_llm,
        request_delay_seconds=0,
    )

    result = analyzer.analyze_one("03.541.629/0001-37")

    assert result.status == "partial_success"
    assert result.responsible
    assert result.responsible.names == []


def test_analyze_many_stops_without_starting_remaining_work():
    processed = []

    def fetch_company(cnpj: str) -> CompanyData:
        processed.append(cnpj)
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj=cnpj,
            url=f"https://cnpj.biz/{cnpj}",
            legal_name=f"Company {cnpj}",
            candidates=[Candidate(name=f"Pessoa {cnpj}", role="Sócio-Administrador")],
        )

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=None,
        request_delay_seconds=0,
        max_concurrency=1,
    )

    stop_after_first = {"value": False}

    def on_result(_result):
        stop_after_first["value"] = True

    results = analyzer.analyze_many(
        [
            "03.541.629/0001-37",
            "21.746.991/0001-26",
            "02.759.853/0001-37",
        ],
        on_result=on_result,
        should_stop=lambda: stop_after_first["value"],
    )

    assert len(results) == 1
    assert processed == ["03541629000137"]


def test_analyze_many_concurrent_stop_returns_without_waiting_for_other_inflight_work():
    started = []

    def fetch_company(cnpj: str) -> CompanyData:
        started.append(cnpj)
        if cnpj == "21746991000126":
            time.sleep(1.0)
        else:
            time.sleep(0.05)
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj=cnpj,
            url=f"https://cnpj.biz/{cnpj}",
            legal_name=f"Company {cnpj}",
            candidates=[Candidate(name=f"Pessoa {cnpj}", role="Sócio-Administrador")],
        )

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=None,
        request_delay_seconds=0,
        max_concurrency=2,
    )

    stop_after_first = {"value": False}

    def on_result(_result):
        stop_after_first["value"] = True

    started_at = time.perf_counter()
    results = analyzer.analyze_many(
        [
            "03.541.629/0001-37",
            "21.746.991/0001-26",
            "02.759.853/0001-37",
        ],
        on_result=on_result,
        should_stop=lambda: stop_after_first["value"],
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.6
    assert len(results) == 1
    assert started[:2] == ["03541629000137", "21746991000126"]


def test_analyze_one_persists_provider_trace_on_fetch_failure():
    def fetch_company(_cnpj: str) -> CompanyData:
        exc = ProviderError("cnpj.biz returned HTTP 403")
        exc.status = "blocked_by_cloudflare"
        exc.provider_trace = [
            ProviderTraceEntry(provider="brasilapi", status="fetch_error", error="BrasilAPI failed with HTTP 429"),
            ProviderTraceEntry(provider="cnpjbiz", status="blocked_by_cloudflare", error="cnpj.biz returned HTTP 403"),
        ]
        raise exc

    analyzer = CompanyAnalyzer(
        fetch_company=fetch_company,
        analyze_with_llm=None,
        request_delay_seconds=0,
    )

    result = analyzer.analyze_one("03.541.629/0001-37")

    assert result.status == "blocked_by_cloudflare"
    assert [item.provider for item in result.provider_trace] == ["brasilapi", "cnpjbiz"]
    assert result.to_dict()["provider_trace"][1]["status"] == "blocked_by_cloudflare"
