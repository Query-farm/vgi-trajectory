# Changelog

## 0.2.2 (2026-11-16)

- Bump vgi-python to 0.52.2.
- Requires Python 3.14 (CI, Docker image and tooling moved to 3.14).

## 0.2.1

- Docs link to upstream sources: the catalog `vgi.doc_md` gains a Sources and references section linking Shapely, pyproj/PROJ and the OGC Simple Feature Access standard (WKB) (VGI183).

## 0.2.0 (unreleased)

- Removed the starter template's demo schema (examples.greet/fetch_items/sequence_table),
  demo_input and the placeholder trajectory_api secret type. The worker now
  exposes only `main.episodes` and the `main.sample_fixes` table, and declares no
  secret types, so it no longer appears to need credentials.
- `main.demo_input` is renamed `main.sample_fixes` (same four synthetic fixes);
  catalog examples, agent tasks and the stock-DuckDB checks use the new name.
- Agent task `gis_demo_input` is renamed `gis_sample_fixes`; the starter's
  greeting, sequence and items-API tasks are gone.
- Removed the starter's mock REST API, SDK recipe examples (`examples/`) and the
  paginated-roster notebook; notebook 01 now writes its fixes as inline `VALUES`.
- The catalog comment is now a short plain-text description of what the worker covers; the detailed analysis notes remain in the catalog's `vgi.doc_md` and `vgi.doc_llm` documentation.

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
