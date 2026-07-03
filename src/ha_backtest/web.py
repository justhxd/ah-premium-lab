from __future__ import annotations

import argparse
import json
import mimetypes
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


jobs = JobStore()


class BacktestRequestHandler(SimpleHTTPRequestHandler):
    server_version = "HABacktestWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/strategies":
            self._handle_get_strategies()
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
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")

    def _handle_get_strategies(self) -> None:
        strategies = [metadata.__dict__ for metadata in list_strategy_metadata()]
        self._send_json({"strategies": strategies})

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

        job = jobs.get(job_id)
        if not job or not job.output_dir:
            self._send_json({"error": "任务或输出目录不存在。"}, HTTPStatus.NOT_FOUND)
            return

        output_dir = Path(job.output_dir).resolve()
        file_path = (output_dir / filename).resolve()
        if output_dir not in file_path.parents or not file_path.exists():
            self._send_json({"error": "文件不存在。"}, HTTPStatus.NOT_FOUND)
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
        jobs.update(
            job_id,
            progress=18,
            step="load_pairs",
            message=f"已读取 {len(pairs)} 个 AH 标的，输出目录已创建。",
            output_dir=str(output_dir),
        )

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
    except Exception as exc:
        jobs.update(
            job_id,
            status="failed",
            progress=100,
            step="failed",
            message="任务执行失败。",
            completed_at=_now(),
            error=f"{exc}\n{traceback.format_exc()}",
        )



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


