# Changelog

## 0.1.0 (2026-11-14)

First release.

- `episodes(...)` table function: turns GPS fixes into visit, trip and gap
  episodes with geofence entry/exit interpolation, dwell, distance, fix counts,
  censoring flags and WKB paths; `demo_input` table of two synthetic tracks.
- Composed examples: ASOF-join visits back to the last fix before entry, and
  each entity's visit share of its observed span.
- Agent tasks `gis_gap_sensitivity` and `gis_trip_distance_and_fixes`.
- Initial worker generated from the VGI starter template (1.3.0).

Targets: vgi-python 0.51 · VGI protocol 3.3 · Haybarn 2.0.0rc11 · vgi-lint-check 2.x (unpinned)
