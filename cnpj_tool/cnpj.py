from __future__ import annotations

import re

CNPJ_PATTERN = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def normalize_cnpj(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def format_cnpj(value: str) -> str:
    digits = normalize_cnpj(value)
    if len(digits) != 14:
        raise ValueError("CNPJ must contain 14 digits")
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def validate_cnpj(value: str) -> bool:
    digits = normalize_cnpj(value)
    if len(digits) != 14:
        return False
    if digits == digits[0] * 14:
        return False

    first = _check_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _check_digit(digits[:12] + first, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == first + second


def extract_cnpjs(text: str) -> list[str]:
    found: list[str] = []
    for match in CNPJ_PATTERN.findall(text or ""):
        digits = normalize_cnpj(match)
        if validate_cnpj(digits):
            found.append(digits)
    return found


def dedupe_preserve_order(cnpjs: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for cnpj in cnpjs:
        normalized = normalize_cnpj(cnpj)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique
