"""Assemble the functions into a catalog and run the worker.

To add a function: write it (see ``greet.py`` / ``sequence.py`` /
``fetch_items.py``), then add the class to ``FUNCTIONS`` below.

Run it:

    vgi-trajectory-worker                      # stdio: what DuckDB launches by default
    vgi-trajectory-worker --http --port 8000   # HTTP: for Docker / hosted deploys
    vgi-trajectory-worker --help

Attach it from DuckDB:

    ATTACH 'trajectory' (TYPE vgi, LOCATION '/abs/path/to/.venv/bin/vgi-trajectory-worker');
"""

from __future__ import annotations

import json
from typing import Any

from vgi import Worker
from vgi.catalog import Catalog, Schema

from .analysis import GIS_DESCRIPTION, GIS_FUNCTIONS, GIS_TABLES
from .fetch_items import API_SECRET_TYPE, FetchItems
from .greet import Greet, GreetWithStyle
from .meta import (
    CATALOG_NAME,
    CATALOG_TAGS,
    SCHEMA_CATEGORIES,
    SCHEMA_DOC_LLM,
    SCHEMA_DOC_MD,
    SOURCE_URL,
    keywords_array,
)
from .sequence import SequenceTable

FUNCTIONS: list[type[Any]] = [Greet, GreetWithStyle, SequenceTable, FetchItems]


def _stamp_example_queries(functions: list[type[Any]]) -> list[dict[str, str]]:
    """Publish each function's examples as ``vgi.example_queries`` (with descriptions).

    Overloads share one SQL name, so their examples are merged per name.
    Returns every example, for the schema-level list.
    """
    by_name: dict[str, list[dict[str, str]]] = {}
    for fn in functions:
        bucket = by_name.setdefault(fn.Meta.name, [])
        for ex in getattr(fn.Meta, "examples", []):
            entry = {"description": ex.description, "sql": ex.sql}
            if entry not in bucket:
                bucket.append(entry)
    for fn in functions:
        fn.Meta.tags = {**fn.Meta.tags, "vgi.example_queries": json.dumps(by_name[fn.Meta.name])}
    return [entry for entries in by_name.values() for entry in entries]


_ALL_EXAMPLES = _stamp_example_queries(FUNCTIONS)
_GIS_EXAMPLES = _stamp_example_queries(GIS_FUNCTIONS)


class TrajectoryWorker(Worker):
    """The worker process: one catalog, one ``main`` schema."""

    catalog = Catalog(
        name=CATALOG_NAME,
        comment=GIS_DESCRIPTION,
        source_url=SOURCE_URL,
        tags={
            **CATALOG_TAGS,
            "vgi.doc_llm": GIS_DESCRIPTION,
            "vgi.doc_md": "## GIS analysis\n\n" + GIS_DESCRIPTION + "\n\n### SQL workflow\n\n"
            "Pass query results to the main schema functions, retaining IDs for joins. "
            "Use bundled synthetic data to try the executable examples without network access. "
            "CRS, coverage, inference limits and resource bounds are explicit function parameters. "
            "The examples schema preserves the SDK regression recipes.",
            "vgi.subtitle": "Reconstruct visits, dwell and trips from GPS observations.",
        },
        schemas=[
            Schema(
                path=["main"],
                comment="Spatial functions and bundled inputs for " + CATALOG_NAME.replace("_", " ") + " analysis.",
                functions=GIS_FUNCTIONS,
                tables=GIS_TABLES,
                tags={
                    "vgi.title": "GIS Analysis",
                    "domain": "geospatial",
                    "vgi.keywords": keywords_array("GIS, spatial, raster, analysis"),
                    "vgi.doc_llm": GIS_DESCRIPTION,
                    "vgi.doc_md": "## GIS analysis\n\n" + GIS_DESCRIPTION + "\n\n### SQL workflow\n\n"
                    "Pass query results to the main schema functions, retaining IDs for joins. "
                    "Use bundled synthetic data to try the executable examples without network access. "
                    "CRS, coverage, inference limits and resource bounds are explicit function parameters. "
                    "The examples schema preserves the SDK regression recipes.",
                    "vgi.categories": json.dumps([c for c in SCHEMA_CATEGORIES if c["name"] == "gis"]),
                    "vgi.example_queries": json.dumps(_GIS_EXAMPLES),
                },
            ),
            Schema(
                path=["examples"],
                comment=SCHEMA_DOC_MD,
                functions=FUNCTIONS,
                tags={
                    "vgi.title": "Trajectory Functions",
                    "domain": "examples",
                    "vgi.keywords": keywords_array("greeting, sequence, generator, rest api, pagination"),
                    "vgi.doc_llm": SCHEMA_DOC_LLM,
                    "vgi.doc_md": SCHEMA_DOC_MD,
                    "vgi.categories": json.dumps([c for c in SCHEMA_CATEGORIES if c["name"] != "gis"]),
                    "vgi.example_queries": json.dumps(_ALL_EXAMPLES),
                },
            ),
        ],
    )

    secret_types = [API_SECRET_TYPE]


def main() -> None:
    """Console-script entry point: parse ``--http`` / ``--unix`` / logging flags and serve."""
    TrajectoryWorker.main()


if __name__ == "__main__":
    main()
