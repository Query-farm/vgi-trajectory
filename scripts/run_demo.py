"""Run a GIS SQL contract with a deadline and explicit engine/worker provenance."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import shlex
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def command_string(argv: list[str]) -> str:
    """Quote an executable argv using the host platform's process syntax."""
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def sql_string(value: str) -> str:
    """Quote a SQL string literal without interpreting command text."""
    return "'" + value.replace("'", "''") + "'"


def stop_process(process: subprocess.Popen[str]) -> None:
    """Terminate the verifier and its worker descendants when a deadline expires."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.communicate()


def run_queries(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Execute real SQL and check normalized results against the portable manifest."""
    spec = json.loads((root / "vgi-worker.json").read_text())
    if args.location:
        location = args.location
    else:
        worker = args.worker or root / spec["worker"][0]
        if not args.worker and os.name == "nt":
            worker = root / ".venv" / "Scripts" / (Path(spec["worker"][0]).name + ".exe")
        if not worker.is_file():
            raise ValueError(f"Worker executable does not exist: {worker}; run uv sync --locked")
        location = command_string([str(worker.resolve())])
    engine = importlib.import_module(args.engine)
    with TemporaryDirectory(prefix="vgi-repositories-") as repositories:
        config = {"extension_repository_directory": repositories} if args.engine == "duckdb" else {}
        connection = engine.connect(":memory:", config=config)
        try:
            if args.engine == "duckdb":
                connection.execute("SET allow_extension_repositories='allowed'")
                connection.execute(
                    "CREATE EXTENSION REPOSITORY query_farm WITH PREFIX 'https://duckdb-extensions.query.farm'"
                )
                connection.execute("INSTALL vgi FROM query_farm; LOAD vgi FROM query_farm")
            else:
                connection.execute("INSTALL vgi FROM community; LOAD vgi")
            if location.startswith(("http://", "https://")):
                connection.execute("INSTALL httpfs; LOAD httpfs")
            attach = f"ATTACH {sql_string(spec['catalog'])} (TYPE vgi, LOCATION {sql_string(location)})"
            connection.execute(attach)
            checks = (
                spec["checks"]
                if args.verify
                else [
                    {"name": f"Demo {i + 1}", "sql": statement.query}
                    for i, statement in enumerate(
                        connection.extract_statements((args.sql_file or root / "demo.sql").read_text())
                    )
                ]
            )
            results = []
            for check in checks:
                print(check["name"], file=sys.stderr, flush=True)
                item = {"name": check["name"], "sql": check["sql"], "status": "passed"}
                try:
                    cursor = connection.execute(check["sql"])
                    rows = json.loads(json.dumps(cursor.fetchall(), default=str, allow_nan=False))
                    columns = [column[0] for column in cursor.description]
                    item.update(rows=rows, columns=columns)
                    if args.verify and json.dumps(rows) != json.dumps(check["rows"]):
                        raise AssertionError(f"Expected {check['rows']!r}, got {rows!r}")
                    if "columns" in check and columns != check["columns"]:
                        raise AssertionError(f"Expected columns {check['columns']!r}, got {columns!r}")
                except Exception as exc:
                    item.update(status="failed", error=str(exc))
                results.append(item)
            version = connection.execute("SELECT version()").fetchone()[0]
            extension = connection.execute(
                "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='vgi'"
            ).fetchone()[0]
            connection.execute('DETACH "' + spec["catalog"].replace('"', '""') + '"')
            return {
                "engine": args.engine,
                "engine_version": engine.__version__,
                "sql_version": version,
                "extension_version": extension,
                "attach_sql": attach,
                "worker": location,
                "status": "passed" if all(c["status"] == "passed" for c in results) else "failed",
                "checks": results,
            }
        finally:
            connection.close()


def main() -> int:
    """Supervise SQL execution so stalled network or worker calls cannot hang a release gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["duckdb", "haybarn"], default="duckdb")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--worker", type=Path, help="Executable from a clean wheel installation")
    location.add_argument("--location", help="VGI endpoint, e.g. http://127.0.0.1:8000")
    query = parser.add_mutually_exclusive_group()
    query.add_argument("--verify", action="store_true", help="Assert all vgi-worker.json results")
    query.add_argument("--sql-file", type=Path, help="Run a SQL file after attaching this worker")
    parser.add_argument("--timeout", type=float, default=180, help="Whole-run deadline in seconds")
    parser.add_argument("--output", type=Path, help="Save the JSON evidence report")
    parser.add_argument("--_run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if args._run:
        try:
            report = run_queries(args, Path(__file__).resolve().parents[1])
        except Exception as exc:
            report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    else:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_run"],
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            start_new_session=os.name != "nt",
        )
        try:
            stdout, _ = process.communicate(timeout=args.timeout)
            report = json.loads(stdout)
            if process.returncode:
                report.update(status="failed", exit_code=process.returncode)
        except subprocess.TimeoutExpired:
            stop_process(process)
            report = {"status": "failed", "error": "SQL verification deadline exceeded", "timeout": args.timeout}
        except BaseException:
            stop_process(process)
            raise
    output = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output and not args._run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    print(output, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
