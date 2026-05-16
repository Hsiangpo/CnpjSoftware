from __future__ import annotations

import sys
import platform
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import CompanyAnalyzer
from .cf_bypass import BlurpathProxyConfig, probe_blurpath_proxy
from .checkpoints import CheckpointStore
from .cnpj import dedupe_preserve_order, extract_cnpjs, normalize_cnpj, validate_cnpj
from .config import load_settings, update_runtime_settings
from .jobs import JobStore
from .llm import LLMClient
from .models import BatchResult, is_business_success
from .providers import build_company_client
from .source_files import list_output_files, list_source_files, load_source_file, output_filename_for


class JobRequest(BaseModel):
    text: str = ""
    cnpjs: list[str] = []
    source_name: str = ""


class RetryOneRequest(BaseModel):
    cnpj: str


class SettingsUpdateRequest(BaseModel):
    llm_api_key: str | None = None
    llm_model: str | None = None
    system_concurrency: int | None = None
    blurpath_proxy_ports: list[int] | None = None
    blurpath_proxy_host: str | None = None
    blurpath_proxy_protocol: str | None = None
    blurpath_proxy_username: str | None = None
    blurpath_proxy_password: str | None = None
    blurpath_proxy_region: str | None = None
    blurpath_proxy_session_time_minutes: int | None = None


def resource_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def _normalize_input(request: JobRequest) -> list[str]:
    cnpjs = extract_cnpjs(request.text)
    for raw in request.cnpjs:
        digits = normalize_cnpj(raw)
        if validate_cnpj(digits):
            cnpjs.append(digits)
    return cnpjs


def build_analyzer() -> CompanyAnalyzer:
    settings = load_settings()
    proxy_configs = _blurpath_proxy_configs(settings) if settings.blurpath_proxy_configured else []
    company_client = build_company_client(
        provider_order=settings.cnpj_provider_order,
        cnpj_biz_proxy_configs=proxy_configs,
        cnpj_biz_user_agent=settings.cnpj_biz_user_agent,
    )
    llm_client = None
    if settings.llm_api_key:
        llm_client = LLMClient(
            api_key=settings.llm_api_key,
            base_urls=settings.llm_base_urls,
            model=settings.llm_model,
            fallback_models=settings.llm_fallback_models,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        llm_client.preflight(chat_timeout_seconds=min(settings.llm_timeout_seconds, 6))
    return CompanyAnalyzer(
        fetch_company=company_client.fetch_company,
        analyze_with_llm=llm_client.analyze_company if llm_client else None,
        request_delay_seconds=settings.cnpj_biz_request_delay_seconds,
        max_concurrency=settings.system_concurrency,
    )


def get_or_build_analyzer(app: FastAPI) -> CompanyAnalyzer:
    analyzer = getattr(app.state, "analyzer", None)
    if analyzer is None:
        analyzer = build_analyzer()
        app.state.analyzer = analyzer
    return analyzer


def get_checkpoint_store(app: FastAPI) -> CheckpointStore:
    store = getattr(app.state, "checkpoints", None)
    if store is None:
        store = CheckpointStore(load_settings().checkpoint_dir)
        app.state.checkpoints = store
    return store


def _settings_payload() -> dict[str, Any]:
    settings = load_settings()
    public = settings.to_public_dict()
    available_ports = list(dict.fromkeys(
        [node.port for node in settings.blurpath_proxy_nodes] or list(settings.blurpath_proxy_ports)
    ))
    return {
        "llm_api_key": public["llm_api_key"],
        "llm_model": public["llm_model"],
        "llm_fallback_models": public["llm_fallback_models"],
        "llm_base_urls": public["llm_base_urls"],
        "system_concurrency": public["system_concurrency"],
        "provider_order": public["cnpj_provider_order"],
        "cnpj_biz_user_agent": public["cnpj_biz_user_agent"],
        "input_dir": public["input_dir"],
        "output_dir": public["output_dir"],
        "blurpath_available_proxy_ports": available_ports,
        "blurpath_proxy_host": public["blurpath_proxy_host"],
        "blurpath_proxy_protocol": public["blurpath_proxy_protocol"],
        "blurpath_proxy_username": public["blurpath_proxy_username"],
        "blurpath_proxy_password": public["blurpath_proxy_password"],
        "blurpath_proxy_region": public["blurpath_proxy_region"],
        "blurpath_proxy_session_time_minutes": public["blurpath_proxy_session_time_minutes"],
        "blurpath_proxy_ports": public["blurpath_proxy_ports"],
    }


def _proxy_payload(settings: Any) -> dict[str, Any]:
    return {
        "configured": settings.blurpath_proxy_configured,
        "proxy_configured": settings.blurpath_proxy_configured,
        "node_mode": bool(getattr(settings, "blurpath_proxy_nodes", [])),
        "node_count": len(settings.blurpath_proxy_ports),
        "host": settings.blurpath_proxy_host,
        "region": settings.blurpath_proxy_region or "RANDOM",
        "protocol": settings.blurpath_proxy_protocol,
        "ports": settings.blurpath_proxy_ports,
        "session_time_minutes": settings.blurpath_proxy_session_time_minutes,
    }


def _blurpath_proxy_configs(settings: Any) -> list[BlurpathProxyConfig]:
    if getattr(settings, "blurpath_proxy_nodes", None):
        node_by_port = {node.port: node for node in settings.blurpath_proxy_nodes}
        return [
            BlurpathProxyConfig(
                host=node_by_port[port].host,
                port=node_by_port[port].port,
                username=node_by_port[port].username,
                password=node_by_port[port].password,
                region=settings.blurpath_proxy_region,
                protocol=node_by_port[port].protocol,
                session_time_minutes=settings.blurpath_proxy_session_time_minutes,
                username_template="",
            )
            for port in settings.blurpath_proxy_ports
            if port in node_by_port
        ]
    return [
        BlurpathProxyConfig(
            host=settings.blurpath_proxy_host,
            port=port,
            username=settings.blurpath_proxy_username,
            password=settings.blurpath_proxy_password,
            region=settings.blurpath_proxy_region,
            protocol=settings.blurpath_proxy_protocol,
            session_time_minutes=settings.blurpath_proxy_session_time_minutes,
            username_template=settings.blurpath_proxy_username_template,
        )
        for port in settings.blurpath_proxy_ports
    ]


def _output_path_for(settings: Any, filename: str, source_type: str) -> Path:
    return settings.output_dir / output_filename_for(filename, source_type)


def _clean_open_error_output(text: str) -> str:
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
        and "dbind-WARNING" not in line
        and "AT-SPI:" not in line
    ]
    return " | ".join(lines)


