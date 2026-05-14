from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Candidate:
    name: str
    role: str
    source_line: str = ""
    cnpj: str = ""
    represented_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Candidate":
        payload = data or {}
        return cls(
            name=str(payload.get("name", "")),
            role=str(payload.get("role", "")),
            source_line=str(payload.get("source_line", "")),
            cnpj=str(payload.get("cnpj", "")),
            represented_by=str(payload.get("represented_by", "")),
        )


@dataclass
class Branch:
    name: str
    cnpj: str
    url: str
    location: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Branch":
        payload = data or {}
        return cls(
            name=str(payload.get("name", "")),
            cnpj=str(payload.get("cnpj", "")),
            url=str(payload.get("url", "")),
            location=str(payload.get("location", "")),
        )


@dataclass
class ProviderTraceEntry:
    provider: str
    status: str
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProviderTraceEntry":
        payload = data or {}
        return cls(
            provider=str(payload.get("provider", "")),
            status=str(payload.get("status", "")),
            error=str(payload.get("error", "")),
        )


@dataclass
class CompanyData:
    cnpj: str
    formatted_cnpj: str
    url: str
    page_title: str = ""
    heading: str = ""
    legal_name: str = ""
    trade_name: str = ""
    opening_date: str = ""
    size: str = ""
    legal_nature: str = ""
    mei_option: str = ""
    simples_option: str = ""
    capital: str = ""
    company_type: str = ""
    status: str = ""
    status_date: str = ""
    email: str = ""
    phones: list[str] = field(default_factory=list)
    street: str = ""
    district: str = ""
    zip_code: str = ""
    city: str = ""
    state: str = ""
    primary_cnae: str = ""
    secondary_cnaes: list[str] = field(default_factory=list)
    qsa_text: str = ""
    responsible_qualification: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    about: str = ""
    branch_count: int = 0
    branches: list[Branch] = field(default_factory=list)
    source_provider: str = ""
    source_proxy_port: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        data["branches"] = [branch.to_dict() for branch in self.branches]
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> "CompanyData":
        payload = data or {}
        return cls(
            cnpj=str(payload.get("cnpj", "")),
            formatted_cnpj=str(payload.get("formatted_cnpj", "")),
            url=str(payload.get("url", "")),
            page_title=str(payload.get("page_title", "")),
            heading=str(payload.get("heading", "")),
            legal_name=str(payload.get("legal_name", "")),
            trade_name=str(payload.get("trade_name", "")),
            opening_date=str(payload.get("opening_date", "")),
            size=str(payload.get("size", "")),
            legal_nature=str(payload.get("legal_nature", "")),
            mei_option=str(payload.get("mei_option", "")),
            simples_option=str(payload.get("simples_option", "")),
            capital=str(payload.get("capital", "")),
            company_type=str(payload.get("company_type", "")),
            status=str(payload.get("status", "")),
            status_date=str(payload.get("status_date", "")),
            email=str(payload.get("email", "")),
            phones=[str(item) for item in payload.get("phones", [])],
            street=str(payload.get("street", "")),
            district=str(payload.get("district", "")),
            zip_code=str(payload.get("zip_code", "")),
            city=str(payload.get("city", "")),
            state=str(payload.get("state", "")),
            primary_cnae=str(payload.get("primary_cnae", "")),
            secondary_cnaes=[str(item) for item in payload.get("secondary_cnaes", [])],
            qsa_text=str(payload.get("qsa_text", "")),
            responsible_qualification=str(payload.get("responsible_qualification", "")),
            candidates=[Candidate.from_dict(item) for item in payload.get("candidates", [])],
            about=str(payload.get("about", "")),
            branch_count=int(payload.get("branch_count", 0) or 0),
            branches=[Branch.from_dict(item) for item in payload.get("branches", [])],
            source_provider=str(payload.get("source_provider", "")),
            source_proxy_port=int(payload.get("source_proxy_port", 0) or 0),
        )


@dataclass
class ResponsibleResult:
    names: list[str]
    role: str
    confidence: float
    reasoning: str
    analysis_source: str
    model_used: str = ""
    candidates: list[Candidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> "ResponsibleResult":
        payload = data or {}
        return cls(
            names=[str(item) for item in payload.get("names", [])],
            role=str(payload.get("role", "")),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            reasoning=str(payload.get("reasoning", "")),
            analysis_source=str(payload.get("analysis_source", "")),
            model_used=str(payload.get("model_used", "")),
            candidates=[Candidate.from_dict(item) for item in payload.get("candidates", [])],
        )


@dataclass
class BatchResult:
    input_cnpj: str
    normalized_cnpj: str
    status: str
    company: CompanyData | None = None
    responsible: ResponsibleResult | None = None
    error: str = ""
    provider_trace: list[ProviderTraceEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "input_cnpj": self.input_cnpj,
            "normalized_cnpj": self.normalized_cnpj,
            "status": self.status,
            "company": self.company.to_dict() if self.company else None,
            "responsible": self.responsible.to_dict() if self.responsible else None,
            "error": self.error,
            "provider_trace": [entry.to_dict() for entry in self.provider_trace],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "BatchResult":
        payload = data or {}
        return cls(
            input_cnpj=str(payload.get("input_cnpj", "")),
            normalized_cnpj=str(payload.get("normalized_cnpj", "")),
            status=str(payload.get("status", "")),
            company=CompanyData.from_dict(payload.get("company")) if payload.get("company") else None,
            responsible=ResponsibleResult.from_dict(payload.get("responsible")) if payload.get("responsible") else None,
            error=str(payload.get("error", "")),
            provider_trace=[ProviderTraceEntry.from_dict(item) for item in payload.get("provider_trace", [])],
        )


def has_responsible_name(result: BatchResult) -> bool:
    responsible = result.responsible
    if responsible is None:
        return False
    return any(str(name or "").strip() for name in responsible.names)


def is_business_success(result: BatchResult) -> bool:
    if result.status == "success":
        return True
    if result.status != "partial_success":
        return False
    responsible = result.responsible
    return bool(
        responsible
        and responsible.analysis_source == "rule_fallback"
        and has_responsible_name(result)
    )
