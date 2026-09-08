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
- `core/aggregate` must not import or assume `core/load_data/world`; population
  is passed *into* `rate_per_100k` as a `{geo_unit_id: population}` map.
- "Clear error" applies to a *wholly-absent* World file (`load_world` raises).
  A *per-unit* population gap is milder: `rate_per_100k` gives that unit a NaN
  column and logs a warning, so partial-population real data still yields rates
  without masking a genuine geo-level mismatch.
- Two entry conditions to test: events-only (curves work) and events+world
  (maps work, rates available).

## Amendment — this is one of three sites writing `counts / population * 100_000`

`Aggregate.rate_per_100k`'s NaN-and-warn policy above is one of three places the
rate arithmetic is written, each for a different consumer with a deliberately
different gap policy — no accident, but previously undiscoverable from any one
site without a repo-wide search:

1. **`Aggregate.rate_per_100k`** (here, table path): NaN column + warning for a
   geo unit absent from the population map, or with population 0.
2. **`build_animation.render._require_populations`** (ADR-0007, map path): a
   geo unit that carries events but has no population is a hard `ValueError` —
   a NaN would render transparent and silently drop located events, which the
   table path's milder policy can tolerate but a map cannot.
3. **`build_animation.raster.cell_rate_grid`** (ADR-0007): per heatmap *cell*,
   not per geo unit, and not really the same divergence as (1) vs (2). A
   zero-population cell there is, in normal operation, the *empty* cell — no
   centroid in it — meant to render transparent; the genuinely-missing-
   population case is intercepted by (2) before this function ever runs.

All three are settled policy and cross-reference each other in their
docstrings; none should be unified as a "cleanup".
