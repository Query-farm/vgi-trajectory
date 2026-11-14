# Visits and trips between GPS fixes

Independent Python VGI worker: query geospatial analysis from SQL and join the resulting rows to your existing tables.

## Run it

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/Query-farm/vgi-trajectory
cd vgi-trajectory
uv sync --locked
make demo
make verify-stock
make check
```

`make demo` runs [demo.sql](demo.sql) in stock DuckDB 2.0.0. Demo datasets ship inside the wheel; no data credentials are required. The first run downloads dependencies and signed SQL extensions. `make verify-stock` asserts every expected result in [vgi-worker.json](vgi-worker.json), including empty inputs, joins and multiple batches.

## Analysis contract

`episodes((SELECT entity_id, observed_at, x, y FROM fixes), ...)` returns visit, trip and gap episodes, timestamps, dwell duration, distance, fix count, inferred-boundary flags, censored endpoints and WKB paths. Optional `accuracy_m` rejects uncertain segments. `demo_input` is a table of two synthetic tracks.

**Acceptance:** a vehicle with both fixes outside a fence visits it for 60 seconds; the visit contains zero recorded fixes. A stopped vehicle dwells 600 seconds. Tests reconstruct one 5,001-fix unsorted history across input batches and stream 7,503 episodes across output batches. SQL joins visits to fleet records.

Supply UTC timestamps (naive timestamps are interpreted as UTC), an explicit input CRS, a local GeoJSON FeatureCollection of fences, `fence_crs` and a suitable projected metre `analysis_crs`. Standard GeoJSON uses EPSG:4326; the bundled synthetic fence intentionally uses EPSG:32618. Fences need a unique feature id or properties.fence_id.

The worker buffers a bounded query globally, groups by entity, sorts by time, and deduplicates identical fixes. Conflicting locations at one timestamp fail. Straight segments are intersected with fence boundaries to infer entry and exit times. Overlapping fences generate independent visits and can double-count time across fences; trips cover intervals outside all fences. Boundary travel counts as inside, but zero-duration tangent contact is not a visit.

Defaults treat gaps over 900 seconds, speeds over 80 m/s or supplied accuracy worse than 100 m as unknown movement. Gap rows have NULL path/distance; no visits are invented across them. Missing accuracy means no accuracy bound was supplied. Observation endpoints are marked censored rather than asserted as exact arrivals/departures. Single fixes cannot define an interval and produce no episodes. `min_dwell_s` filters short visits without reallocating that time to trips. A fence buffer is a tolerance, not a statistical uncertainty model. Default input cap is 1 million fixes; this is linear interpolation, not road map matching.

## Use your data

After `uv sync`, attach the executable with its absolute path:

```sql
SET allow_extension_repositories = 'allowed';
CREATE EXTENSION REPOSITORY IF NOT EXISTS query_farm
  WITH PREFIX 'https://duckdb-extensions.query.farm';
INSTALL vgi FROM query_farm;
LOAD vgi FROM query_farm;
INSTALL spatial;
LOAD spatial;
ATTACH 'trajectory' (TYPE vgi,
  LOCATION '/absolute/path/to/vgi-trajectory/.venv/bin/vgi-trajectory-worker');
```

The following template expects your own source tables and paths:

```sql
SELECT entity_id, fence_id, started_at, ended_at, duration_s,
       fix_count, interpolated_boundaries, left_censored, right_censored
FROM trajectory.main.episodes((SELECT * FROM gps_fixes),
    fences := '/absolute/path/sites.geojson', input_crs := 'EPSG:4326',
    fence_crs := 'EPSG:4326', analysis_crs := 'EPSG:32618', max_gap_s := 300)
WHERE episode_type = 'visit'
ORDER BY entity_id, started_at;
```

Episodes keep the caller's `entity_id`, so you can join them back to the fixes they were built from. This query runs as-is on the bundled demo data: an ASOF join finds the last recorded fix at or before each visit's entry. The `crossing` entity entered the yard 30 seconds after its last fix and has no fixes inside; the `stopped` entity's visit starts at a recorded fix.

```sql
SELECT v.entity_id, v.fence_id, v.started_at, f.observed_at AS last_fix_at,
       date_diff('second', f.observed_at, v.started_at) AS seconds_after_fix, v.fix_count
FROM trajectory.main.episodes((SELECT * FROM trajectory.main.demo_input)) AS v
ASOF JOIN trajectory.main.demo_input AS f
  ON v.entity_id = f.entity_id AND v.started_at >= f.observed_at
WHERE v.episode_type = 'visit'
ORDER BY v.entity_id, v.started_at;
```

WKB is an ordinary SQL BLOB with an explicit companion CRS, not an automatically transformed geometry. Use `ST_AsWKB` on input and `ST_GeomFromWKB` on output when using Spatial. Coordinates always use X/Y order. Do not join different coordinate systems without transforming them. Input IDs are retained as VARCHAR for joins. Invalid input schemas, geometries, coordinates and exceeded resource limits fail explicitly.

## Verification and provenance

- Scientific fixtures and edge cases: [tests/test_analysis.py](tests/test_analysis.py).
- Real SQL across stdio, launch and HTTP: [test/sql/gis.test](test/sql/gis.test), run by `make check` alongside the preserved SDK regression suite.
- Stock DuckDB contract: the expected results in [vgi-worker.json](vgi-worker.json); `make verify-stock` writes its report to `validation/stock-duckdb.json` (local evidence, not committed).
- Worker language: Python, pinned locally to 3.13. SDK: `vgi-python 0.51.1` with the starter's `>=0.51.1,<0.52` compatibility bound retained.
- Starter: [Query-farm/vgi-starter-python](https://github.com/Query-farm/vgi-starter-python), commit `9cca9105474d6e0052b8e343c8ea21f3d1a7503c`, template 1.3.0.
- Stock engine: DuckDB 2.0.0, signed VGI extension `e75482339d` from `query_farm`. The starter integration runner is separately pinned to `haybarn-unittest 2.0.0rc11`; it is not the stock DuckDB check.

`make check` includes formatting, Ruff, strict mypy, docstring checks, unit tests, all three SQL transports, executed metadata examples and stock DuckDB assertions. `make lint-ai` is an optional agent evaluation and is not part of the completed checks. The `examples` schema preserves starter functions; GIS functions live in `main`. Tests use synthetic known-answer fixtures, not a claim of production accuracy on every dataset.

Run `make release-check` to build a wheel from the source archive and verify its installed SQL interface outside the checkout. `make verify-container` builds locked runtime dependencies and checks every stock SQL assertion through a non-root, read-only HTTP container. See [PRODUCTION.md](PRODUCTION.md) for deployment, capacity limits, release evidence and operational boundaries.

## Support

Report problems at [github.com/Query-farm/vgi-trajectory/issues](https://github.com/Query-farm/vgi-trajectory/issues). Keep reports tied to the input CRS, resource limits and reproducible SQL. See [LICENSE](LICENSE) for the starter's license and dependency licenses for their terms.
