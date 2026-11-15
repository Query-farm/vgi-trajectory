-- Offline acceptance demos. Run with: uv run --with duckdb==2.0.0 python scripts/run_demo.py
-- The runner loads VGI, attaches this worker, and installs Spatial for geometry joins.

-- Sample GPS fixes on bundled synthetic data
SELECT entity_id, count(*) FROM trajectory.main.sample_fixes GROUP BY entity_id ORDER BY entity_id;

-- Trajectory visit and trip reconstruction on bundled synthetic data
SELECT entity_id, duration_s, fix_count FROM trajectory.main.episodes((SELECT * FROM trajectory.main.sample_fixes)) WHERE episode_type='visit' ORDER BY entity_id;

-- Join inferred visits to fleet records
WITH fleet(entity_id, vehicle) AS (VALUES ('crossing', 'Van 7'), ('stopped', 'Van 9')),
episodes AS (SELECT * FROM trajectory.main.episodes((SELECT * FROM trajectory.main.sample_fixes)))
SELECT f.vehicle, e.duration_s, e.fix_count, e.interpolated_boundaries
FROM episodes e JOIN fleet f USING(entity_id) WHERE e.episode_type='visit' ORDER BY f.vehicle;

