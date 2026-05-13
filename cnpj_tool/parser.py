from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from .cnpj import format_cnpj, normalize_cnpj
from .models import Branch, Candidate, CompanyData


REGISTRATION_LABELS = [
    "CNPJ:",
    "Inscrição Estadual",
    "Razão Social:",
    "Nome Fantasia:",
    "Data da Abertura:",
    "Porte:",
    "Natureza Jurídica:",
    "Opção pelo MEI:",
    "Opção pelo Simples:",
    "Data Opção",
    "Capital Social:",
    "Tipo:",
    "Situação:",
    "Data Situação Cadastral:",
]

LOCATION_LABELS = [
    "Logradouro:",
    "Bairro:",
    "CEP:",
    "Município:",
    "Estado:",
    "Para correspondência:",
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _find_h2(soup: BeautifulSoup, title: str) -> Tag | None:
    target = title.casefold()
    for heading in soup.find_all("h2"):
        if _clean(heading.get_text()).casefold() == target:
            return heading
    return None


def _section_nodes(soup: BeautifulSoup, title: str) -> list[Tag | NavigableString]:
    heading = _find_h2(soup, title)
    if not heading:
        return []

    nodes: list[Tag | NavigableString] = []
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.name == "h2":
            break
        nodes.append(sibling)
    return nodes


def _section_text(soup: BeautifulSoup, title: str, separator: str = " ") -> str:
    parts: list[str] = []
    for node in _section_nodes(soup, title):
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag):
            if node.name == "br":
                parts.append("\n")
            else:
                parts.append(node.get_text(separator, strip=True))
    if separator == "\n":
        return "\n".join(part.strip() for part in parts if part.strip())
    return _clean(" ".join(parts))


def _extract_between(text: str, label: str, labels: list[str]) -> str:
    start = text.find(label)
    if start < 0:
        return ""

    value_start = start + len(label)
    value_end = len(text)
    for stop in labels:
        if stop == label:
            continue
        index = text.find(stop, value_start)
        if index >= 0 and index < value_end:
            value_end = index
    return _clean(text[value_start:value_end])


