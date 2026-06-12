from pathlib import Path

from cnpj_tool.name_search import (
    CompanySearchResult,
    build_query_variants,
    parse_search_results,
    pick_best_match,
    search_url,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Accented characters are written as escapes so the source stays pure ASCII and
# cannot be mangled by file-encoding round-trips. "Logistica" with accented i:
AEROTRAFIC_QUERY = "Aerotrafic Transportes e Logistica"  # accent-free; matcher strips accents


def _aerotrafic_results() -> list[CompanySearchResult]:
    # Real cards captured from the Aerotrafic search on cnpj.biz.
    raw = [
        ("06207059000301", "Aerotrafic Transportes Logistica e Armazens Gerais - Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
        ("10492303000122", "Aerotrafic Transportes e Logistica LTDA - Aeropan Transportes e Logistica Ltda.", "ATIVA"),
        ("06207059000484", "Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
        ("06207059000212", "Aerotrafic Transportes e Logistica - Aerotrafic Transportes e Logistica LTDA", "BAIXADA"),
        ("06207059000131", "Aerotrafic Transportes Logistica e Armazens Gerais - Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
        ("06207059000565", "Aerotrafic Transportes e Logistica LTDA", "ATIVA"),
    ]
    return [CompanySearchResult(cnpj=c, formatted_cnpj="", name=n, status=s) for c, n, s in raw]


def test_search_url_encodes_spaces_and_slashes():
    assert search_url("Construtora R.Yazbek LTDA") == "https://cnpj.biz/procura/Construtora%20R.Yazbek%20LTDA"
    assert search_url("Yazbek Clinica Medica S/S") == "https://cnpj.biz/procura/Yazbek%20Clinica%20Medica%20S%2FS"


def test_parse_search_results_reads_real_cards():
    html = (FIXTURES / "cnpjbiz_procura_yazbek.html").read_text(encoding="utf-8")
    results = parse_search_results(html)

    assert len(results) == 13
    first = results[0]
    assert first.cnpj == "05844915000105"
    assert first.formatted_cnpj == "05.844.915/0001-05"
    assert first.name == "Conbek - Construtora Yazbek LTDA"
    assert first.status == "BAIXADA"
    # fixture capture mangled the accented char; verify the field is located, not its accent
    assert first.city.startswith('Tucuru') and first.city.endswith('/PA')
    assert first.opening_date == "1979-11-16"
    assert first.url == "https://cnpj.biz/05844915000105"

    active = next(r for r in results if r.cnpj == "08904258000124")
    assert active.name == "Alberto Jose Kalil Yazbek"
    assert active.status == "ATIVA"
    assert active.city == "Pindamonhangaba/SP"


def test_pick_best_match_single_suspended_result_is_accepted():
    # Real: searching the full name returns exactly one (SUSPENSA) company whose
    # detail page lists the ground-truth responsible "Rita de Cassia Yazbek".
    results = [
        CompanySearchResult(
            cnpj="22779678000157",
            formatted_cnpj="22.779.678/0001-57",
            name="Construtora R.yazbek LTDA Scp3-Hermano Ribeiro",
            status="SUSPENSA",
        )
    ]
    match = pick_best_match(
        results,
        "Construtora R.Yazbek LTDA",
        website="http://www.ryazbek.com.br",
        email="ana@ryazbek.com.br",
    )
    assert match is not None
    assert match.result.cnpj == "22779678000157"
    assert match.candidate_count == 1
    assert match.confidence >= 0.8


def test_pick_best_match_avoids_lookalike_and_prefers_matriz():
    # The Aeropan card (10492303...) shares the fantasia "Aerotrafic..." but is a
    # different company; the matcher must land on the real Aerotrafic group and
    # normalize to its matriz (branch 0001) when present in the results.
    match = pick_best_match(
        _aerotrafic_results(),
        AEROTRAFIC_QUERY,
        website="https://aerotrafic.com.br",
        email="caroline.almeida@aerotrafic.com.br",
    )
    assert match is not None
    assert match.result.cnpj.startswith("06207059")
    assert match.result.cnpj != "10492303000122"
    assert match.result.cnpj == "06207059000131"  # matriz of the real group


def test_pick_best_match_uses_domain_hint_to_break_ties():
    results = [
        CompanySearchResult(cnpj="11111111000191", formatted_cnpj="", name="Tech Solucoes LTDA", status="ATIVA"),
        CompanySearchResult(cnpj="22222222000181", formatted_cnpj="", name="Nexus Tech LTDA", status="ATIVA"),
    ]
    match = pick_best_match(results, "Tech", website="https://nexustech.com")
    assert match is not None
    assert match.result.cnpj == "22222222000181"


def test_pick_best_match_returns_none_when_nothing_relevant():
    assert pick_best_match([], "Whatever LTDA") is None
    unrelated = [CompanySearchResult(cnpj="33333333000100", formatted_cnpj="", name="Padaria do Joao LTDA", status="ATIVA")]
    assert pick_best_match(unrelated, "Companhia Aerospacial Brasileira") is None


def test_build_query_variants_simplifies_progressively():
    assert build_query_variants("") == []
    assert build_query_variants("Transkompa") == ["Transkompa"]

    dabasons = build_query_variants("Dabasons Imp Exp Com Ltda")
    assert dabasons[0] == "Dabasons Imp Exp Com Ltda"
    assert "Dabasons" in dabasons

    caruana = build_query_variants("Caruana S.A. Sociedade de Credito")
    assert caruana[0] == "Caruana S.A. Sociedade de Credito"
    assert "Caruana" in caruana

    gramcell = build_query_variants("Gramcell - Parceiro Vivo")
    assert "Gramcell" in gramcell
    assert "Parceiro Vivo" in gramcell

    assert len(build_query_variants("A B C D E F G H Imp Exp")) <= 4
