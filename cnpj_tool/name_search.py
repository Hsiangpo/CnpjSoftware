from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

from bs4 import BeautifulSoup

from .cnpj import format_cnpj

BASE_URL = "https://cnpj.biz"

# Legal-form / boilerplate tokens that carry no disambiguation value.
_LEGAL_TOKENS = {
    "ltda", "me", "epp", "eireli", "mei", "sa", "cia", "ltd", "inc",
    "scp", "ss", "s", "do", "da", "de", "dos", "das", "e",
}
# Trailing domain labels to peel off when extracting a brand root.
_DOMAIN_SUFFIXES = {
    "com", "br", "net", "org", "gov", "edu", "co", "io", "app",
    "me", "biz", "info", "inc", "ltda", "us", "uk",
}

# Generic business descriptors; when a query's full name finds nothing, the part
# before the first such token is usually the distinctive brand worth re-searching.
_GENERIC_DESCRIPTOR_TOKENS = {
    "imp", "exp", "com", "comercio", "comercial", "importacao", "exportacao",
    "industria", "industrial", "servicos", "servico", "sociedade", "credito",
    "financiamento", "investimento", "distribuidora", "representacoes",
    "participacoes", "empreendimentos", "consultoria", "transportes",
    "logistica", "construcao", "construtora", "materiais",
}


@dataclass
class CompanySearchResult:
    cnpj: str
    formatted_cnpj: str
    name: str
    status: str = ""
    city: str = ""
    opening_date: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "cnpj": self.cnpj,
            "formatted_cnpj": self.formatted_cnpj,
            "name": self.name,
            "status": self.status,
            "city": self.city,
            "opening_date": self.opening_date,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "CompanySearchResult":
        payload = data or {}
        return cls(
            cnpj=str(payload.get("cnpj", "")),
            formatted_cnpj=str(payload.get("formatted_cnpj", "")),
            name=str(payload.get("name", "")),
            status=str(payload.get("status", "")),
            city=str(payload.get("city", "")),
            opening_date=str(payload.get("opening_date", "")),
            url=str(payload.get("url", "")),
        )


@dataclass
class NameMatch:
    result: CompanySearchResult
    confidence: float
    candidate_count: int
    query: str

    def to_dict(self) -> dict:
        return {
            "result": self.result.to_dict(),
            "confidence": self.confidence,
            "candidate_count": self.candidate_count,
            "query": self.query,
        }


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalize(text: str) -> str:
    lowered = _strip_accents(text).casefold()
    return _clean(re.sub(r"[^a-z0-9]+", " ", lowered))


def _name_tokens(text: str) -> list[str]:
    tokens = []
    for token in _normalize(text).split():
        if len(token) < 2 or token in _LEGAL_TOKENS:
            continue
        tokens.append(token)
    return tokens


def _token_scores(query: list[str], candidate: list[str]) -> tuple[float, float]:
    query_set, candidate_set = set(query), set(candidate)
    if not query_set:
        return 0.0, 0.0
    intersection = query_set & candidate_set
    union = query_set | candidate_set
    coverage = len(intersection) / len(query_set)
    jaccard = len(intersection) / len(union) if union else 0.0
    return coverage, jaccard


