# 0001 — Vendor `june_events`, depend on `world_reader`

Status: accepted

## Context

`core/load_data` needs two readers of two JUNE2 output files:

- `june_events` — reads `simulation_events.h5`. Lives in `JUNE2/analysis_tools`,
  pure-Python (h5py/pandas/numpy), **no packaging** (no setup/pyproject), and a
  copy is wanted local to JUNE2 for people who won't install this repo.
- `world_reader` — reads `world_state.h5`. Lives nested inside the MAY2 Flask app
  (`MAY2/may_world_visualiser/world_reader`), heavier, MAY-owned.

Two sibling readers, but their situations differ enough to warrant different
handling.

## Decision

- **Vendor `june_events`**: copy it wholecloth into
  `core/load_data/june_events`. On copy, rename its `inspect/` subpackage to
  `introspect/` (it shadowed stdlib `inspect` and forced awkward
  import-from-parent; CONTEXT already names the concept "Introspection"). Keep its
  own tests. A copy also remains in JUNE2.
- **Depend on `world_reader`**: install it as a normal dependency via a minimal
  upstream packaging shim added to MAY2 (not vendored) — so MAY stays the owner
  and fixes flow downstream.

## Consequences

- Two readers acquired two different ways — surprising at a glance, hence this ADR.
- `june_events` drift: the JUNE2 copy and the vendored copy can diverge; re-vendor
  deliberately when needed.
- `world_reader` requires the MAY2 shim to exist before `core/load_data/world`
  (Phase 3) can be built.
- The `introspect` rename means any external `june_events.inspect` import must be
  updated to `june_events.introspect`.
- `load_enriched.py` is now a deliberate divergence point from the JUNE2 copy: the
  `load_decoded_events` / `load_enriched_events` split lives only in the vendored
  copy. Re-vendor by **merging**, not overwriting, so the split is preserved.
