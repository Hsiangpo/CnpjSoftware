from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .models import BatchResult


@dataclass
class Job:
    job_id: str
    input_cnpjs: list[str]
    upload_id: str = ""
    source_name: str = ""
    filename: str = ""
    output_path: str = ""
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    results: list[BatchResult] = field(default_factory=list)
    error: str = ""
    cancel_requested: bool = False
    mode: str = "cnpj"
    name_queries: list = field(default_factory=list)

    def _name_queries_payload(self) -> list[dict]:
        payload = []
        for query in self.name_queries:
            payload.append(query.to_dict() if hasattr(query, "to_dict") else dict(query))
        return payload

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "input_cnpjs": self.input_cnpjs,
            "upload_id": self.upload_id,
            "source_name": self.source_name,
            "filename": self.filename,
            "output_path": self.output_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "results": [result.to_dict() for result in self.results],
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "mode": self.mode,
            "name_queries": self._name_queries_payload(),
            "total_units": len(self.name_queries) if self.mode == "name" else len(self.input_cnpjs),
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(
        self,
        cnpjs: list[str],
        *,
        upload_id: str = "",
        source_name: str = "",
        filename: str = "",
        output_path: str = "",
        existing_results: list[BatchResult] | None = None,
        mode: str = "cnpj",
        name_queries: list | None = None,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            input_cnpjs=cnpjs,
            upload_id=upload_id,
            source_name=source_name,
            filename=filename,
            output_path=output_path,
            results=list(existing_results or []),
            mode=mode,
            name_queries=list(name_queries or []),
        )
        total_units = len(job.name_queries) if mode == "name" else len(cnpjs)
        if existing_results and total_units > 0 and len(existing_results) == total_units:
            job.status = "completed"
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            if job.status in {"completed", "failed", "canceled"}:
                return job
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "canceled"
            elif job.status == "running":
                job.status = "canceling"
            job.updated_at = time.time()
            return job

    def set_output_path(self, job_id: str, output_path: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            job.output_path = output_path
            job.updated_at = time.time()
            return job

    def run(
        self,
        job_id: str,
        processor: Callable[..., list[BatchResult]],
        on_result: Callable[[BatchResult], None] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status in {"completed", "canceled"} or job.cancel_requested:
                job.status = "canceled" if job.cancel_requested else job.status
                job.updated_at = time.time()
                return
            job.status = "running"
            job.updated_at = time.time()

        try:
            existing_results = list(job.results)

            def _should_stop() -> bool:
                with self._lock:
                    return self._jobs[job_id].cancel_requested

            def _record_result(result: BatchResult) -> None:
                with self._lock:
                    by_cnpj = {item.normalized_cnpj: item for item in job.results}
                    by_cnpj[result.normalized_cnpj] = result
                    job.results = [by_cnpj[item] for item in job.input_cnpjs if item in by_cnpj]
                    job.updated_at = time.time()
                if on_result:
                    on_result(result)

            try:
                results = processor(
                    job.input_cnpjs,
                    existing_results=existing_results,
                    on_result=_record_result,
                    should_stop=_should_stop,
                )
            except TypeError:
                results = processor(job.input_cnpjs)
            with self._lock:
                job.results = results
                job.status = "canceled" if job.cancel_requested else "completed"
                job.updated_at = time.time()
        except Exception as exc:
            with self._lock:
                job.error = str(exc)
                job.status = "canceled" if job.cancel_requested else "failed"
                job.updated_at = time.time()

    def run_name(
        self,
        job_id: str,
        processor: Callable[..., list[BatchResult]],
        on_result: Callable[[BatchResult], None] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status in {"completed", "canceled"} or job.cancel_requested:
                job.status = "canceled" if job.cancel_requested else job.status
                job.updated_at = time.time()
                return
            job.status = "running"
            job.updated_at = time.time()

        def _result_key(result: BatchResult) -> str:
            meta = result.name_meta or {}
            return str(meta.get("row_number", "") or meta.get("query_name", ""))

        def _query_key(query) -> str:
            return str(getattr(query, "row_number", 0) or getattr(query, "company_name", ""))

        try:
            order = [_query_key(query) for query in job.name_queries]
            done_keys = {_result_key(result) for result in job.results}
            pending = [query for query in job.name_queries if _query_key(query) not in done_keys]

            def _should_stop() -> bool:
                with self._lock:
                    return self._jobs[job_id].cancel_requested

            def _record_result(result: BatchResult) -> None:
                with self._lock:
                    by_key = {_result_key(item): item for item in job.results}
                    by_key[_result_key(result)] = result
                    job.results = [by_key[key] for key in order if key in by_key]
                    job.updated_at = time.time()
                if on_result:
                    on_result(result)

            try:
                processor(pending, on_result=_record_result, should_stop=_should_stop)
            except TypeError:
                processor(pending)
            with self._lock:
                job.status = "canceled" if job.cancel_requested else "completed"
                job.updated_at = time.time()
        except Exception as exc:
            with self._lock:
                job.error = str(exc)
                job.status = "canceled" if job.cancel_requested else "failed"
                job.updated_at = time.time()
