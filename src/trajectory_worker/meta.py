"""Discovery metadata: the one file to edit when you rename or extend the worker.

DuckDB, coding agents and the ``vgi-lint`` metadata checker all read these
tags. Keep every object documented and ``make lint`` stays at 100.

* Catalog-level tags (title, license, author, links, long description) live in
  ``CATALOG_TAGS`` below.
* Every function and table carries ``object_tags(...)``: a title, a category
  from ``SCHEMA_CATEGORIES``, search keywords, and LLM- and human-facing docs.
"""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa

CATALOG_NAME = "trajectory"

SOURCE_URL = "https://github.com/Query-farm/vgi-trajectory"

# Categories group functions in docs and agent tools. Every object's
# ``vgi.category`` must name one of these.
SCHEMA_CATEGORIES = [
    {
        "name": "gis",
        "title": "GIS Analysis",
        "description": "Spatial analysis over query results and geospatial assets.",
    },
]


def keywords_array(keywords: str) -> str:
    """Turn ``"a, b, c"`` into the JSON array string ``vgi.keywords`` requires."""
    return json.dumps([k.strip() for k in keywords.split(",") if k.strip()])


def object_tags(*, title: str, category: str, keywords: str, doc_llm: str, doc_md: str) -> dict[str, str]:
    """Build the standard per-object discovery tags."""
    if category not in {c["name"] for c in SCHEMA_CATEGORIES}:
        raise ValueError(f"unknown category {category!r}; add it to SCHEMA_CATEGORIES")
    return {
        "vgi.title": title,
        "vgi.category": category,
        "vgi.keywords": keywords_array(keywords),
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
    }


def column(name: str, type_: pa.DataType, comment: str, *, nullable: bool = True) -> pa.Field[Any]:
    """Build an Arrow field whose ``comment`` shows up in DuckDB's ``DESCRIBE`` and agent tools."""
    return pa.field(name, type_, nullable=nullable, metadata={b"comment": comment.encode()})


CATALOG_DOC_LLM = (
    "Reconstruct visits, dwell, trips and observation gaps from timestamped GPS rows. "
    "`main.episodes((SELECT entity_id, observed_at, x, y FROM fixes), fences := ...)` buffers the "
    "input, sorts each entity by UTC time, intersects the piecewise-linear track with geofence "
    "polygons and returns visit, trip and gap episodes with inferred entry/exit times, dwell "
    "seconds, distance, fix counts, censoring flags and WKB paths. `main.sample_fixes` is a table "
    "of four synthetic fixes that works with the bundled default fence for offline examples. "
    "CRS, gap, speed, accuracy and resource limits are explicit named arguments."
)

CATALOG_DOC_MD = (
    "# VGI trajectory worker\n\n"
    "**Turn GPS fixes into geofence visits, trips and gaps from DuckDB SQL.** The "
    "[VGI](https://query.farm/vgi) worker interpolates straight segments between fixes, so it "
    "finds visits even when no recorded fix falls inside a fence, and it marks long gaps, "
    "implausible speeds and poor-accuracy fixes as unknown movement instead of inventing visits.\n\n"
    "The worker speaks Apache Arrow to DuckDB over stdin/stdout, a Unix socket, or HTTP, so the "
    "same code runs as a local subprocess or a hosted service. See the "
    "[VGI documentation](https://query.farm/vgi/docs/) to learn more."
)

AGENT_TEST_TASKS = [
    {
        "name": "gis_sample_fixes",
        "prompt": "Count observations per synthetic entity. Use the bundled synthetic inputs and "
        "return the columns and ordering shown in its catalog example.",
    },
    {
        "name": "gis_episodes",
        "prompt": "Recover a visit even though neither recorded fix is inside the fence. Use the "
        "bundled synthetic inputs and return the columns and ordering shown in its "
        "catalog example.",
    },
    {
        "name": "gis_gap_sensitivity",
        "prompt": "Using the trajectory worker's bundled sample GPS fixes and its default fences, which "
        "entities have a fence visit with the default settings but no fence visit when the maximum "
        "interpolation gap is tightened to 300 seconds? Return one VARCHAR column entity_id, ordered "
        "by entity_id.",
    },
    {
        "name": "gis_trip_distance_and_fixes",
        "prompt": "Using the trajectory worker's bundled sample GPS fixes and its default fences, report for "
        "every sample entity the total metres travelled in reconstructed trip episodes (0.0 when it has "
        "no trips) alongside how many GPS fixes it recorded. Return entity_id (VARCHAR), trip_m (DOUBLE) "
        "and fixes (BIGINT), ordered by entity_id.",
    },
]

CATALOG_TAGS = {
    "vgi.title": "VGI Trajectory Worker",
    "vgi.subtitle": "Reconstruct geofence visits, dwell, trips and gaps from GPS fixes.",
    "vgi.doc_llm": CATALOG_DOC_LLM,
    "vgi.doc_md": CATALOG_DOC_MD,
    "vgi.source_url": SOURCE_URL,
    "vgi.icon_url": "https://query.farm/media-kit/products/vgi/vgi-logo.png",
    "vgi.license": "0BSD",
    "vgi.author": "Query.Farm",
    "vgi.copyright": "Copyright 2026 Query.Farm LLC",
    "vgi.keywords": keywords_array(
        "vgi, duckdb, trajectory, gps, geofence, visits, dwell time, trips, gis, table function"
    ),
    "vgi.support_contact": f"{SOURCE_URL}/issues",
    "vgi.support_policy_url": f"{SOURCE_URL}#support",
    # Public analyst tasks for `vgi-lint simulate`; private graders live in vgi-agent-tests.yaml.
    "vgi.agent_test_tasks": json.dumps(AGENT_TEST_TASKS),
}
