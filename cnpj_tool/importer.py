from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from .cnpj import extract_cnpjs


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


@dataclass
class UploadDetails:
    filename: str
    cnpjs: list[str]
    row_refs: list[dict] = field(default_factory=list)
    source_type: str = ""


def parse_upload(filename: str, data: bytes) -> list[str]:
    return parse_upload_details(filename, data).cnpjs


def parse_upload_details(filename: str, data: bytes) -> UploadDetails:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".csv"}:
        cnpjs = extract_cnpjs(_decode(data))
        return UploadDetails(filename=filename, cnpjs=cnpjs, source_type=suffix.lstrip("."))
    if suffix == ".xlsx":
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        cnpjs: list[str] = []
        row_refs: list[dict] = []
        for sheet in workbook.worksheets:
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = ["" if value is None else str(value) for value in row]
                row_cnpjs = extract_cnpjs("\n".join(values))
                cnpjs.extend(row_cnpjs)
                if row_cnpjs:
                    row_refs.append(
                        {
                            "sheet_name": sheet.title,
                            "row_number": row_number,
                            "cnpjs": row_cnpjs,
                        }
                    )
        workbook.close()
        return UploadDetails(
            filename=filename,
            cnpjs=cnpjs,
            row_refs=row_refs,
            source_type="xlsx",
        )
    raise ValueError("Unsupported file type. Use .txt, .csv, or .xlsx.")