def _spreadsheet_launcher_hint(path: Path, error_text: str) -> str:
    association = ""
    if shutil.which("xdg-mime"):
        mime_type = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
        }.get(path.suffix.lower(), "")
        if mime_type:
            result = subprocess.run(["xdg-mime", "query", "default", mime_type], capture_output=True, text=True)
            association = (result.stdout or "").strip()
    message = "No spreadsheet application is installed or associated with this file type"
    if association:
        message += f" (desktop entry: {association})"
    if error_text:
        message += f". Launcher output: {error_text}"
    return message


def _open_path(path: Path) -> list[str]:
    system = platform.system()
    if system == "Windows":
        command = ["explorer", str(path)]
        subprocess.Popen(command)
        return command
    if system == "Darwin":
        command = ["open", str(path)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return command
        raise RuntimeError(_clean_open_error_output(result.stderr or result.stdout or "open failed"))

    attempted: list[str] = []
    for command in (
        ["xdg-open", str(path)] if shutil.which("xdg-open") else None,
        ["gio", "open", str(path)] if shutil.which("gio") else None,
    ):
        if command is None:
            continue
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return command
        attempted.append(_clean_open_error_output(result.stderr or result.stdout or f"{command[0]} failed"))

    office_command = None
    if path.suffix.lower() in {".xlsx", ".xls", ".csv"}:
        if shutil.which("libreoffice"):
            office_command = ["libreoffice", "--view", str(path)]
        elif shutil.which("soffice"):
            office_command = ["soffice", "--view", str(path)]
    if office_command is not None:
        subprocess.Popen(office_command)
        return office_command

    error_text = " | ".join(item for item in attempted if item) or "No file opener is available"
    if path.suffix.lower() in {".xlsx", ".xls", ".csv"}:
        raise RuntimeError(_spreadsheet_launcher_hint(path, error_text))
    raise RuntimeError(error_text)


def _safe_output_file_path(root: Path, filename: str) -> Path:
    candidate = (root / filename).resolve()
    root_resolved = root.resolve()
    if candidate.parent != root_resolved:
        raise FileNotFoundError(filename)
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(filename)
    return candidate


def _retry_job_kwargs(original: Any, settings: Any, cnpjs: list[str]) -> dict[str, Any]:
    if original.upload_id and original.source_name:
        output_path = original.output_path
        if not output_path and original.filename:
            source_type = Path(original.filename).suffix.lower().lstrip(".")
            output_path = str(_output_path_for(settings, original.filename, source_type))
        return {
            "upload_id": original.upload_id,
            "source_name": original.source_name,
            "filename": original.filename or original.source_name,
            "output_path": output_path,
        }
    stem = Path(original.filename or original.source_name or original.job_id).stem
    return {
        "source_name": original.source_name,
        "filename": f"{stem}-failed-retry.csv",
        "output_path": str(settings.output_dir / f"{stem}-failed-retry.csv"),
    }


def _redact_proxy_error(error: str, settings: Any) -> str:
    text = str(error or "")
    for secret in [settings.blurpath_proxy_username, settings.blurpath_proxy_password]:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def create_app(auto_run_jobs: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        analyzer = getattr(app.state, "analyzer", None)
        close = getattr(analyzer, "close", None)
        if callable(close):
            close()

    app = FastAPI(title="CNPJ Responsible Finder", version="0.1.0", lifespan=lifespan)
    app.state.jobs = JobStore()
    app.state.analyzer = None
    app.state.checkpoints = CheckpointStore(load_settings().checkpoint_dir)

    static_dir = resource_root() / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Frontend assets not found")
        return FileResponse(index_path)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings = load_settings()
        proxy = _proxy_payload(settings)
        return {
            "status": "ok",
            "model": settings.llm_model,
            "fallback_models": settings.llm_fallback_models,
            "base_urls": settings.llm_base_urls,
            "has_llm_key": bool(settings.llm_api_key),
            "provider_order": settings.cnpj_provider_order,
            "system_concurrency": settings.system_concurrency,
            "blurpath_proxy_configured": settings.blurpath_proxy_configured,
            "browser_proxy": proxy,
        }

    @app.get("/api/proxy-preflight")
    def proxy_preflight() -> dict[str, Any]:
        settings = load_settings()
        payload = _proxy_payload(settings)
        payload.update(
            {
            "probe_url": "https://api.ipify.org",
            "proxy_probe_ok": False,
            "proxy_probe_results": [],
            "proxy_error": "",
            }
        )
        if not settings.blurpath_proxy_configured:
            payload["proxy_error"] = "Blurpath proxy is not configured"
            return payload
        results = [
            probe_blurpath_proxy(
                config,
                session_id=f"probe{config.port}",
                timeout_seconds=10,
            )
            for config in _blurpath_proxy_configs(settings)
        ]
        for item in results:
            item["error"] = _redact_proxy_error(item.get("error", ""), settings)
        payload["proxy_probe_results"] = results
        payload["proxy_probe_ok"] = any(item.get("ok") for item in results)
        return payload

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return _settings_payload()

    @app.put("/api/settings")
    def put_settings(request: SettingsUpdateRequest) -> dict[str, Any]:
        try:
            update_runtime_settings(
                llm_api_key=request.llm_api_key,
                llm_model=request.llm_model,
                system_concurrency=request.system_concurrency,
                blurpath_proxy_ports=request.blurpath_proxy_ports,
                blurpath_proxy_host=request.blurpath_proxy_host,
                blurpath_proxy_protocol=request.blurpath_proxy_protocol,
                blurpath_proxy_username=request.blurpath_proxy_username,
                blurpath_proxy_password=request.blurpath_proxy_password,
                blurpath_proxy_region=request.blurpath_proxy_region,
                blurpath_proxy_session_time_minutes=request.blurpath_proxy_session_time_minutes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app.state.analyzer = None
        return _settings_payload()

    @app.get("/api/source-files")
    def get_source_files() -> dict[str, Any]:
        settings = load_settings()
        files = [item.to_dict() for item in list_source_files(settings.input_dir, get_checkpoint_store(app), settings.output_dir)]
        return {
            "input_dir": str(settings.input_dir),
            "output_dir": str(settings.output_dir),
            "files": files,
        }

    @app.get("/api/output-files")
    def get_output_files() -> dict[str, Any]:
        settings = load_settings()
        return {
            "output_dir": str(settings.output_dir),
            "files": list_output_files(settings.output_dir),
        }

    @app.post("/api/output-files/{filename}/open")
    def open_output_file(filename: str) -> dict[str, Any]:
        settings = load_settings()
        try:
            path = _safe_output_file_path(settings.output_dir, filename)
            command = _open_path(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Output file not found") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"opened": True, "path": str(path)}

    @app.post("/api/output-directory/open")
    def open_output_directory() -> dict[str, Any]:
        settings = load_settings()
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            command = _open_path(settings.output_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"opened": True, "output_dir": str(settings.output_dir)}

    def run_job(job_id: str) -> None:
        analyzer = get_or_build_analyzer(app)
        job = app.state.jobs.get(job_id)
        settings = load_settings()
        output_flush_batch_size = settings.output_flush_batch_size
        output_flush_interval_seconds = settings.output_flush_interval_seconds
        pending_output_flush_count = 0
        last_output_flush_at = 0.0
        has_materialized_output = False

        def materialize_current_output(*, force: bool = False) -> None:
            nonlocal has_materialized_output, last_output_flush_at, pending_output_flush_count
            now = time.monotonic()
            if (
                not force
                and has_materialized_output
                and pending_output_flush_count < output_flush_batch_size
                and now - last_output_flush_at < output_flush_interval_seconds
            ):
                return
            current_job = app.state.jobs.get(job_id)
            if not current_job.upload_id or not current_job.output_path:
                return
            full_results = get_checkpoint_store(app).load_results(current_job.upload_id)
            if not full_results:
                return
            output_path = get_checkpoint_store(app).materialize_output(
                upload_id=current_job.upload_id,
                filename=current_job.filename or current_job.source_name or current_job.job_id,
                output_path=Path(current_job.output_path),
                results=full_results,
            )
            app.state.jobs.set_output_path(job_id, str(output_path))
            has_materialized_output = True
            last_output_flush_at = time.monotonic()
            pending_output_flush_count = 0

        def persist_result(result: BatchResult) -> None:
            nonlocal pending_output_flush_count
            if not job.upload_id:
                return
            get_checkpoint_store(app).upsert_result(
                upload_id=job.upload_id,
                filename=job.filename or "upload",
                input_cnpjs=job.input_cnpjs,
                result=result,
            )
            pending_output_flush_count += 1
            try:
                materialize_current_output(force=not has_materialized_output)
            except Exception:
                pass

        app.state.jobs.run(job_id, analyzer.analyze_many, on_result=persist_result)
        materialize_current_output(force=True)

    @app.post("/api/jobs")
    def create_job(request: JobRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        settings = load_settings()
        existing_results: list[BatchResult] = []
        upload_id = ""
        filename = ""
        source_name = request.source_name
        output_path = ""
        if request.source_name:
            try:
                path, data, details = load_source_file(settings.input_dir, request.source_name)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Source file not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            cnpjs = details.cnpjs
            upload_id = get_checkpoint_store(app).build_upload_id(path.name, data, details.cnpjs)
            get_checkpoint_store(app).register_upload(
                upload_id=upload_id,
                filename=path.name,
                data=data,
                input_cnpjs=details.cnpjs,
                row_refs=details.row_refs,
                source_type=details.source_type,
            )
            existing_results = get_checkpoint_store(app).load_results(upload_id)
            filename = path.name
            output_path = str(_output_path_for(settings, path.name, details.source_type))
        else:
            cnpjs = _normalize_input(request)
        if not cnpjs:
            raise HTTPException(status_code=400, detail="No valid CNPJ values found")
        job = app.state.jobs.create(
            cnpjs,
            upload_id=upload_id,
            source_name=source_name,
            filename=filename,
            output_path=output_path,
            existing_results=existing_results,
        )
        if auto_run_jobs:
            background_tasks.add_task(run_job, job.job_id)
        return job.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [job.to_dict() for job in app.state.jobs.list()]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return app.state.jobs.get(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return app.state.jobs.cancel(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/api/jobs/{job_id}/retry-failed")
    def retry_failed_job(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
        settings = load_settings()
        try:
            original = app.state.jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        source_results = (
            get_checkpoint_store(app).load_results(original.upload_id)
            if original.upload_id
            else original.results
        )
        failed_cnpjs = [
            item.normalized_cnpj
            for item in source_results
            if not is_business_success(item)
        ]
        failed_cnpjs = dedupe_preserve_order(failed_cnpjs)
        if not failed_cnpjs:
            raise HTTPException(status_code=400, detail="This job has no failed CNPJ values")
        retry_job = app.state.jobs.create(
            failed_cnpjs,
            **_retry_job_kwargs(original, settings, failed_cnpjs),
        )
        if auto_run_jobs:
            background_tasks.add_task(run_job, retry_job.job_id)
        return retry_job.to_dict()

    @app.post("/api/jobs/{job_id}/retry-one")
    def retry_one_job(job_id: str, request: RetryOneRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        settings = load_settings()
        try:
            original = app.state.jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        digits = normalize_cnpj(request.cnpj)
        if not validate_cnpj(digits):
            raise HTTPException(status_code=400, detail="Invalid CNPJ") from None
        source_results = (
            get_checkpoint_store(app).load_results(original.upload_id)
            if original.upload_id
            else original.results
        )
        available = {item.normalized_cnpj for item in source_results}
        if digits not in available and digits not in {normalize_cnpj(item) for item in original.input_cnpjs}:
            raise HTTPException(status_code=404, detail="CNPJ not found in this job")
        retry_job = app.state.jobs.create(
            [digits],
            **_retry_job_kwargs(original, settings, [digits]),
        )
        if auto_run_jobs:
            background_tasks.add_task(run_job, retry_job.job_id)
        return retry_job.to_dict()

    return app


app = create_app()
