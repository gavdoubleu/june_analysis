# june_analysis

Render-agnostic analysis platform for the output of *any* JUNE2 simulation.
A shared `core/` (data load + aggregate — no matplotlib/ffmpeg) feeds many
**Consumers**: the map animator, epidemic-curve plots, summary tables, notebooks.

This file is a **glossary only** — no implementation detail. It reuses the
`core/load_data/june_events` terms (Event type, Raw/Enriched event table, Lookup
table, Registry, Sentinel value, Introspection — see
[june_events/CONTEXT.md](core/load_data/june_events/CONTEXT.md)) and adds the
platform-level terms below.

## Language

**Events file**:
`simulation_events.h5` — the event log every JUNE2 run writes. The one required
input: on its own it supports epidemic curves, per-geo tables, symptom-state
plots. Read by `core/load_data/june_events`.

**SimulationEvents**:
The reader handle to one run's **Events file** — exposes its available **Event
type**s (with row counts) and loads them, decoded or enriched. Owns the light
details Consumers otherwise repeat (the `events/` prefix, path coercion). Bound to
one file; events-only — the World file is an input the run *consumes*, so it stays
outside this handle.

**World file**:
`world_state.h5` — geography, population, venues for a run. Optional. Read (via
the installed `world_reader` dependency) by `core/load_data/world`. Supplies the
coordinates the **Events file** lacks. Required for maps/animation; absent ⇒ the
map path errors clearly, the events-only path still works.

**Geo unit**:
An addressable geographic area in the world hierarchy (identified by
`geo_unit_id`), at some **geo level** (e.g. region → area → super-area). Events
carry a `geo_unit_id`, so aggregation keys on it **without needing coordinates** —
this is what makes the events-only path possible.

**Decoded event table**:
A single **Event type**'s rows with **Registry** codes resolved to labels (via
`decode_registry_column`) but *without* the **Lookup table** people/venue joins of
an **Enriched event table** — the light extraction path. Produced by
`load_decoded_events`; a **Consumer** bins/plots it with ordinary pandas.

**Aggregate**:
A time-binned per-**Geo unit** summary of events — counts, or rate-per-100k once
population is known. Produced by `core/aggregate`, keyed on `geo_unit_id`.
The reusable intermediate every **Consumer** builds on; exportable to CSV.

**Population**:
The resident count of a **Geo unit**, *subtree-aggregated* — a unit's population
is the sum over its whole subtree, so it is defined at every **geo level** (a
leaf's equals its direct residents; a parent's is the sum of its descendants').
Read from the **World file**; the denominator that turns an **Aggregate**'s
counts into rate-per-100k.

**Consumer**:
An application built on `core/` — a driver, notebook, or script that loads,
aggregates, and renders. Lives in an app folder (`animations/`,
`events_analysis/`), never in `core/`. `core/` imports nothing from a Consumer.

**Preset**:
A named cosmetic config (e.g. `config_plague.yaml`) overlaying non-inferable
choices — colour ramps, background image, title, fps — onto the auto-detected
generic defaults (`config_default.yaml`). Plague is a Preset, never the default.

## Relationships

- A **Consumer** loads an **Events file** (always) and optionally a **World
  file**, builds an **Aggregate**, then renders. Maps additionally require the
  World file's coordinates.
- **Auto-detection** discovers event types, geo levels/hierarchy, disease states,
  bbox, UTM zone, population from the files. A **Preset** supplies only what
  cannot be inferred.