def _extract_cnpj(text: str) -> str:
    match = re.search(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", text or "")
    return normalize_cnpj(match.group(0)) if match else ""


def _split_secondary_cnaes(section: str) -> list[str]:
    secondary = _extract_between(section, "Secundária(s):", ["Quadro de Sócios", "Sobre"])
    if not secondary:
        return []
    chunks = re.split(r"(?=\d{2}\.\d{2}-\d-\d{2}\s+-)", secondary)
    return [_clean(chunk.replace("⇩", "")) for chunk in chunks if _clean(chunk)]


def _parse_candidate_line(line: str) -> list[Candidate]:
    line = _clean(line)
    if not line or line.startswith("Qualificação do responsável"):
        return []

    candidates: list[Candidate] = []
    represented = re.search(r"Representado por\s+(.+?)\s+-\s+(.+)$", line)
    company_partner = re.match(r"^(.+?)\s+-\s+CNPJ:\s*(\d{14})\s+-\s+(.+?)(?:\s+Representado por|$)", line)
    if company_partner:
        candidates.append(
            Candidate(
                name=_clean(company_partner.group(1)),
                cnpj=company_partner.group(2),
                role=_clean(company_partner.group(3)),
                source_line=line,
            )
        )
    if represented:
        candidates.append(
            Candidate(
                name=_clean(represented.group(1)),
                role=_clean(represented.group(2)),
                source_line=line,
                represented_by=company_partner.group(1) if company_partner else "",
            )
        )
        return candidates

    if " - " not in line:
        return []
    name, role = line.rsplit(" - ", 1)
    return [Candidate(name=_clean(name), role=_clean(role), source_line=line)]


def _parse_candidates(qsa_text: str) -> tuple[list[Candidate], str]:
    candidates: list[Candidate] = []
    qualification = ""
    for raw_line in qsa_text.splitlines():
        line = _clean(raw_line)
        if not line:
            continue
        if line.startswith("Qualificação do responsável pela empresa:"):
            qualification = _clean(line.split(":", 1)[1])
            continue
        candidates.extend(_parse_candidate_line(line))
    return candidates, qualification


def _parse_branches(soup: BeautifulSoup, page_url: str) -> tuple[int, list[Branch]]:
    section = _section_text(soup, "Filiais")
    count_match = re.search(r"Total de\s+(\d+)\s+filia", section, flags=re.IGNORECASE)
    branch_count = int(count_match.group(1)) if count_match else 0
    branches: list[Branch] = []

    for node in _section_nodes(soup, "Filiais"):
        if not isinstance(node, Tag):
            continue
        links = [node] if node.name == "a" else []
        links.extend(node.find_all("a"))
        for link in links:
            text = _clean(link.get_text(" ", strip=True))
            cnpj = _extract_cnpj(text)
            if not cnpj:
                continue
            branches.append(
                Branch(
                    name=_clean(text.replace(format_cnpj(cnpj), "").replace("-", " ")),
                    cnpj=cnpj,
                    url=urljoin(page_url, link.get("href", "")),
                    location=_clean(node.get_text(" ", strip=True)),
                )
            )
    return branch_count, branches


def parse_company_page(html: str, page_url: str) -> CompanyData:
    soup = BeautifulSoup(html, "html.parser")
    registration = _section_text(soup, "Informações de Registro")
    location = _section_text(soup, "Localização")
    contacts = _section_text(soup, "Contatos")
    cnaes = _section_text(soup, "Atividades - CNAES")
    qsa_text = _section_text(soup, "Quadro de Sócios e Administradores", separator="\n")
    about = _section_text(soup, "Sobre")
    cnpj = _extract_cnpj(registration) or _extract_cnpj(page_url)
    candidates, responsible_qualification = _parse_candidates(qsa_text)
    branch_count, branches = _parse_branches(soup, page_url)
    email_match = re.search(r"[\w.*+-]+@[\w.*-]+\.[A-Za-z.*]{2,}", contacts)
    phone_matches = re.findall(r"\(\d{2}\)\s*[\d*]{3,5}\*+-\*+", contacts)

    primary_cnae = _extract_between(cnaes, "Principal:", ["Esta atividade compreende:", "Secundária(s):"])
    primary_cnae = _clean(primary_cnae.replace("⇩", ""))

    return CompanyData(
        cnpj=cnpj,
        formatted_cnpj=format_cnpj(cnpj) if cnpj else "",
        url=page_url,
        page_title=_clean(soup.title.get_text()) if soup.title else "",
        heading=_clean(soup.find("h1").get_text(" ", strip=True)) if soup.find("h1") else "",
        legal_name=_extract_between(registration, "Razão Social:", REGISTRATION_LABELS),
        trade_name=_extract_between(registration, "Nome Fantasia:", REGISTRATION_LABELS),
        opening_date=_extract_between(registration, "Data da Abertura:", REGISTRATION_LABELS),
        size=_extract_between(registration, "Porte:", REGISTRATION_LABELS),
        legal_nature=_extract_between(registration, "Natureza Jurídica:", REGISTRATION_LABELS),
        mei_option=_extract_between(registration, "Opção pelo MEI:", REGISTRATION_LABELS),
        simples_option=_extract_between(registration, "Opção pelo Simples:", REGISTRATION_LABELS),
        capital=_extract_between(registration, "Capital Social:", REGISTRATION_LABELS),
        company_type=_extract_between(registration, "Tipo:", REGISTRATION_LABELS),
        status=_extract_between(registration, "Situação:", REGISTRATION_LABELS),
        status_date=_extract_between(registration, "Data Situação Cadastral:", REGISTRATION_LABELS),
        email=email_match.group(0) if email_match else "",
        phones=phone_matches,
        street=_extract_between(location, "Logradouro:", LOCATION_LABELS),
        district=_extract_between(location, "Bairro:", LOCATION_LABELS),
        zip_code=_extract_between(location, "CEP:", LOCATION_LABELS),
        city=_extract_between(location, "Município:", LOCATION_LABELS),
        state=_extract_between(location, "Estado:", LOCATION_LABELS),
        primary_cnae=primary_cnae,
        secondary_cnaes=_split_secondary_cnaes(cnaes),
        qsa_text=_clean(qsa_text),
        responsible_qualification=responsible_qualification,
        candidates=candidates,
        about=about,
        branch_count=branch_count,
        branches=branches,
    )
