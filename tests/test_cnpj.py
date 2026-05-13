from cnpj_tool.cnpj import (
    dedupe_preserve_order,
    extract_cnpjs,
    format_cnpj,
    normalize_cnpj,
    validate_cnpj,
)


def test_extracts_valid_cnpjs_and_preserves_duplicates():
    text = """
    03.541.629/0001-37
    35.516.918/0001-72
    35.516.918/0001-72
    invalid 11.111.111/1111-11
    """

    assert extract_cnpjs(text) == [
        "03541629000137",
        "35516918000172",
        "35516918000172",
    ]


def test_formats_and_validates_cnpj():
    assert normalize_cnpj("03.541.629/0001-37") == "03541629000137"
    assert format_cnpj("03541629000137") == "03.541.629/0001-37"
    assert validate_cnpj("03541629000137") is True
    assert validate_cnpj("11111111111111") is False


def test_dedupes_preserving_first_seen_order():
    assert dedupe_preserve_order([
        "03541629000137",
        "35516918000172",
        "03541629000137",
    ]) == ["03541629000137", "35516918000172"]
