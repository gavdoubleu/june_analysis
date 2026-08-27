# 0005 — `aggregate_events` takes a pre-resolved `geo_unit_id`

Status: accepted

## Context

`aggregate_events` originally took an *Enriched event table* and resolved each
event's geo unit itself: it read `venue_geo_unit_id` / `person_geo_unit_id` and
coalesced them per a `geo_priority` argument (`_resolve_geo_unit`,
`_GEO_SOURCE_COLUMNS`). Two problems:

- **Only the heavy path could feed it.** Those prefixed geo columns exist only on
  the full *Enriched event table*, which joins the **entire** people lookup (plus
  every `people_properties` column) and the whole venues lookup — to recover one
  `geo_unit_id`. There was no cheap events→aggregate path, contradicting the
  extraction-library ethos.
- **A silent cross-seam leak.** `_GEO_SOURCE_COLUMNS` hardcoded `enrich`'s
  `venue_`/`person_` prefix convention. Change the prefix in `enrich/joins.py` and
  aggregate would find no geo column and drop **every** row — with no error and no
  test to catch it.

## Decision

Move geo resolution **behind the extraction seam**. A new `june_analysis`-owned
`load_geo_events` (surfaced as `SimulationEvents.geo_events`) joins only
`geo_unit_id` from the lookups and coalesces venue-then-person, returning a
**Located event table** (`time, geo_unit_id`). `aggregate_events` takes that frame
and keys straight on `geo_unit_id`; it no longer knows `geo_priority`, lookup
prefixes, or `_resolve_geo_unit`.

## Consequences

- Aggregate's interface shrank (deeper module): input is `time, geo_unit_id`,
  full stop. The prefix-leak failure mode is gone — aggregate references no
  enrich-produced column name.
- The venue/person **priority now lives in `load_geo_events`**, not aggregate.
  This is deliberate; do not move it back. Re-aggregating one frame under a
  different priority means re-extracting (cheap now), not re-binning.
- Placement is `core/load_data` (june_analysis-owned), not vendored `june_events`:
  the priority is an analysis choice, and vendored `june_events` divergence is
  kept minimal. `load_geo_events` composes the vendored `load_decoded_events` +
  `enrich_with_people/venues` over `geo_unit_id`-projected lookups, using the
  existing `include_properties=False` so no `people_properties` expansion is paid.
- Breaking signature change to `aggregate_events`; the only consumers are the
  in-repo example notebooks, updated in step.

## Amendment — coarsening a level is *not* resolution, and sits above the engine

Asking for a coarser **Geo level** looks like it belongs behind this same seam.
It does not. Resolution picks *which* geo unit an event belongs to (venue or
person) and needs the lookups; **Rollup** sums an already-resolved key up the
hierarchy, and the hierarchy arrives from the **World file** — which
`load_geo_events` deliberately does not read (ADR-0003).

So rollup is `rollup(aggregate, ancestor_by_geo_unit) -> Aggregate` in
`core/aggregate/rollup.py`, an Aggregate→Aggregate transform above the engine
exactly as `trailing_window.trailing_mean` is. This ADR's rule is unchanged:
`aggregate_events`'s input is still `time, geo_unit_id`, full stop.

Rolling up *before* binning (inside `load_geo_events`) was the alternative, and
is mathematically identical — counts sum exactly. It was rejected because it
would give the repo's cheapest, most events-only function a World dependency, and
changing level would mean re-extracting rather than re-summing a small dense
array. One extraction now serves every level.

- The `{geo_unit_id: ancestor_id}` map comes from a new
  `World.ancestor_by_geo_unit(level)` and crosses the seam as a **plain dict**,
  mirroring `aggregate.rate_per_100k(world.population_by_geo_unit())` —
  `core/aggregate` still imports nothing from `core/load_data/world` (ADR-0003).
  `World` owns level-name validation, since it owns the per-run registry.
- Rates need no special handling: **Population** is subtree-aggregated, so a
  rolled-up unit's denominator is already its own entry in the existing map.
- Resolution walks `unit.parent` until the level matches — no level ordering
  needed, and a ragged hierarchy is tolerated. A unit already at the requested
  level maps to **itself**; excluding it would empty the Aggregate when the
  native level is asked for.
- **A Rollup drops nothing.** Unplaceable units — the `-1` sentinel (meaningful
  in `core`, never collapsed here), an **Orphan unit**, or an id absent from the
  World file — keep their own column and are warned about, in the style of
  `rate_per_100k`'s geo-level-mismatch warning. Dropping them would make national
  totals silently wrong; one shared bucket would destroy a distinction `core`
  keeps deliberately. The price: a rolled Aggregate is **not guaranteed
  homogeneous in level**.
- **Level order comes from the registry, never from `GeographyManager.levels`.**
  `metadata/registries/geo_levels` is written coarse→fine (the serializer sorts
  unique levels by parent-chain depth), but `load_geography` recomputes its own
  `levels` list as first-seen over unit *file* order — sorted by unit id, no
  relation to depth. `World` retains the registry and exposes it as
  `geo_levels()`, so a bad level name is rejected against a list a reader can
  act on. Resolution itself treats "too coarse" and "orphan" identically — both
  are simply omitted from the map — since the parent walk never needs to know
  which of two levels is coarser. With no registry, `geo_levels()` falls back to
  the hierarchy's own first-seen list: the names are still right, only the
  ordering is meaningless — accepted. `geo_levels()`'s return type carries no
  signal of which case a caller got, so it never claims an order; a bad-level
  `ValueError` states "(coarsest first)" only when a registry backs it.
  `geo_levels_coarsest_first()` is the order-guaranteeing accessor: it raises
  rather than hand back a meaningless order where there is no registry.
- `Aggregate` gains **no** `geo_level` field: the caller asks for a level and so
  knows it, and an Aggregate never round-trips from disk (a CSV export is not a
  re-loadable Aggregate), so it cannot arrive detached from the call.
- `rollup` and `trailing_mean` commute (both linear); worth a test, not a
  constraint.

### Scope limit — rollup is not for maps

Rollup ships in `core` for tables, curves and cross-run comparison; the animator
does not expose it. Coarsening does not improve a map and generally harms one —
see ADR-0007's amendment.
