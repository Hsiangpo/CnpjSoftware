from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .checkpoints import CheckpointStore
from .importer import UploadDetails, parse_upload_details
from .models import is_business_success


SUPPORTED_SOURCE_SUFFIXES = {".txt", ".csv", ".xlsx"}


@dataclass(frozen=True)
class SourceFileRecord:
    name: str
    path: Path
    source_type: str
    count: int
    unique_count: int
    upload_id: str
    size_bytes: int
    modified_at: float
    resume: dict
    output_name: str
    output_exists: bool
    output_size_bytes: int
    output_modified_at: float
    normal_count: int
    abnormal_count: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source_type": self.source_type,
            "count": self.count,
            "unique_count": self.unique_count,
            "upload_id": self.upload_id,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "resume": self.resume,
            "output_name": self.output_name,
            "output_exists": self.output_exists,
            "output_size_bytes": self.output_size_bytes,
            "output_modified_at": self.output_modified_at,
            "normal_count": self.normal_count,
            "abnormal_count": self.abnormal_count,
        }


def _safe_source_path(root: Path, source_name: str) -> Path:
    candidate = (root / source_name).resolve()
    root_resolved = root.resolve()
    if candidate.parent != root_resolved:
        raise ValueError(f"Unsupported source file: {source_name}")
    if candidate.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
        raise ValueError(f"Unsupported file type: {candidate.suffix}")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(source_name)
    return candidate


def load_source_file(root: Path, source_name: str) -> tuple[Path, bytes, UploadDetails]:
    path = _safe_source_path(root, source_name)
    data = path.read_bytes()
    details = parse_upload_details(path.name, data)
    return path, data, details


def list_source_files(root: Path, checkpoints: CheckpointStore, output_root: Path) -> list[SourceFileRecord]:
    root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    records: list[SourceFileRecord] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        data = path.read_bytes()
        details = parse_upload_details(path.name, data)
        upload_id = checkpoints.build_upload_id(path.name, data, details.cnpjs)
        resume = checkpoints.get_resume_state(upload_id).to_dict()
        results = checkpoints.load_results(upload_id)
        normal_count = sum(1 for result in results if is_business_success(result))
        abnormal_count = max(0, len(results) - normal_count)
        output_name = output_filename_for(path.name, details.source_type)
        output_path = output_root / output_name
        records.append(
            SourceFileRecord(
                name=path.name,
                path=path,
                source_type=details.source_type,
                count=len(details.cnpjs),
                unique_count=len(dict.fromkeys(details.cnpjs)),
                upload_id=upload_id,
                size_bytes=path.stat().st_size,
                modified_at=path.stat().st_mtime,
                resume=resume,
                output_name=output_name,
                output_exists=output_path.exists(),
                output_size_bytes=output_path.stat().st_size if output_path.exists() else 0,
                output_modified_at=output_path.stat().st_mtime if output_path.exists() else 0.0,
                normal_count=normal_count,
                abnormal_count=abnormal_count,
            )
        )
    return records


def list_output_files(root: Path) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(root.iterdir(), key=lambda item: (item.stat().st_mtime, item.name.casefold()), reverse=True):
        if not path.is_file():
            continue
        files.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": path.stat().st_mtime,
            }
        )
    return files


def output_filename_for(source_name: str, source_type: str) -> str:
    stem = Path(source_name).stem
    if source_type == "xlsx":
        return f"{stem}-responsaveis.xlsx"
    suffix = Path(source_name).suffix.lower().lstrip(".") or source_type
    return f"{stem}-{suffix}-responsaveis.csv"
