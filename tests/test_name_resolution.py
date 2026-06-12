from cnpj_tool.analysis import CompanyAnalyzer
from cnpj_tool.importer import NameQuery
from cnpj_tool.models import Candidate, CompanyData
from cnpj_tool.name_search import CompanySearchResult


def _aerotrafic_results() -> list[CompanySearchResult]:
    raw = [
        ("06207059000301", "Aerotrafic Transportes Logistica e Armazens Gerais - Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
        ("10492303000122", "Aerotrafic Transportes e Logistica LTDA - Aeropan Transportes e Logistica Ltda.", "ATIVA"),
        ("06207059000484", "Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
        ("06207059000131", "Aerotrafic Transportes Logistica e Armazens Gerais - Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
    ]
    return [CompanySearchResult(cnpj=c, formatted_cnpj="", name=n, status=s) for c, n, s in raw]


def test_analyze_one_by_name_resolves_then_extracts_responsible():
    captured: dict = {}

    def fake_search(name: str) -> list[CompanySearchResult]:
        captured["name"] = name
        return _aerotrafic_results()

    def fake_fetch(cnpj: str) -> CompanyData:
        captured["cnpj"] = cnpj
        return CompanyData(
            cnpj=cnpj,
            formatted_cnpj="",
            url="",
            legal_name="Aerotrafic Transportes e Logistica LTDA",
            candidates=[
                Candidate(name="Carlos Filho", role="Sócio"),
                Candidate(name="Douglas do Vale Santiago", role="Administrador"),
            ],
        )

    analyzer = CompanyAnalyzer(fetch_company=fake_fetch, search_companies=fake_search, request_delay_seconds=0)
    query = NameQuery(
        company_name="Aerotrafic Transportes e Logística",
        website="https://aerotrafic.com.br",
        email="caroline.almeida@aerotrafic.com.br",
        responsible_hint="Douglas do Vale Santiago",
        row_number=3,
    )

    result = analyzer.analyze_one_by_name(query)

    assert captured["name"] == "Aerotrafic Transportes e Logística"
    assert captured["cnpj"] == "06207059000131"  # normalized to matriz, fetched via existing pipeline
    assert result.status == "success"
    assert result.responsible.names == ["Douglas do Vale Santiago"]  # highest-ranked role
    assert result.name_meta["matched_cnpj"] == "06207059000131"
    assert result.name_meta["candidate_count"] == 4
    assert result.name_meta["responsible_hint"] == "Douglas do Vale Santiago"
    assert result.name_meta["row_number"] == 3


def test_analyze_one_by_name_reports_not_found_without_fetch():
    def fake_fetch(cnpj: str) -> CompanyData:  # pragma: no cover - must not be called
        raise AssertionError("fetch_company should not run when there is no match")

    analyzer = CompanyAnalyzer(fetch_company=fake_fetch, search_companies=lambda name: [], request_delay_seconds=0)
    result = analyzer.analyze_one_by_name(NameQuery(company_name="Empresa Totalmente Inexistente XYZ"))

    assert result.status == "not_found"
    assert result.company is None
    assert result.name_meta["candidate_count"] == 0


def test_analyze_many_by_name_preserves_order_and_status():
    def fake_search(name: str) -> list[CompanySearchResult]:
        if "aero" in name.casefold():
            return [CompanySearchResult(cnpj="06207059000131", formatted_cnpj="", name="Aerotrafic Transportes e Logistica LTDA", status="ATIVA")]
        return []

    def fake_fetch(cnpj: str) -> CompanyData:
        return CompanyData(cnpj=cnpj, formatted_cnpj="", url="", candidates=[Candidate(name="Resp", role="Administrador")])

    analyzer = CompanyAnalyzer(fetch_company=fake_fetch, search_companies=fake_search, request_delay_seconds=0)
    out = analyzer.analyze_many_by_name(
        [NameQuery(company_name="Aerotrafic"), NameQuery(company_name="Nada Existe Aqui")]
    )

    assert [r.status for r in out] == ["success", "not_found"]
    assert out[0].name_meta["query_name"] == "Aerotrafic"


def test_analyze_one_by_name_falls_back_to_simpler_query():
    calls: list[str] = []

    def fake_search(name: str) -> list[CompanySearchResult]:
        calls.append(name)
        if name == "Dabasons":  # only the simplified query yields a result
            return [CompanySearchResult(cnpj="11222333000181", formatted_cnpj="", name="Dabasons Imp Exp Com LTDA", status="ATIVA")]
        return []

    def fake_fetch(cnpj: str) -> CompanyData:
        return CompanyData(cnpj=cnpj, formatted_cnpj="", url="", candidates=[Candidate(name="Elia Dabbah", role="Administrador")])

    analyzer = CompanyAnalyzer(fetch_company=fake_fetch, search_companies=fake_search, request_delay_seconds=0)
    result = analyzer.analyze_one_by_name(
        NameQuery(company_name="Dabasons Imp Exp Com Ltda", responsible_hint="Elia Dabbah")
    )

    assert result.status == "success"
    assert result.responsible.names == ["Elia Dabbah"]
    assert result.name_meta["matched_cnpj"] == "11222333000181"
    assert result.name_meta["query_used"] == "Dabasons"
    assert calls[0] == "Dabasons Imp Exp Com Ltda"  # full name tried first
    assert "Dabasons" in calls  # then the simplified fallback
