"""Build a locked, unprivileged container and exercise its GIS contract over HTTP."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def command(argv: list[str], *, timeout: float = 180) -> str:
    """Run a bounded Docker operation and retain diagnostics in the release log."""
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {result.stderr[-6000:]} {result.stdout[-1000:]}")
    return (result.stdout + result.stderr).strip() if argv[1] == "logs" else result.stdout.strip()


def main() -> None:
    """Verify container startup, read-only operation and all SQL acceptance queries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("validation/container.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    name = project["name"] + "-check-" + uuid.uuid4().hex[:10]
    image = project["name"] + ":production-check"
    print(f"Building {image}", file=sys.stderr, flush=True)
    command(["docker", "build", "--tag", image, str(root)], timeout=600)
    identifier = command(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::8000",
            "--read-only",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,size=256m,mode=1777",
            "--tmpfs",
            "/home/worker/.cache:rw,nosuid,size=256m,mode=1777",
            "--tmpfs",
            "/var/lib/vgi:rw,nosuid,size=1g,mode=0700,uid=10001,gid=10001",
            image,
        ]
    )
    try:
        endpoint = "http://" + command(["docker", "port", identifier, "8000/tcp"]).splitlines()[0]
        deadline = time.monotonic() + 90
        while True:
            try:
                with urllib.request.urlopen(endpoint + "/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            running = command(["docker", "inspect", "--format", "{{.State.Running}}", identifier])
            if running != "true" or time.monotonic() >= deadline:
                raise RuntimeError("Container did not become healthy: " + command(["docker", "logs", identifier]))
            time.sleep(0.5)
        print(f"Checking SQL through {endpoint}", file=sys.stderr, flush=True)
        result = subprocess.run(
            [sys.executable, str(root / "scripts/run_demo.py"), "--verify", "--location", endpoint],
            capture_output=True,
            text=True,
            timeout=210,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr + command(["docker", "logs", identifier]))
        report: dict[str, Any] = json.loads(result.stdout)
        report.update(
            image=image,
            image_id=command(["docker", "inspect", "--format", "{{.Image}}", identifier]),
            runtime_user=command(["docker", "exec", identifier, "id", "-u"]),
            read_only_root=True,
            memory_limit_bytes=2147483648,
        )
        if report["runtime_user"] == "0":
            raise AssertionError("Production container must not run as root")
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"image": image, "status": report["status"], "checks": len(report["checks"])}))
    finally:
        subprocess.run(["docker", "rm", "--force", identifier], capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    main()
