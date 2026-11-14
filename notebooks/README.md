# VGI Trajectory Worker examples

| Notebook | Question | One-parameter experiment |
|---|---|---|
| [01 · A visit with no fixes inside](01_visits_between_fixes.ipynb) | How much dwell can a linear model infer between GPS fixes? | Maximum interpolated gap 900 → 60 seconds |
| [02 · Check a paged roster before drafting greetings](02_page_size_is_not_roster_completeness.ipynb) | Does complete pagination imply complete expected-identity coverage? | Requested page size 3 → 5 records |

Use each notebook's **Open in Colab** link and **Runtime → Run all**. The short
bootstrap installs only the shared base package and retrieves immutable,
SHA256-verified companions. For local execution install [uv](https://docs.astral.sh/uv/)
and Git, then run from `notebooks/`:

```sh
uv sync --locked
uv run --locked vgi-notebooks
uv run --locked vgi-notebooks 01_visits_between_fixes.ipynb --parameters '{"MAX_GAP_S":60.0}' --output-dir artifacts/gap-60
uv run --locked vgi-notebooks 02_page_size_is_not_roster_completeness.ipynb --parameters '{"PAGE_SIZE":5}' --output-dir artifacts/page-5
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
libraries before executing the second notebook's visible bootstrap. Both stories
use the same short worker launch and companion registry path.

`trajectory_example.py` only validates input parameters/fixture bytes and renders
results. `roster_fixture.py` defines the second story's explicit synthetic HTTP
input and records raw requests; it does not replace worker paging or compute
analytical results. Retrieval, reconciliation, geometry and summaries remain
visible SQL. Ordinary in-memory tables are intentional: JupySQL cursors do not
share cursor-local temporary tables or registered DataFrame views. Final cleanup
closes the SQL connection and the loopback service.

## Complete coverage and current source

Actual functions, tables, views, arguments and output-schema exports identify
**five public named surfaces**, all meaningfully covered across these stories:
`main.demo_input`, `main.episodes`, `examples.sequence_table`, `examples.fetch_items`
and `examples.greet`. The six function rows include two `greet` overloads; the
`demo_input` catalog table and same-named table function count once. The examples
schema remains in the denominator even though it is separate from GPS analysis.
No public object is omitted. Authentication behavior is not claimed as covered.

Release v0.1.0 resolves to the same public-main source revision reviewed here:
`9f08af596b2b059028bd51bb849237adb77d96c2`. The runtime inventory therefore supports
both released and current-source interfaces; notebooks execute the tagged launch.
`coverage.json` and `coverage/` retain reviewed object mappings, raw catalog
exports, full signatures, metadata provenance and hashed execution receipts.
Existing green [source CI](https://github.com/Query-farm/vgi-trajectory/actions/runs/43614815243)
is reused. Worker source and root dependencies are unchanged; no source rebuild,
repeated worker suite, deployment, image publication or new worker release is needed.

## GPS inputs, units and model limits

- `trajectory.main.demo_input` supplies four synthetic fixes: crossing and
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

## Paged input, missing identity and missing name

The second story covers the retained `examples` APIs with an explicitly synthetic
loopback service. It has eight records: IDs 1,2,3,4,5,7,8,9; ID 4 has a NULL name.
An independently authored expected roster is IDs 1..9, generated by
`sequence_table(9)`. This contiguous range is a fixture assumption, never a claim
about real identity schemes. Category and USD-price fields are schema examples,
not inputs to the roster decision.

The actual `fetch_items` implementation follows `next_page` and materializes the
complete response once. Page size 3 yields three requests (3+3+2 records); size 5
yields two (5+3). The source fingerprint and all nine expected identities remain
fixed. SQL identifies one absent record separately from one present unnamed
record. Both greeting overloads produce seven draft strings and preserve NULL
names. No messages are sent. Twelve SQL checks cover populations, joins, drafts
and the exact request trail; no `LIMIT` is used to imply a network bound.

Both notebooks start with an empty temporary SQL-secret directory and persistent
secrets disabled. The second also removes the worker's inherited
`TRAJECTORY_API_TOKEN` before launching it, restores that environment variable
without displaying it during cleanup, and rejects any request carrying an
Authorization header. Its audit records only a presence boolean, never a header
value. No saved credential is used. The fixture has a stable snapshot; another
API would need its own consistency guarantees, completeness contract and explicit
authentication setup. This notebook does not validate those live properties.
