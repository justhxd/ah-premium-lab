from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .cli import DEFAULT_CACHE, DEFAULT_OUTPUT, DEFAULT_PAIRS, _make_run_output_dir
from .data import load_ah_pairs
from .core.context import StrategyRunRequest
from .core.output import ALLOWED_RESULT_FILES, summarize_output
from .core.registry import get_strategy, list_strategy_metadata


ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "ui"
ALLOWED_FILES = ALLOWED_RESULT_FILES
HISTORY_METADATA_FILE = "run_metadata.json"


@dataclass
class Job:
    id: str
    params: dict[str, Any]
    status: str = "queued"
    progress: int = 0
    step: str = "queued"
    message: str = "任务已进入队列。"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_dir: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, params: dict[str, Any]) -> Job:
        job = Job(id=uuid4().hex[:12], params=params)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)


jobs = JobStore()


class BacktestRequestHandler(SimpleHTTPRequestHandler):
    server_version = "HABacktestWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/strategies":
            self._handle_get_strategies()
            return
        if path == "/api/history":
            self._handle_get_history()
            return
        if path == "/api/status":
            self._handle_get_status()
            return
        if path.startswith("/api/jobs/"):
            self._handle_get_job(path)
            return
        if path.startswith("/api/files/"):
            self._handle_get_file(path)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            self._handle_create_job()
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/open-output-dir"):
            self._handle_open_output_dir(parsed.path)
            return
        if parsed.path.startswith("/api/history/") and parsed.path.endswith("/open-output-dir"):
            self._handle_open_output_dir(parsed.path)
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")

    def _handle_get_strategies(self) -> None:
        strategies = [metadata.__dict__ for metadata in list_strategy_metadata()]
        self._send_json({"strategies": strategies})

    def _handle_get_history(self) -> None:
        self._send_json({"runs": _list_history_runs()})

    def _handle_get_status(self) -> None:
        self._send_json(_status_payload())

    def _handle_create_job(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw or "{}")
            params = _normalize_payload(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except json.JSONDecodeError:
            self._send_json({"error": "请求体不是有效 JSON。"}, HTTPStatus.BAD_REQUEST)
            return

        job = jobs.create(params)
        thread = threading.Thread(target=_run_job, args=(job.id,), daemon=True)
        thread.start()
        self._send_json(_job_payload(job), HTTPStatus.ACCEPTED)

    def _handle_get_job(self, path: str) -> None:
        job_id = path.rstrip("/").split("/")[-1]
        job = jobs.get(job_id)
        if not job:
            self._send_json({"error": "任务不存在。"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(_job_payload(job))

    def _handle_open_output_dir(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "api" or parts[1] not in {"jobs", "history"} or parts[3] != "open-output-dir":
            self._send_json({"error": "\u8f93\u51fa\u76ee\u5f55\u8bf7\u6c42\u65e0\u6548\u3002"}, HTTPStatus.BAD_REQUEST)
            return

        output_dir = _resolve_output_dir(parts[2])
        if not output_dir:
            self._send_json({"error": "\u4efb\u52a1\u6216\u8f93\u51fa\u76ee\u5f55\u4e0d\u5b58\u5728\u3002"}, HTTPStatus.NOT_FOUND)
            return

        try:
            _open_directory(output_dir)
        except OSError as exc:
            self._send_json({"error": f"\u6253\u5f00\u8f93\u51fa\u76ee\u5f55\u5931\u8d25\uff1a{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"ok": True, "path": str(output_dir)})

    def _handle_get_file(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) < 5:
            self._send_json({"error": "文件路径无效。"}, HTTPStatus.BAD_REQUEST)
            return

        job_id = parts[3]
        filename = parts[4]
        if filename not in ALLOWED_FILES:
            self._send_json({"error": "不允许访问该文件。"}, HTTPStatus.BAD_REQUEST)
            return

        output_dir = _resolve_output_dir(job_id)
        if not output_dir:
            self._send_json({"error": "\u4efb\u52a1\u6216\u8f93\u51fa\u76ee\u5f55\u4e0d\u5b58\u5728\u3002"}, HTTPStatus.NOT_FOUND)
            return

        file_path = (output_dir / filename).resolve()
        if output_dir not in file_path.parents or not file_path.exists():
            self._send_json({"error": "\u6587\u4ef6\u4e0d\u5b58\u5728\u3002"}, HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        with file_path.open("rb") as handle:
            self.wfile.write(handle.read())

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (UI_DIR / relative).resolve()
        ui_root = UI_DIR.resolve()
        if ui_root not in target.parents and target != ui_root:
            self._send_json({"error": "Invalid static path"}, HTTPStatus.BAD_REQUEST)
            return
        if not target.exists() or not target.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with target.open("rb") as handle:
            self.wfile.write(handle.read())

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)



def _resolve_output_dir(run_id: str) -> Optional[Path]:
    job = jobs.get(run_id)
    if job and job.output_dir:
        output_dir = Path(job.output_dir).resolve()
        if output_dir.exists() and output_dir.is_dir():
            return output_dir
    return _history_output_dir(run_id)


def _history_output_dir(run_id: str) -> Optional[Path]:
    if not re.fullmatch(r"run_[A-Za-z0-9_-]+", str(run_id)):
        return None
    base_dir = Path(DEFAULT_OUTPUT).resolve()
    output_dir = (base_dir / run_id).resolve()
    if base_dir not in output_dir.parents or not output_dir.is_dir():
        return None
    return output_dir

def _open_directory(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


def _run_job(job_id: str) -> None:
    try:
        job = jobs.get(job_id)
        if not job:
            return
        params = job.params
        jobs.update(
            job_id,
            status="running",
            progress=8,
            step="validate",
            message="正在校验参数并读取 AH 股票池。",
            started_at=_now(),
        )
        pairs = load_ah_pairs(Path(params["pairs"]))
        if not pairs:
            raise RuntimeError(f"没有从 {params['pairs']} 读取到 AH 配对。")

        output_dir = _make_output_dir(Path(params["output_dir"]), params["strategy"], params["start"], params["end"])
        output_dir.mkdir(parents=True, exist_ok=True)
        jobs.update(
            job_id,
            progress=18,
            step="load_pairs",
            message=f"已读取 {len(pairs)} 个 AH 标的，输出目录已创建。",
            output_dir=str(output_dir),
        )
        _write_run_metadata(output_dir, job, params, "running")

        strategy = get_strategy(params["strategy"])
        jobs.update(job_id, progress=35, step="run_backtest", message="正在拉取或复用行情缓存，并执行 AKQuant 回测。")
        request = StrategyRunRequest(
            strategy_id=params["strategy"],
            pairs=pairs,
            start_date=params["start"],
            end_date=params["end"],
            cache_dir=Path(params["cache_dir"]),
            output_dir=output_dir,
            refresh=params["refresh"],
            fx_csv=Path(params["fx_csv"]) if params.get("fx_csv") else None,
            initial_cash=params["initial_cash"],
            min_premium=params["min_premium"],
            gross_exposure=params["gross_exposure"],
            integer_percent=params["integer_percent"],
            report=True,
        )
        strategy_result = strategy.run(request)
        run_repr = strategy_result.run_summary

        jobs.update(job_id, progress=92, step="summarize", message="正在汇总输出文件和最后一个交易日持仓。")
        summary = summarize_output(output_dir=output_dir, run_repr=run_repr)
        jobs.update(
            job_id,
            status="completed",
            progress=100,
            step="completed",
            message="任务执行完成。",
            completed_at=_now(),
            result=summary,
        )
        completed_job = jobs.get(job_id)
        if completed_job:
            _write_run_metadata(output_dir, completed_job, params, "completed")
    except Exception as exc:
        job = jobs.get(job_id)
        output_dir = Path(job.output_dir) if job and job.output_dir else None
        jobs.update(
            job_id,
            status="failed",
            progress=100,
            step="failed",
            message="任务执行失败。",
            completed_at=_now(),
            error=f"{exc}\n{traceback.format_exc()}",
        )
        failed_job = jobs.get(job_id)
        if failed_job and output_dir:
            _write_run_metadata(output_dir, failed_job, failed_job.params, "failed")



def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    strategy = str(payload.get("strategy") or "ha-premium")
    get_strategy(strategy)

    start = _clean_date(payload.get("start") or payload.get("startDate"), "开始日期")
    end = _clean_date(payload.get("end") or payload.get("endDate"), "结束日期")
    if start > end:
        raise ValueError("结束日期需要晚于或等于开始日期。")

    initial_cash = _positive_float(payload.get("initialCash", 1_000_000.0), "初始资金")
    gross_exposure = _positive_float(payload.get("grossExposure", 1.0), "总仓位上限")
    if gross_exposure > 1.0:
        gross_exposure = gross_exposure / 100.0
    if gross_exposure > 1.0:
        raise ValueError("总仓位上限不能超过 100%。")

    return {
        "strategy": strategy,
        "start": start,
        "end": end,
        "initial_cash": initial_cash,
        "gross_exposure": gross_exposure,
        "refresh": bool(payload.get("refresh") or payload.get("refreshData")),
        "integer_percent": bool(payload.get("integerPercent")),
        "min_premium": float(payload.get("minPremium", 0.0)),
        "pairs": str(payload.get("pairs") or DEFAULT_PAIRS),
        "cache_dir": str(payload.get("cacheDir") or DEFAULT_CACHE),
        "output_dir": str(payload.get("outputDir") or DEFAULT_OUTPUT),
        "fx_csv": payload.get("fxCsv") or None,
    }


def _make_output_dir(base_dir: Path, strategy: str, start_date: str, end_date: str) -> Path:
    return _make_run_output_dir(base_dir, start_date, end_date)


def _clean_date(value: Any, label: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"{label}格式应为 YYYY-MM-DD 或 YYYYMMDD。")
    parsed = datetime.strptime(text, "%Y%m%d")
    return parsed.strftime("%Y%m%d")


def _positive_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字。") from exc
    if number <= 0:
        raise ValueError(f"{label}必须大于 0。")
    return number



def _list_history_runs() -> list[dict[str, Any]]:
    base_dir = Path(DEFAULT_OUTPUT)
    if not base_dir.exists():
        return []

    runs = []
    for output_dir in base_dir.iterdir():
        if not output_dir.is_dir() or not output_dir.name.startswith("run_"):
            continue
        record = _history_record(output_dir)
        if record:
            runs.append(record)
    return sorted(runs, key=lambda item: item.get("createdAtSort") or "", reverse=True)


def _history_record(output_dir: Path) -> Optional[dict[str, Any]]:
    metadata = _read_run_metadata(output_dir)
    record = _record_from_metadata(output_dir, metadata) if metadata else _infer_history_record(output_dir)
    if not record:
        return None
    report_ready = (output_dir / "akquant_ha_report.html").exists()
    record["id"] = output_dir.name
    record["outputDir"] = str(output_dir)
    record["reportReady"] = report_ready
    record["files"] = [{"name": filename, "exists": (output_dir / filename).exists()} for filename in sorted(ALLOWED_RESULT_FILES)]
    if record.get("status") in {"queued", "running"}:
        record["status"] = "completed" if report_ready else "missing"
    else:
        record.setdefault("status", "completed" if report_ready else "missing")
    return record


def _read_run_metadata(output_dir: Path) -> Optional[dict[str, Any]]:
    path = output_dir / HISTORY_METADATA_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _record_from_metadata(output_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    params = metadata.get("params") or {}
    created_at = str(metadata.get("createdAtIso") or metadata.get("createdAt") or _mtime_iso(output_dir))
    return {
        "id": output_dir.name,
        "jobId": metadata.get("jobId"),
        "strategy": metadata.get("strategy") or params.get("strategy") or "unknown",
        "strategyName": metadata.get("strategyName") or _strategy_name(metadata.get("strategy") or params.get("strategy")),
        "createdAt": _display_datetime(created_at),
        "createdAtSort": created_at,
        "startDate": _display_date(metadata.get("startDate") or params.get("start")),
        "endDate": _display_date(metadata.get("endDate") or params.get("end")),
        "initialCash": _float_or_none(metadata.get("initialCash", params.get("initial_cash"))),
        "grossExposure": _float_or_none(metadata.get("grossExposure", params.get("gross_exposure"))),
        "refreshData": bool(metadata.get("refreshData", params.get("refresh", False))),
        "integerPercent": bool(metadata.get("integerPercent", params.get("integer_percent", False))),
        "minPremium": _float_or_none(metadata.get("minPremium", params.get("min_premium"))),
        "status": metadata.get("status") or "completed",
        "step": metadata.get("step"),
        "message": metadata.get("message"),
        "error": metadata.get("error"),
        "startedAt": _display_datetime(metadata.get("startedAtIso")),
        "completedAt": _display_datetime(metadata.get("completedAtIso")),
    }


def _infer_history_record(output_dir: Path) -> Optional[dict[str, Any]]:
    parsed = _parse_run_dir(output_dir.name)
    description = _read_description_params(output_dir / "strategy_description.md")
    created_at = parsed.get("createdAtIso") if parsed else _mtime_iso(output_dir)
    annual_line = description.get("annual_line_filter")
    if annual_line is True:
        strategy = "ha-premium-annual-line"
    elif annual_line is False:
        strategy = "ha-premium"
    else:
        strategy = "unknown"
    start_date = description.get("start") or (parsed or {}).get("start")
    end_date = description.get("end") or (parsed or {}).get("end")
    return {
        "id": output_dir.name,
        "strategy": strategy,
        "strategyName": _strategy_name(strategy),
        "createdAt": _display_datetime(created_at),
        "createdAtSort": created_at,
        "startDate": _display_date(start_date),
        "endDate": _display_date(end_date),
        "initialCash": description.get("initial_cash"),
        "grossExposure": description.get("gross_exposure"),
        "refreshData": bool(description.get("refresh", False)),
        "integerPercent": bool(description.get("integer_percent", False)),
        "minPremium": description.get("min_premium"),
        "status": "completed" if (output_dir / "akquant_ha_report.html").exists() else "missing",
        "step": "inferred",
        "message": "inferred from output directory",
    }


def _write_run_metadata(output_dir: Path, job: Job, params: dict[str, Any], status: str) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        strategy = get_strategy(params["strategy"])
        metadata = {
            "id": output_dir.name,
            "jobId": job.id,
            "strategy": params["strategy"],
            "strategyName": strategy.metadata.name,
            "createdAtIso": job.created_at,
            "startedAtIso": job.started_at,
            "completedAtIso": job.completed_at,
            "startDate": params["start"],
            "endDate": params["end"],
            "initialCash": params["initial_cash"],
            "grossExposure": params["gross_exposure"],
            "refreshData": params["refresh"],
            "integerPercent": params["integer_percent"],
            "minPremium": params["min_premium"],
            "status": status,
            "step": job.step,
            "message": job.error.splitlines()[0] if job.error else job.message,
            "error": job.error.splitlines()[0] if job.error else None,
            "params": params,
        }
        (output_dir / HISTORY_METADATA_FILE).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _status_payload() -> dict[str, Any]:
    active_jobs = [_status_record_from_job(job) for job in jobs.list()]
    history_runs = _list_history_runs()
    known_active_output_dirs = {item.get("outputDir") for item in active_jobs if item.get("outputDir")}
    history_records = [
        _status_record_from_history(run)
        for run in history_runs
        if run.get("outputDir") not in known_active_output_dirs
    ]
    recent_tasks = sorted(
        active_jobs + history_records,
        key=lambda item: item.get("sortTime") or "",
        reverse=True,
    )[:12]
    failures = [
        item
        for item in recent_tasks
        if item.get("status") in {"failed", "missing"} or item.get("error")
    ][:5]
    completed_runs = [run for run in history_runs if run.get("status") == "completed"]
    latest_run = history_runs[0] if history_runs else None
    return {
        "generatedAt": _display_datetime(_now()),
        "summary": {
            "activeJobs": sum(1 for item in active_jobs if item.get("status") in {"queued", "running"}),
            "completedRuns": len(completed_runs),
            "failedRuns": sum(1 for run in history_runs if run.get("status") == "failed"),
            "reportReadyRuns": sum(1 for run in history_runs if run.get("reportReady")),
            "latestRunAt": latest_run.get("createdAt") if latest_run else "--",
            "latestRunStatus": _status_text(latest_run.get("status")) if latest_run else "no records",
        },
        "recentTasks": recent_tasks,
        "failures": failures,
        "automation": {
            "lastRunAt": latest_run.get("createdAt") if latest_run else "--",
            "lastRunStatus": _status_text(latest_run.get("status")) if latest_run else "no historical runs",
            "source": "local output history",
            "message": "No scheduler state was detected; last run is inferred from data/run_* output directories.",
        },
    }


def _status_record_from_job(job: Job) -> dict[str, Any]:
    payload = _job_payload(job)
    params = job.params
    report_ready = bool(job.result and _has_result_file(job.result, "akquant_ha_report.html"))
    return {
        "id": job.id,
        "fileId": job.id,
        "kind": "job",
        "status": job.status,
        "statusText": _status_text(job.status),
        "progress": job.progress,
        "step": job.step,
        "message": payload.get("error") or job.message,
        "error": payload.get("error"),
        "createdAt": _display_datetime(job.created_at),
        "sortTime": job.completed_at or job.started_at or job.created_at,
        "strategy": params.get("strategy"),
        "strategyName": _strategy_name(params.get("strategy")),
        "startDate": _display_date(params.get("start")),
        "endDate": _display_date(params.get("end")),
        "outputDir": job.output_dir,
        "reportReady": report_ready,
    }


def _status_record_from_history(run: dict[str, Any]) -> dict[str, Any]:
    status = run.get("status") or ("completed" if run.get("reportReady") else "missing")
    return {
        "id": run.get("id"),
        "fileId": run.get("id"),
        "kind": "history",
        "status": status,
        "statusText": _status_text(status),
        "progress": 100 if status in {"completed", "failed", "missing"} else None,
        "step": run.get("step"),
        "message": run.get("error") or run.get("message") or _history_message(run),
        "error": run.get("error"),
        "createdAt": run.get("createdAt"),
        "sortTime": run.get("createdAtSort"),
        "strategy": run.get("strategy"),
        "strategyName": run.get("strategyName"),
        "startDate": run.get("startDate"),
        "endDate": run.get("endDate"),
        "outputDir": run.get("outputDir"),
        "reportReady": bool(run.get("reportReady")),
    }


def _history_message(run: dict[str, Any]) -> str:
    if run.get("reportReady"):
        return "report ready"
    return "output directory exists, but AKQuant HTML report is missing"


def _status_text(status: Any) -> str:
    return {
        "queued": "queued",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "missing": "missing report",
    }.get(str(status), "unknown")


def _has_result_file(result: dict[str, Any], filename: str) -> bool:
    return any(file.get("name") == filename and file.get("exists") for file in result.get("files", []))


def _parse_run_dir(name: str) -> dict[str, str]:
    match = re.match(r"^run_(\d{8})_(\d{8})_(\d{8})_(\d{6})(?:_\d+)?$", name)
    if not match:
        return {}
    start, end, day, clock = match.groups()
    return {
        "start": start,
        "end": end,
        "createdAtIso": f"{day[:4]}-{day[4:6]}-{day[6:8]}T{clock[:2]}:{clock[2:4]}:{clock[4:6]}",
    }


def _read_description_params(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    values = re.findall(r"`([^`]*)`", text)
    if len(values) < 12:
        return {}
    annual_line = _bool_or_none(values[6])
    if annual_line is None:
        annual_line = False
        min_premium_index = 6
        refresh_index = 8
    else:
        min_premium_index = 7
        refresh_index = 9
    return {
        "start": values[0],
        "end": values[1],
        "initial_cash": _float_or_none(values[3]),
        "gross_exposure": _float_or_none(values[4]),
        "integer_percent": _bool_or_none(values[5]),
        "annual_line_filter": annual_line,
        "min_premium": _float_or_none(values[min_premium_index]),
        "refresh": _bool_or_none(values[refresh_index]),
    }


def _strategy_name(strategy_id: Any) -> str:
    try:
        return get_strategy(str(strategy_id)).metadata.name
    except ValueError:
        return "未知策略"


def _display_date(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return str(value or "--")


def _display_datetime(value: Any) -> str:
    text = str(value or "")
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16] if text else "--"


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _job_payload(job: Job) -> dict[str, Any]:
    payload = asdict(job)
    if payload.get("error"):
        payload["error"] = str(payload["error"]).splitlines()[0]
    return payload


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web UI for H/A backtest jobs.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not UI_DIR.exists():
        raise SystemExit(f"UI directory does not exist: {UI_DIR}")

    server = ThreadingHTTPServer((args.host, args.port), BacktestRequestHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"H/A backtest web UI: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
