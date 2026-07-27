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
  the priority is an analysis choice, and ADR-0001 keeps vendored divergence
  minimal. `load_geo_events` composes the vendored `load_decoded_events` +
  `enrich_with_people/venues` over `geo_unit_id`-projected lookups, using the
  existing `include_properties=False` so no `people_properties` expansion is paid.
- Breaking signature change to `aggregate_events`; the only consumers are the
  in-repo example notebooks, updated in step.
