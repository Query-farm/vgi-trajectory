"""Reconstruct visits, trips, and observation gaps across all input Arrow batches."""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Any, ClassVar

import numpy as np
import pyarrow as pa
from pyproj import Transformer
from shapely import get_num_coordinates, transform
from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree
from vgi import Arg
from vgi.arguments import TableInput
from vgi.catalog import Table
from vgi.catalog.constraints import constraint_record
from vgi.invocation import BindResponse
from vgi.table_buffering_function import TableBufferingFunction, TableBufferingParams
from vgi.table_function import (
    BindParams,
    OutputCollector,
    ProcessParams,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc import ArrowSerializableDataclass

from .support import (
    example,
    finite_parameters,
    identifier,
    metadata,
    metric_crs,
    numeric,
    read_json,
    require_columns,
    schema_of,
)

GIS_DESCRIPTION = (
    "Reconstruct visits and trips from timestamped GPS rows, including geofence "
    "crossings between fixes. "
    "The worker buffers within an explicit point budget, sorts by entity and UTC time, "
    "intersects each "
    "piecewise-linear track with polygons, and emits visits, trips, and explicit "
    "observation gaps. "
    "Long gaps, implausible speeds and poor-accuracy fixes never create inferred visits. "
    "Durations and paths describe the linear interpolation model, not unobserved ground truth."
)
INPUT = schema_of(
    [
        ("entity_id", pa.string(), "Caller-owned vehicle or device identity."),
        ("observed_at", pa.timestamp("us"), "UTC GPS observation time; naive timestamps are interpreted as UTC."),
        ("x", pa.float64(), "Position X in input_crs."),
        ("y", pa.float64(), "Position Y in input_crs."),
    ]
)
RESULT = schema_of(
    [
        ("entity_id", pa.string(), "Input device/vehicle identity."),
        ("episode_id", pa.int64(), "Stable chronological episode number within an entity for the supplied query."),
        ("episode_type", pa.string(), "visit, trip, or gap. Overlapping fences produce independent visit rows."),
        ("fence_id", pa.string(), "Visited fence identity, or NULL for trips and gaps."),
        ("started_at", pa.timestamp("us"), "UTC episode start; inferred boundary time when a segment crosses a fence."),
        ("ended_at", pa.timestamp("us"), "UTC episode end; inferred boundary time when a segment exits a fence."),
        ("duration_s", pa.float64(), "Elapsed seconds under the piecewise-linear interpolation model."),
        (
            "distance_m",
            pa.float64(),
            "Length of reconstructed projected track in metres; NULL for unknown movement gaps.",
        ),
        (
            "fix_count",
            pa.int64(),
            "Number of observation timestamps inside this episode's time interval; may be zero "
            "for a between-fix visit.",
        ),
        (
            "interpolated_boundaries",
            pa.bool_(),
            "True if at least one episode boundary occurs between recorded GPS fixes.",
        ),
        (
            "left_censored",
            pa.bool_(),
            "True if the episode was already in progress at the start of available continuous observations.",
        ),
        (
            "right_censored",
            pa.bool_(),
            "True if the episode may continue past the end of available continuous observations.",
        ),
        ("status", pa.string(), "linear_interpolation, long_gap, implausible_speed, or poor_accuracy."),
        ("geometry_wkb", pa.binary(), "Reconstructed episode LineString WKB in analysis_crs; NULL for gaps."),
        ("analysis_crs", pa.string(), "Projected metre CRS used for lengths and reconstructed geometry."),
    ]
)


def utc_naive(value: Any) -> datetime:
    """Normalize datetime or ISO text to a naive UTC timestamp."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("observed_at must be a timestamp or ISO datetime")
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def read_fences(args: Any) -> tuple[list[str], list[Any], STRtree]:
    """Validate and project a local GeoJSON-shaped polygon collection."""
    data = read_json(args.fences, args.max_json_bytes)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("Fences must be a FeatureCollection")
    names, polygons = [], []
    seen: set[str] = set()
    vertices = 0
    if len(data.get("features", [])) > args.max_fences:
        raise ValueError("Fence collection exceeds max_fences")
    project = Transformer.from_crs(args.fence_crs, args.analysis_crs, always_xy=True)
    for feature in data.get("features", []):
        key = feature.get("id", (feature.get("properties") or {}).get("fence_id"))
        if key is None or str(key) in seen:
            raise ValueError("Every fence needs a unique id or properties.fence_id")
        key = identifier({"fence_id": key}, "fence_id")
        geom = shape(feature["geometry"])
        if geom.geom_type not in {"Polygon", "MultiPolygon"} or geom.is_empty or not geom.is_valid:
            raise ValueError("Fences must be valid nonempty polygons")
        geom = transform(geom, project.transform, interleaved=False)
        if not np.isfinite(geom.bounds).all():
            raise ValueError("Fence cannot be transformed into analysis_crs")
        if args.fence_buffer_m:
            geom = geom.buffer(args.fence_buffer_m)
        vertices += int(get_num_coordinates(geom))
        if vertices > args.max_fence_vertices:
            raise ValueError("Fence collection exceeds max_fence_vertices after buffering")
        seen.add(str(key))
        names.append(str(key))
        polygons.append(geom)
    if not names:
        raise ValueError("Fence collection cannot be empty")
    return names, polygons, STRtree(polygons)


def boundary_points(geom: Any) -> list[Any]:
    """Extract cut locations from point or overlapping boundary intersections."""
    if geom.is_empty:
        return []
    if hasattr(geom, "geoms"):
        return [point for part in geom.geoms for point in boundary_points(part)]
    if geom.geom_type == "Point":
        return [geom]
    if geom.geom_type in {"LineString", "LinearRing"}:
        return [Point(geom.coords[0]), Point(geom.coords[-1])]
    return []


def reconstruct(rows: list[dict[str, Any]], args: Any) -> list[dict[str, Any]]:
    """Reconstruct complete entities after global cross-batch sorting and deduplication."""
    if not rows:
        return []
    if len(rows) > args.max_points:
        raise ValueError("Trajectory input exceeds max_points")
    finite_parameters(args)
    metric_crs(args.analysis_crs)
    names, polygons, tree = read_fences(args)
    project = Transformer.from_crs(args.input_crs, args.analysis_crs, always_xy=True)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = identifier(row, "entity_id")
        x, y = numeric(row, "x", "y")
        x, y = project.transform(x, y)
        if not np.isfinite([x, y]).all():
            raise ValueError("GPS point cannot be transformed into analysis_crs")
        accuracy = row.get("accuracy_m")
        if accuracy is not None and (not math.isfinite(float(accuracy)) or float(accuracy) < 0):
            raise ValueError("accuracy_m must be finite and nonnegative when supplied")
        groups.setdefault(key, []).append(
            {
                "time": utc_naive(row["observed_at"]),
                "xy": (x, y),
                "poor": accuracy is not None and float(accuracy) > args.max_accuracy_m,
            }
        )
    output: list[dict[str, Any]] = []
    created_episodes = 0
    path_vertices = 0
    for entity, observations in sorted(groups.items()):
        points: list[dict[str, Any]] = []
        for point in sorted(observations, key=lambda p: p["time"]):
            if points and point["time"] == points[-1]["time"]:
                if point["xy"] != points[-1]["xy"]:
                    raise ValueError(f"Conflicting locations for {entity} at one timestamp")
                points[-1]["poor"] = points[-1]["poor"] or point["poor"]
            else:
                points.append(point)
        reasons: list[str | None] = []
        for a, b in pairwise(points):
            dt = (b["time"] - a["time"]).total_seconds()
            speed = math.dist(a["xy"], b["xy"]) / dt
            reasons.append(
                "poor_accuracy"
                if a["poor"] or b["poor"]
                else "long_gap"
                if dt > args.max_gap_s
                else "implausible_speed"
                if speed > args.max_speed_m_s
                else None
            )
        episodes: list[dict[str, Any]] = []
        active: dict[tuple[str, str | None, str], dict[str, Any]] = {}
        for i, (a, b) in enumerate(pairwise(points)):
            dt = (b["time"] - a["time"]).total_seconds()
            line = LineString([a["xy"], b["xy"]])
            chunks: list[tuple[float, float, str, str | None, str | None]]
            if reasons[i] is not None:
                chunks = [(0.0, 1.0, "gap", None, reasons[i])]
            else:
                candidates = [int(index) for index in tree.query(line)]
                fractions = {0.0, 1.0}
                if line.length:
                    for index in candidates:
                        fractions.update(
                            float(line.project(p, normalized=True))
                            for p in boundary_points(line.intersection(polygons[index].boundary))
                        )
                        if len(fractions) > args.max_segment_splits:
                            raise ValueError("Trajectory segment exceeds max_segment_splits")
                cuts = sorted(fractions)
                chunks = []
                for left, right in pairwise(cuts):
                    if right - left <= 1e-12:
                        continue
                    middle = line.interpolate((left + right) / 2, normalized=True) if line.length else Point(a["xy"])
                    labels = [names[int(index)] for index in tree.query(middle, predicate="covered_by")]
                    chunks.extend((left, right, "visit", label, "linear_interpolation") for label in labels)
                    if not labels:
                        chunks.append((left, right, "trip", None, "linear_interpolation"))
                    if len(chunks) > args.max_episodes:
                        raise ValueError("Trajectory segment exceeds max_episodes")
            for left, right, kind, fence, status in chunks:
                start, end = a["time"] + timedelta(seconds=dt * left), a["time"] + timedelta(seconds=dt * right)
                if end <= start:
                    continue
                start_xy = tuple(a["xy"][j] + left * (b["xy"][j] - a["xy"][j]) for j in (0, 1))
                end_xy = tuple(a["xy"][j] + right * (b["xy"][j] - a["xy"][j]) for j in (0, 1))
                segment_distance = None if kind == "gap" else line.length * (right - left)
                label_key = (kind, fence, str(status))
                old = active.get(label_key)
                interpolated = left > 1e-12 or right < 1 - 1e-12
                right_censored = right == 1 and (i == len(reasons) - 1 or reasons[i + 1] is not None)
                if old is not None and old["ended_at"] == start:
                    old["ended_at"] = end
                    old["duration_s"] = (end - old["started_at"]).total_seconds()
                    if segment_distance is not None:
                        old["distance_m"] += segment_distance
                    if kind != "gap":
                        path_vertices += 1
                        if path_vertices > args.max_path_vertices:
                            raise ValueError("Trajectory exceeds max_path_vertices")
                        old["_coords"].append(end_xy)
                    old["interpolated_boundaries"] = old["interpolated_boundaries"] or interpolated
                    old["right_censored"] = right_censored
                else:
                    created_episodes += 1
                    path_vertices += 0 if kind == "gap" else 2
                    if created_episodes > args.max_episodes:
                        raise ValueError("Trajectory exceeds max_episodes before dwell filtering")
                    if path_vertices > args.max_path_vertices:
                        raise ValueError("Trajectory exceeds max_path_vertices")
                    episode = {
                        "entity_id": entity,
                        "episode_id": 0,
                        "episode_type": kind,
                        "fence_id": fence,
                        "started_at": start,
                        "ended_at": end,
                        "duration_s": (end - start).total_seconds(),
                        "distance_m": segment_distance,
                        "fix_count": 0,
                        "interpolated_boundaries": interpolated,
                        "left_censored": left == 0 and (i == 0 or reasons[i - 1] is not None),
                        "right_censored": right_censored,
                        "status": status,
                        "geometry_wkb": None,
                        "analysis_crs": args.analysis_crs,
                        "_coords": [] if kind == "gap" else [start_xy, end_xy],
                    }
                    active[label_key] = episode
                    episodes.append(episode)
        ordered = sorted(episodes, key=lambda e: (e["started_at"], e["ended_at"], e["fence_id"] or ""))
        times = [p["time"] for p in points]
        episode_number = 0
        for episode in ordered:
            if episode["episode_type"] == "visit" and episode["duration_s"] < args.min_dwell_s:
                continue
            coords = episode.pop("_coords")
            episode["fix_count"] = bisect_right(times, episode["ended_at"]) - bisect_left(times, episode["started_at"])
            if episode["episode_type"] != "gap":
                episode["geometry_wkb"] = LineString(coords).wkb
            episode_number += 1
            episode["episode_id"] = episode_number
            output.append(episode)
    return output


@dataclass(slots=True, frozen=True, kw_only=True)
class EpisodeArgs:
    """Position input, geofences, and explicit inference limits."""

    data: Annotated[
        TableInput,
        Arg(
            0,
            doc=(
                "Rows with entity_id, observed_at, x and y; optional accuracy_m. Unsorted and "
                "interleaved entities are accepted."
            ),
        ),
    ]
    fences: Annotated[
        str,
        Arg(
            "fences",
            default="demo://fences.json",
            doc=(
                "Local FeatureCollection JSON path with unique feature id or properties.fence_id "
                "and Polygon/MultiPolygon geometry."
            ),
        ),
    ]
    input_crs: Annotated[
        str, Arg("input_crs", default="EPSG:32618", doc="CRS of GPS XY input coordinates; always XY axis order.")
    ]
    fence_crs: Annotated[
        str,
        Arg(
            "fence_crs",
            default="EPSG:32618",
            doc="Explicit CRS of fence coordinates; use EPSG:4326 for standard GeoJSON.",
        ),
    ]
    analysis_crs: Annotated[
        str,
        Arg(
            "analysis_crs",
            default="EPSG:32618",
            doc="Suitable local projected metre CRS for segment interpolation and distances.",
        ),
    ]
    max_gap_s: Annotated[
        float,
        Arg(
            "max_gap_s",
            default=900.0,
            gt=0,
            doc=("Maximum seconds between fixes permitting movement interpolation; longer intervals become gap rows."),
        ),
    ]
    max_speed_m_s: Annotated[
        float,
        Arg(
            "max_speed_m_s",
            default=80.0,
            gt=0,
            doc="Maximum plausible straight-line speed; faster intervals become gaps.",
        ),
    ]
    max_accuracy_m: Annotated[
        float,
        Arg(
            "max_accuracy_m",
            default=100.0,
            ge=0,
            doc="Optional accuracy_m values above this bound prevent interpolation through that fix.",
        ),
    ]
    min_dwell_s: Annotated[
        float,
        Arg(
            "min_dwell_s",
            default=0.0,
            ge=0,
            doc=("Exclude visit episodes shorter than this duration; trips are not merged across excluded visits."),
        ),
    ]
    fence_buffer_m: Annotated[
        float,
        Arg(
            "fence_buffer_m",
            default=0.0,
            ge=0,
            doc=(
                "Explicit outward polygon tolerance for GPS jitter, metres; changes the spatial definition of visits."
            ),
        ),
    ]
    max_points: Annotated[
        int,
        Arg(
            "max_points",
            default=1000000,
            ge=1,
            doc=(
                "Hard input-point budget before global sorting; partition large histories by entity"
                " and time with overlap."
            ),
        ),
    ]
    max_input_bytes: Annotated[
        int,
        Arg(
            "max_input_bytes",
            default=268435456,
            ge=1,
            doc="Maximum total Arrow bytes of used input columns before global reconstruction.",
        ),
    ]
    max_json_bytes: Annotated[
        int, Arg("max_json_bytes", default=16777216, ge=1024, doc="Maximum bytes in the geofence JSON file.")
    ]
    max_fences: Annotated[
        int, Arg("max_fences", default=10000, ge=1, doc="Maximum geofence polygons in the collection.")
    ]
    max_fence_vertices: Annotated[
        int,
        Arg(
            "max_fence_vertices",
            default=250000,
            ge=4,
            doc="Maximum total fence coordinates after projection and optional buffering.",
        ),
    ]
    max_segment_splits: Annotated[
        int,
        Arg(
            "max_segment_splits",
            default=10000,
            ge=2,
            doc="Maximum distinct boundary cut positions along one GPS segment.",
        ),
    ]
    max_episodes: Annotated[
        int,
        Arg(
            "max_episodes",
            default=1000000,
            ge=1,
            doc="Maximum reconstructed episodes, including visits later removed by min_dwell_s.",
        ),
    ]
    max_path_vertices: Annotated[
        int,
        Arg(
            "max_path_vertices",
            default=2000000,
            ge=2,
            doc="Maximum coordinates stored across reconstructed paths, including overlapping visits.",
        ),
    ]


@dataclass(kw_only=True)
class Drain(ArrowSerializableDataclass):
    """Last output-log row consumed by this finalize stream."""

    after_id: int = -1


EPISODE_SQL = (
    "SELECT entity_id, duration_s, fix_count FROM trajectory.main.episodes((SELECT * "
    "FROM trajectory.main.demo_input)) WHERE episode_type='visit' ORDER BY entity_id"
)

# Composed examples: episodes() output joined back to the demo_input fixes it was built from.
VISIT_LAST_FIX_SQL = (
    "SELECT v.entity_id, v.fence_id, v.started_at, f.observed_at AS last_fix_at, "
    "date_diff('second', f.observed_at, v.started_at) AS seconds_after_fix, v.fix_count "
    "FROM trajectory.main.episodes((SELECT * FROM trajectory.main.demo_input)) AS v "
    "ASOF JOIN trajectory.main.demo_input AS f "
    "ON v.entity_id = f.entity_id AND v.started_at >= f.observed_at "
    "WHERE v.episode_type = 'visit' ORDER BY v.entity_id, v.started_at"
)
VISIT_SHARE_SQL = (
    "WITH span AS (SELECT entity_id, date_diff('second', min(observed_at), max(observed_at)) AS observed_s "
    "FROM trajectory.main.demo_input GROUP BY entity_id), "
    "visits AS (SELECT entity_id, sum(duration_s) AS visit_s "
    "FROM trajectory.main.episodes((SELECT * FROM trajectory.main.demo_input)) "
    "WHERE episode_type = 'visit' GROUP BY entity_id) "
    "SELECT span.entity_id, span.observed_s, coalesce(visits.visit_s, 0) AS visit_s, "
    "round(coalesce(visits.visit_s, 0) / span.observed_s, 3) AS visit_share "
    "FROM span LEFT JOIN visits USING (entity_id) ORDER BY span.entity_id"
)


class Episodes(TableBufferingFunction[EpisodeArgs, Drain]):
    """Buffer across batches and workers before reconstructing complete tracks."""

    class Meta:
        """Trajectory contract and between-fix visit example."""

        name = "episodes"
        description = "Reconstruct visits, dwell, trips and gaps from timestamped GPS rows"
        tags = metadata(
            "Trajectory visit and trip reconstruction",
            GIS_DESCRIPTION
            + (
                " Identical duplicate fixes are collapsed; conflicting positions at one timestamp "
                "fail. Fence boundaries count as inside. A tangent with zero residence time does "
                "not produce a visit. Censored endpoints and interpolated boundaries are explicit. "
                "Input/output state uses invocation-scoped VGI storage, so entity histories survive"
                " multiple batches and parallel producers."
            ),
            RESULT,
            EPISODE_SQL,
            [["crossing", 60.0, 0], ["stopped", 600.0, 2]],
        )
        examples = [
            *example(EPISODE_SQL, "Recover a visit even though neither recorded fix is inside the fence"),
            *example(
                VISIT_LAST_FIX_SQL,
                "ASOF-join each reconstructed visit back to the last demo_input fix at or before its entry: "
                "the crossing entity entered the yard 30 seconds after its last fix and has zero fixes inside, "
                "while the stopped entity's visit starts at a recorded fix",
            ),
            *example(
                VISIT_SHARE_SQL,
                "Share of each entity's observed span (first to last demo_input fix) spent in fence visits: "
                "crossing spends 60 of 120 seconds in the yard (0.5), stopped all 600 seconds (1.0)",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[EpisodeArgs]) -> BindResponse:
        """Require entity identity, UTC time, and positions."""
        finite_parameters(params.args)
        require_columns(params.bind_call.input_schema, tuple(INPUT.names))
        return BindResponse(output_schema=RESULT)

    @classmethod
    def process(cls, batch: pa.RecordBatch, params: TableBufferingParams[EpisodeArgs]) -> bytes:
        """Store Arrow batches in invocation-scoped storage with a shared size limit."""
        used = [*INPUT.names, *(["accuracy_m"] if "accuracy_m" in batch.schema.names else [])]
        batch = batch.select(used)
        size = params.storage.counter_add(b"trajectory", b"input_bytes", batch.nbytes)
        if size > params.args.max_input_bytes:
            raise ValueError("Trajectory input exceeds max_input_bytes; partition the input history")
        count = params.storage.counter_add(b"trajectory", b"points", batch.num_rows)
        if count > params.args.max_points:
            raise ValueError("Trajectory input exceeds max_points; partition the input history")
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, batch.schema) as writer:
            writer.write_batch(batch)
        params.storage.state_append(b"trajectory_input", b"", sink.getvalue().to_pybytes())
        return params.execution_id

    @classmethod
    def combine(cls, state_ids: list[bytes], params: TableBufferingParams[EpisodeArgs]) -> list[bytes]:
        """Merge all input producers, reconstruct, and store bounded output batches."""
        rows = []
        after = -1
        while items := params.storage.state_log_scan(b"trajectory_input", b"", after_id=after, limit=16):
            for _, payload in items:
                rows.extend(pa.ipc.open_stream(payload).read_all().to_pylist())
            after = items[-1][0]
        result = reconstruct(rows, params.args)
        for offset in range(0, len(result), 4096):
            batch = pa.RecordBatch.from_pylist(result[offset : offset + 4096], schema=params.output_schema)
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, batch.schema) as writer:
                writer.write_batch(batch)
            params.storage.state_append(b"trajectory_result", b"", sink.getvalue().to_pybytes())
        return [params.execution_id]

    @classmethod
    def initial_finalize_state(cls, finalize_state_id: bytes, params: TableBufferingParams[EpisodeArgs]) -> Drain:
        """Start before the first stored output batch."""
        return Drain()

    @classmethod
    def finalize(
        cls, params: TableBufferingParams[EpisodeArgs], finalize_state_id: bytes, state: Drain, out: OutputCollector
    ) -> None:
        """Stream reconstructed output from invocation storage."""
        items = params.storage.state_log_scan(b"trajectory_result", b"", after_id=state.after_id, limit=1)
        if not items:
            out.finish()
            return
        state.after_id, payload = items[0]
        out.emit(pa.ipc.open_stream(payload).read_next_batch())


@dataclass(slots=True, frozen=True, kw_only=True)
class DemoArgs:
    """No arguments: use two known synthetic tracks."""


@dataclass(kw_only=True)
class Cursor(ArrowSerializableDataclass):
    """Whether the fixture has been sent."""

    done: bool = False


DEMO_SQL = "SELECT entity_id, count(*) FROM trajectory.main.demo_input GROUP BY entity_id ORDER BY entity_id"


@init_single_worker
@bind_fixed_schema
class DemoInput(TableFunctionGenerator[DemoArgs, Cursor]):
    """Return one between-fix crossing and one observed stationary visit."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = INPUT

    class Meta:
        """Synthetic trajectory metadata."""

        name = "demo_input"
        description = "Two synthetic GPS tracks demonstrating a between-fix crossing and a stop"
        tags = metadata(
            "Demo GPS fixes",
            "Four fixes in EPSG:32618 at UTC times. The crossing entity moves from 10 m west to"
            " 10 m east of a 20 m wide fence in 120 seconds; neither fix is inside. The stopped"
            " entity remains inside for 600 seconds. Use with the bundled fences.json.",
            INPUT,
            DEMO_SQL,
            [["crossing", 2], ["stopped", 2]],
        )
        examples = example(DEMO_SQL, "Count observations per synthetic entity")

    @classmethod
    def initial_state(cls, params: ProcessParams[DemoArgs]) -> Cursor:
        """Start before the fixture rows."""
        return Cursor()

    @classmethod
    def process(cls, params: ProcessParams[DemoArgs], state: Cursor, out: OutputCollector) -> None:
        """Emit both tracks once."""
        if state.done:
            out.finish()
            return
        base = datetime(2026, 1, 1)
        rows = [
            {"entity_id": entity, "observed_at": base + timedelta(seconds=seconds), "x": x, "y": 4100010.0}
            for entity, seconds, x in [
                ("crossing", 0, 499990.0),
                ("crossing", 120, 500030.0),
                ("stopped", 0, 500010.0),
                ("stopped", 600, 500010.0),
            ]
        ]
        out.emit(pa.RecordBatch.from_pylist(rows, schema=params.output_schema))
        state.done = True


GIS_FUNCTIONS: list[type[Any]] = [DemoInput, Episodes]

GIS_TABLES = [
    Table(
        name="demo_input",
        function=DemoInput,
        comment=DemoInput.Meta.description,
        constraints=(
            constraint_record(
                ["main"],
                "demo_input",
                "id_not_null",
                "NOT_NULL",
                [["entity_id"]],
                enforcement="ENFORCED",
                validation="ALL_ROWS",
            ),
            constraint_record(
                ["main"],
                "demo_input",
                "demo_pk",
                "PRIMARY_KEY",
                [["entity_id"], ["observed_at"]],
                enforcement="ENFORCED",
                validation="ALL_ROWS",
            ),
        ),
        tags={
            **DemoInput.Meta.tags,
            "domain": "geospatial",
            "vgi.example_queries": json.dumps(
                [{"description": ex.description, "sql": ex.sql} for ex in DemoInput.Meta.examples]
            ),
        },
        column_comments={f.name: (f.metadata or {}).get(b"comment", b"").decode() for f in DemoInput.FIXED_SCHEMA},
    )
]
