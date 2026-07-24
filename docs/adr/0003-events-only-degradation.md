# 0003 — Events-only degradation

Status: accepted

## Context

A `world_state.h5` (**World file**) is not always available, but a
`simulation_events.h5` (**Events file**) always is. Much useful analysis —
epidemic curves, per-geo tables, symptom-state plots — needs only counts per
area over time, not coordinates.

## Decision

`core/aggregate` keys on `geo_unit_id`, which events already carry, so it runs
from the **Events file** alone with **no coordinates**. Coordinates (from the
**World file** via `core/load_data/world`) are pulled in only for maps/animation
and for rate-per-100k population normalisation.

When a map/animation path is asked for without a World file, fail with a clear,
actionable error — never a bare traceback.

## Consequences

- The core has a genuine non-map path; the first end-to-end build
  (`plot_infections.ipynb`) proves reuse without any rendering-of-geography.
- `core/aggregate` must not import or assume `core/load_data/world`.
- Two entry conditions to test: events-only (curves work) and events+world
  (maps work, rates available).