def _domain_root(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[1]
    else:
        text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
        text = text.split("/", 1)[0]
    text = text.split(":", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    labels = [label for label in text.split(".") if label]
    while len(labels) > 1 and labels[-1] in _DOMAIN_SUFFIXES:
        labels.pop()
    root = labels[-1] if labels else ""
    return root if len(root) >= 3 else ""


def _matriz_sibling(
    chosen: CompanySearchResult, results: list[CompanySearchResult]
) -> CompanySearchResult | None:
    if chosen.cnpj[8:12] == "0001":
        return None
    base = chosen.cnpj[:8]
    for result in results:
        if result.cnpj[:8] == base and result.cnpj[8:12] == "0001":
            return result
    return None


def search_url(name: str, base_url: str = BASE_URL) -> str:
    return f"{base_url}/procura/{quote((name or '').strip(), safe='')}"


def parse_search_results(html: str, base_url: str = BASE_URL) -> list[CompanySearchResult]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[CompanySearchResult] = []
    seen: set[str] = set()
    for li in soup.find_all("li"):
        anchor = li.find("a", href=True)
        if not anchor:
            continue
        match = re.search(r"/(\d{14})(?:[/?#]|$)", anchor.get("href", ""))
        if not match:
            continue
        cnpj = match.group(1)
        if cnpj in seen:
            continue
        seen.add(cnpj)

        name_el = li.find("p", class_="text-lg")
        status_el = li.find("p", class_="rounded-full")
        city = ""
        for paragraph in li.find_all("p"):
            use = paragraph.find("use")
            if use and "location" in (use.get("href", "") or ""):
                city = _clean(paragraph.get_text())
                break
        time_el = li.find("time")
        opening = ""
        if time_el is not None:
            opening = time_el.get("datetime", "") or _clean(time_el.get_text())

        results.append(
            CompanySearchResult(
                cnpj=cnpj,
                formatted_cnpj=format_cnpj(cnpj),
                name=_clean(name_el.get_text()) if name_el else "",
                status=_clean(status_el.get_text()) if status_el else "",
                city=city,
                opening_date=opening,
                url=f"{base_url}/{cnpj}",
            )
        )
    return results


def pick_best_match(
    results: list[CompanySearchResult],
    company_name: str,
    website: str = "",
    email: str = "",
    min_confidence: float = 0.45,
) -> NameMatch | None:
    if not results:
        return None
    query_tokens = _name_tokens(company_name)
    if not query_tokens:
        return None

    domain = _domain_root(website) or _domain_root(email)

    best: tuple[float, float, float, float, bool, CompanySearchResult] | None = None
    for result in results:
        coverage, jaccard = _token_scores(query_tokens, _name_tokens(result.name))
        domain_hit = bool(domain and domain in _normalize(result.name).replace(" ", ""))
        is_matriz = result.cnpj[8:12] == "0001"
        is_active = "ativa" in (result.status or "").casefold()
        score = (
            coverage
            + jaccard
            + (0.5 if domain_hit else 0.0)
            + (0.15 if is_matriz else 0.0)
            + (0.1 if is_active else 0.0)
        )
        confidence = min(1.0, coverage * 0.7 + jaccard * 0.2 + (0.2 if domain_hit else 0.0))
        candidate = (score, coverage, jaccard, confidence, domain_hit, result)
        # Rank on (score, coverage, jaccard); the rest are carried for reporting.
        if best is None or candidate[:3] > best[:3]:
            best = candidate

    score, coverage, jaccard, confidence, domain_hit, chosen = best
    if confidence < min_confidence:
        return None

    sibling = _matriz_sibling(chosen, results)
    if sibling is not None:
        chosen = sibling

    return NameMatch(
        result=chosen,
        confidence=round(confidence, 3),
        candidate_count=len(results),
        query=company_name,
    )


def build_query_variants(name: str) -> list[str]:
    """Ordered search queries to try: the full name first, then progressively
    simpler forms (dash segments, the distinctive lead, the brand word)."""
    raw = (name or "").strip()
    if not raw:
        return []

    variants = [raw]
    for segment in re.split(r"\s*[-–—]\s*", raw):
        segment = segment.strip()
        if segment:
            variants.append(segment)

    words = raw.split()
    lead: list[str] = []
    for word in words:
        token = _normalize(word)
        if not token:
            continue
        if token in _GENERIC_DESCRIPTOR_TOKENS or token in _LEGAL_TOKENS:
            break
        lead.append(word)
    if lead:
        variants.append(" ".join(lead))

    for word in words:
        token = _normalize(word)
        if len(token) >= 3 and token not in _GENERIC_DESCRIPTOR_TOKENS and token not in _LEGAL_TOKENS:
            variants.append(word)
            break

    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        key = _normalize(variant)
        if key and key not in seen:
            seen.add(key)
            ordered.append(variant)
    return ordered[:4]
