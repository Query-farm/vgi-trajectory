# VGI Trajectory Worker examples

| Notebook | Question | One-parameter experiment |
|---|---|---|
| [01 · A visit with no fixes inside](01_visits_between_fixes.ipynb) | How much dwell can a linear model infer between GPS fixes? | Maximum interpolated gap 900 → 60 seconds |

Use the notebook's **Open in Colab** link and **Runtime → Run all**. The short
bootstrap installs only the shared base package and retrieves immutable,
SHA256-verified companions. For local execution install [uv](https://docs.astral.sh/uv/)
and Git, then run from `notebooks/`:

```sh
uv sync --locked
uv run --locked vgi-notebooks
uv run --locked vgi-notebooks 01_visits_between_fixes.ipynb --parameters '{"MAX_GAP_S":60.0}' --output-dir artifacts/gap-60
```

For Jupyter select `.venv/bin/python`. The locked `[runner]` extra is local tooling;
Colab installs the base package only. Overrides require a separate destination,
unknown parameters fail and failed execution cannot replace a successful default.
If an older setup replaced kernel libraries, use a fresh runtime.

## Portable release and shared presentation

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'trajectory' (TYPE vgi,
  LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-trajectory@v0.1.0 vgi-trajectory-worker');
```

The public v0.1.0 tag owns its worker dependencies in a separate Python 3.13
environment. The notebook lock does not lock that worker environment. The first
book also visibly installs and loads DuckDB Spatial. Initial Git, package,
extension and companion retrieval needs internet; the analyses themselves use
bounded synthetic inputs. No worker checkout, root virtual environment, real API
credential or external dataset is required. macOS arm64 was tested; other
platforms were not executed.

The [shared v0.3.27 standard](https://github.com/Query-farm/vgi-example-notebooks/blob/v0.3.27/docs/standard.md) provides catalog-derived title/subtitle, branding, isolated
SQL connection, SVG presentation and a protected runner. Keep `charts/` beside
saved notebooks for GitHub image links; interactive runs retain native SVG.
Review PNGs, logs, experiment copies and generated files stay ignored. Hosted
Colab was not manually operated; a fresh compatible kernel preloads eight common
libraries before executing the notebook's visible bootstrap.

`trajectory_example.py` only validates input parameters/fixture bytes and renders
results. Geometry and summaries remain visible SQL. Ordinary in-memory tables are
intentional: JupySQL cursors do not share cursor-local temporary tables or
registered DataFrame views. Final cleanup closes the SQL connection.

## Coverage

The notebook covers the worker's analysis function, `main.episodes`. Its four
synthetic GPS fixes are written inline as a SQL `VALUES` list. `coverage.json` and
`coverage/` retain the object mappings, raw catalog exports, signatures, metadata
provenance and hashed execution receipts reviewed against release v0.1.0; the
catalog exports are a snapshot of that release, which still carried the starter
template's `examples` schema and the `demo_input` table.

## GPS inputs, units and model limits

- An inline `VALUES` list supplies four synthetic fixes: crossing and
  stationary tracks starting **2026-01-01 00:00:00 UTC**, ending at 00:02:00 and
  00:10:00 UTC respectively. “Van 7” and “Van 9” are illustrative SQL labels.
- `fixtures/fences.json` is byte-identical to the released worker's bundled yard
  polygon. It deliberately uses projected coordinates, unlike ordinary geographic
  GeoJSON. Input, fence and analysis CRS are explicitly **EPSG:32618**, WGS 84 /
  UTM zone 18N, XY order, metres. Map axes label their subtracted coordinate origin.
- The worker interpolates straight segments at constant progress. It does not
  map-match roads or establish unobserved ground truth. Speed remains limited to
  80 m/s, supplied accuracy to 100 m, minimum dwell to 0 s and fence buffer to 0 m.
  These fixes do not supply accuracy measurements.
- Durations are elapsed seconds. Fix counts include both endpoints; a boundary
  fix can belong to adjacent episodes. Summing them would not count unique fixes.
- Censored endpoints indicate incomplete observation of the beginning/end of a
  visit. A stationary model does not prove the vehicle remained there throughout.
  Gaps retain NULL distance, distinct from stationary movement's zero distance.
- Time-partition checks apply to this single fence without dwell filtering.
  Overlapping fences or filtering visits changes that accounting.

The default reconstructs a **60 s** yard visit with **zero recorded fixes inside**,
from 00:00:30 to 00:01:30 UTC, and two 30 s trips. The stationary track produces a
**600 s** modeled visit with both endpoints censored. At a 60 s gap limit, both
tracks become `long_gap`: **720 entity-seconds** of unknown movement and NULL
distances. Only intervals strictly greater than the limit become gaps; equality
remains eligible. SQL recomputes time partitions and Spatial path lengths. These
are internal-consistency checks, not evidence of the real route.
