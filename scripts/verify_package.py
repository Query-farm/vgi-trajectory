"""Build from an sdist and verify the wheel outside the checkout with locked runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def run(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute a bounded packaging command with diagnostics on stderr."""
    return subprocess.run(argv, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=sys.stderr, timeout=300)


def main() -> None:
    """Produce a reproducible wheel and save evidence from an isolated installation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("validation/packaged.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    executable = next(iter(project["scripts"]))
    with TemporaryDirectory(prefix=executable + "-release-") as temporary:
        stage = Path(temporary)
        run(["uv", "build", "--sdist", "--out-dir", str(stage / "sdist")], cwd=root)
        sdist = next((stage / "sdist").glob("*.tar.gz"))
        # Build from the archive, not the editable checkout; fixture inclusion is part of the contract.
        run(["uv", "build", "--wheel", str(sdist), "--out-dir", str(stage / "wheel")], cwd=stage)
        wheel = next((stage / "wheel").glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            metadata = BytesParser().parsebytes(archive.read(metadata_path))
            if metadata["License-Expression"] != "0BSD":
                raise AssertionError("Wheel license metadata must match LICENSE")
            if not any("/data/" in name for name in archive.namelist()):
                raise AssertionError("Wheel must include the offline analysis fixtures")
        requirements = stage / "requirements.txt"
        run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--no-hashes",
                "--output-file",
                str(requirements),
            ],
            cwd=root,
        )
        environment = stage / "venv"
        run(["uv", "venv", "--python", sys.executable, str(environment)], cwd=stage)
        bindir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        worker = bindir / (executable + (".exe" if os.name == "nt" else ""))
        run(
            ["uv", "pip", "install", "--python", str(python), "-r", str(requirements), str(wheel), "duckdb==2.0.0"],
            cwd=stage,
        )
        # Extract the release scripts/manifest too, so repository files cannot mask missing sdist contents.
        with tarfile.open(sdist) as archive:
            archive.extractall(stage / "source", filter="data")
        source = next((stage / "source").iterdir())
        result = run([str(python), str(source / "scripts/run_demo.py"), "--verify", "--worker", str(worker)], cwd=stage)
        report: dict[str, Any] = json.loads(result.stdout)
        if report["status"] != "passed":
            raise AssertionError(report)
        report.update(
            wheel=wheel.name,
            sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
            sdist=sdist.name,
            sdist_sha256=hashlib.sha256(sdist.read_bytes()).hexdigest(),
            isolated_install=True,
            built_from_sdist=True,
            runtime_dependencies="uv.lock",
        )
        destination = root / "dist"
        destination.mkdir(exist_ok=True)
        for artifact in (sdist, wheel):
            (destination / artifact.name).write_bytes(artifact.read_bytes())
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "wheel": wheel.name, "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
