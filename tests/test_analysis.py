import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import Polygon, box, mapping

from trajectory_worker.analysis import reconstruct


def args(**updates: Any) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            "fences": "demo://fences.json",
            "fence_crs": "EPSG:32618",
            "input_crs": "EPSG:32618",
            "analysis_crs": "EPSG:32618",
            "fence_buffer_m": 0.0,
            "max_accuracy_m": 100.0,
            "max_gap_s": 900.0,
            "max_speed_m_s": 80.0,
            "min_dwell_s": 0.0,
            "max_points": 1000000,
            "max_episodes": 1000000,
            "max_path_vertices": 2000000,
            "max_json_bytes": 16777216,
            "max_fences": 10000,
            "max_fence_vertices": 250000,
            "max_segment_splits": 10000,
            **updates,
        }
    )


def crossing(**updates: Any) -> Any:
    base = datetime(2026, 1, 1)
    return [
        {"entity_id": "car", "observed_at": base, "x": 499990.0, "y": 4100010.0, **updates},
        {"entity_id": "car", "observed_at": base + timedelta(seconds=120), "x": 500030.0, "y": 4100010.0, **updates},
    ]


def test_between_fix_visit_and_trip_partition() -> None:
    rows = reconstruct(crossing(), args())
    assert [r["episode_type"] for r in rows] == ["trip", "visit", "trip"]
    assert [r["duration_s"] for r in rows] == [30.0, 60.0, 30.0]
    assert sum(r["distance_m"] for r in rows) == 40.0
    assert rows[1]["fix_count"] == 0
    assert rows[1]["interpolated_boundaries"] is True
    assert not rows[1]["left_censored"]
    assert not rows[1]["right_censored"]


def test_long_gap_and_implausible_speed_do_not_invent_visits() -> None:
    for a, reason in [(args(max_gap_s=60), "long_gap"), (args(max_speed_m_s=0.1), "implausible_speed")]:
        rows = reconstruct(crossing(), a)
        assert len(rows) == 1
        assert rows[0]["episode_type"] == "gap"
        assert rows[0]["status"] == reason
        assert rows[0]["geometry_wkb"] is None
        assert rows[0]["distance_m"] is None


def test_poor_accuracy_and_short_dwell_filters() -> None:
    assert reconstruct(crossing(accuracy_m=200), args())[0]["status"] == "poor_accuracy"
    assert all(r["episode_type"] != "visit" for r in reconstruct(crossing(), args(min_dwell_s=61)))


def test_unsorted_duplicate_fixes_are_deterministic() -> None:
    points = crossing()
    assert reconstruct([points[1], points[0], points[1]], args()) == reconstruct(points, args())
    with pytest.raises(ValueError, match="Conflicting"):
        reconstruct([*points, {**points[0], "x": 500000}], args())


def test_stationary_visit_and_censored_endpoints() -> None:
    rows = reconstruct(crossing(x=500010), args())
    assert len(rows) == 1
    assert rows[0]["episode_type"] == "visit"
    assert rows[0]["duration_s"] == 120
    assert rows[0]["left_censored"] and rows[0]["right_censored"]
    assert rows[0]["distance_m"] == 0


def test_tangent_contact_empty_and_single_fix() -> None:
    points = crossing()
    points[0].update(x=499990, y=4100010)
    points[1].update(x=500010, y=4100030)
    assert not any(r["episode_type"] == "visit" for r in reconstruct(points, args()))
    assert reconstruct([], args()) == []
    assert reconstruct(points[:1], args()) == []


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"max_episodes": 2}, "max_episodes"),
        ({"max_path_vertices": 3}, "max_path_vertices"),
        ({"max_segment_splits": 2}, "max_segment_splits"),
        ({"max_fence_vertices": 4}, "max_fence_vertices"),
        ({"max_points": 1}, "max_points"),
        ({"max_json_bytes": 10}, "max_json_bytes"),
    ],
)
def test_resource_budgets_fail_explicitly(updates: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        reconstruct(crossing(), args(**updates))


def test_no_zero_duration_episodes_below_timestamp_resolution() -> None:
    points = crossing()
    points[1]["observed_at"] = points[0]["observed_at"] + timedelta(microseconds=1)
    rows = reconstruct(points, args(max_speed_m_s=1e9))
    assert all(row["duration_s"] > 0 for row in rows)


def test_overlapping_fences_keep_independent_visits(tmp_path: Path) -> None:
    path = tmp_path / "overlap.json"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "id": name, "properties": {}, "geometry": mapping(geom)}
                    for name, geom in [
                        ("A", box(500000, 4100000, 500020, 4100020)),
                        ("B", box(500010, 4100000, 500025, 4100020)),
                    ]
                ],
            }
        )
    )
    rows = reconstruct(crossing(), args(fences=str(path)))
    assert [(r["fence_id"], r["duration_s"]) for r in rows if r["episode_type"] == "visit"] == [
        ("A", 60.0),
        ("B", 45.0),
    ]
    assert sum(r["duration_s"] for r in rows if r["episode_type"] == "trip") == 45.0
    with pytest.raises(ValueError, match="max_fences"):
        reconstruct(crossing(), args(fences=str(path), max_fences=1))


def test_fence_holes_split_visits_without_merging_trips(tmp_path: Path) -> None:
    polygon = Polygon(
        box(500000, 4100000, 500020, 4100020).exterior.coords, [box(500005, 4100005, 500015, 4100015).exterior.coords]
    )
    path = tmp_path / "hole.json"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "hole", "properties": {}, "geometry": mapping(polygon)}],
            }
        )
    )
    rows = reconstruct(crossing(), args(fences=str(path)))
    assert [r["duration_s"] for r in rows if r["episode_type"] == "visit"] == [15.0, 15.0]
    assert [r["duration_s"] for r in rows if r["episode_type"] == "trip"] == [30.0, 30.0, 30.0]


def test_geojson_null_properties_and_bounded_fence_identity(tmp_path: Path) -> None:
    path = tmp_path / "fences.json"
    feature = {
        "type": "Feature",
        "id": "site",
        "properties": None,
        "geometry": mapping(box(500000, 4100000, 500020, 4100020)),
    }
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    rows = reconstruct(crossing(), args(fences=str(path)))
    assert [r["duration_s"] for r in rows if r["fence_id"] == "site"] == [60.0]
    feature["id"] = "x" * 4097
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    with pytest.raises(ValueError, match="identifier limit"):
        reconstruct(crossing(), args(fences=str(path)))


def test_catalog_links_and_composed_examples() -> None:
    from trajectory_worker.analysis import VISIT_LAST_FIX_SQL, VISIT_SHARE_SQL, Episodes
    from trajectory_worker.meta import SOURCE_URL
    from trajectory_worker.worker import TrajectoryWorker

    # The catalog must link to this worker's repository, not the starter template.
    assert SOURCE_URL == "https://github.com/Query-farm/vgi-trajectory"
    assert TrajectoryWorker.catalog.source_url == SOURCE_URL
    # Composed examples sit within the first five examples agents are shown for episodes.
    first_five = [entry["sql"] for entry in json.loads(Episodes.Meta.tags["vgi.example_queries"])[:5]]
    assert VISIT_LAST_FIX_SQL in first_five
    assert VISIT_SHARE_SQL in first_five
