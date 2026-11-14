"""Shared conventions vendored into this independently installable GIS worker."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from itertools import batched
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
from pyproj import CRS, Transformer
from shapely import from_wkb, transform
from vgi.metadata import FunctionExample

from .meta import CATALOG_NAME, column, object_tags


def resource(path: str) -> str:
    """Resolve bundled demo assets; ordinary paths and URLs pass through."""
    if path.startswith("demo://"):
        name = path.removeprefix("demo://")
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("Invalid demo asset name")
        candidate = Path(__file__).parent / "data" / name
        if not candidate.is_file():
            raise ValueError(f"Unknown demo asset: {name}")
        return str(candidate)
    return path


def metric_crs(value: Any) -> CRS:
    """Require projected horizontal coordinates in metres for metric algorithms."""
    crs = CRS.from_user_input(value)
    if not crs.is_projected or len(crs.axis_info) < 2:
        raise ValueError("A projected raster/analysis CRS in metres is required")
    if any(abs(axis.unit_conversion_factor - 1.0) > 1e-9 for axis in crs.axis_info[:2]):
        raise ValueError("Horizontal CRS units must be metres; reproject feet-based data first")
    return crs


def geometry(value: Any, source_crs: str, target_crs: Any, *, polygon: bool = True) -> Any:
    """Decode validated WKB and transform XY with explicit axis order."""
    if value is None:
        raise ValueError("Geometry cannot be NULL")
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("geometry_wkb must contain binary WKB")
    if len(value) > 16 * 1024 * 1024:
        raise ValueError("Geometry exceeds the 16 MiB WKB limit; partition the geometry")
    geom = from_wkb(bytes(value))
    if geom.is_empty or not geom.is_valid:
        raise ValueError("Geometry must be nonempty and valid")
    if polygon and geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Expected a Polygon or MultiPolygon")
    if CRS.from_user_input(source_crs) != CRS.from_user_input(target_crs):
        project = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        geom = transform(geom, project.transform, interleaved=False, include_z=bool(geom.has_z))
    if not np.isfinite(geom.bounds).all():
        raise ValueError("Geometry has nonfinite coordinates after CRS transformation")
    return geom


def require_columns(schema: pa.Schema | None, required: tuple[str, ...]) -> None:
    """Reject missing relational inputs at bind time."""
    missing = set(required) - set(schema.names if schema is not None else [])
    if missing:
        raise ValueError(f"Missing input columns: {', '.join(sorted(missing))}")


def identifier(row: dict[str, Any], key: str) -> str:
    """Preserve caller identity as text and reject NULL identifiers."""
    if row.get(key) is None:
        raise ValueError(f"{key} cannot be NULL")
    result = str(row[key])
    if len(result.encode("utf-8")) > 4096:
        raise ValueError(f"{key} exceeds the 4096-byte identifier limit")
    return result


def numeric(row: dict[str, Any], *keys: str) -> list[float]:
    """Validate finite numerical inputs before scientific computation."""
    try:
        result = [float(row[k]) for k in keys]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected numbers in {keys}") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"Expected finite numbers in {keys}")
    return result


def schema_of(fields: list[tuple[str, pa.DataType, str]]) -> pa.Schema:
    """Build an output schema with documented columns."""
    return pa.schema([column(name, kind, description) for name, kind, description in fields])


def sql_type(kind: pa.DataType) -> str:
    """Map the GIS workers' Arrow types to discoverable SQL type names."""
    if pa.types.is_boolean(kind):
        return "BOOLEAN"
    if pa.types.is_integer(kind):
        return "BIGINT"
    if pa.types.is_floating(kind):
        return "DOUBLE"
    if pa.types.is_binary(kind):
        return "BLOB"
    if pa.types.is_timestamp(kind):
        return "TIMESTAMP"
    return "VARCHAR"


def metadata(title: str, description: str, schema: pa.Schema, sql: str, expected: list[list[Any]]) -> dict[str, str]:
    """Publish complete GIS function docs and a deterministic SQL acceptance example."""
    return {
        **object_tags(
            title=title,
            category="gis",
            keywords=f"GIS, geospatial, {CATALOG_NAME}, analysis, Arrow, SQL",
            doc_llm=description,
            doc_md=f"## {title}\n\n{description}",
        ),
        "vgi.result_columns_schema": json.dumps(
            [
                {
                    "name": f.name,
                    "type": sql_type(f.type),
                    "description": (f.metadata or {}).get(b"comment", b"").decode(),
                }
                for f in schema
            ]
        ),
        "vgi.executable_examples": json.dumps(
            [{"description": title + " on bundled synthetic data", "sql": sql, "expected_result": expected}]
        ),
    }


def example(sql: str, title: str) -> list[FunctionExample]:
    """Return the SDK's discoverable example representation."""
    return [FunctionExample(sql=sql, description=title)]


def finite_parameters(args: Any) -> None:
    """Reject NaN and infinity in constant numerical controls before execution."""
    values = {f.name: getattr(args, f.name) for f in fields(args)} if is_dataclass(args) else vars(args)
    for name, value in values.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name} must be finite")


def read_json(path: str, max_bytes: int) -> Any:
    """Read a local JSON document without allocating an unbounded file."""
    with Path(resource(path)).open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"JSON document exceeds max_json_bytes={max_bytes}")
    return json.loads(payload)


def emit_rows(rows: Iterable[dict[str, Any]], schema: pa.Schema, out: Any) -> None:
    """Bound Arrow output batches even when one input produces many rows."""
    for group in batched(rows, 4096, strict=False):
        out.emit(pa.RecordBatch.from_pylist(list(group), schema=schema))
