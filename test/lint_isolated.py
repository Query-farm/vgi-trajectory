"""Run the published metadata checker with an empty, non-persistent DuckDB secret store."""

from __future__ import annotations

import importlib
import tempfile
from typing import Any


def main() -> None:
    engine = importlib.import_module("haybarn")
    original_connect = engine.connect
    try:
        with tempfile.TemporaryDirectory(prefix="trajectory-lint-secrets-") as directory:

            def isolated_connect(*args: Any, **kwargs: Any) -> Any:
                config = dict(kwargs.pop("config", {}) or {})
                config.update(secret_directory=directory, allow_persistent_secrets=False)
                connection = original_connect(*args, config=config, **kwargs)
                assert connection.execute("SELECT name FROM duckdb_secrets()").fetchall() == []
                return connection

            engine.connect = isolated_connect
            importlib.import_module("vgi_lint_check.cli").app()
    finally:
        engine.connect = original_connect


if __name__ == "__main__":
    main()
