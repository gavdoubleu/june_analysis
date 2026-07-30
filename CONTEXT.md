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

**Located event table**:
A **Decoded event table** with a single **Geo unit** resolved per row
(`geo_unit_id`), obtained by joining *only* the `geo_unit_id` column from the
people/venue **Lookup table**s and coalescing venue-then-person. The light feed for
an **Aggregate** — it carries `time, geo_unit_id` and nothing else, so it costs a
fraction of an **Enriched event table** (which joins the whole people+venue
metadata). Produced by `load_geo_events` / `SimulationEvents.geo_events`. Sits
between the **Decoded** and **Enriched event table**s.

**Geo source**:
One of the two ways a **Located event table** resolves a **Geo unit** for an
event — the *venue* it occurred at, or the *person* involved — each read from
its **Lookup table**. Coalesced venue-then-person by priority. A source that
cannot supply a geo unit is skipped, not an error: either **Absent** or
**Malformed**.

**Absent source**:
A **Geo source** with nothing to join from — the event type lacks its id
column, or its **Lookup table** is missing. Expected (event types carry
different ids); skipped silently.

**Malformed source**:
A **Geo source** whose **Lookup table** exists but cannot yield a **Geo unit** —
it lacks `geo_unit_id` or its own id column. Signals partial/corrupt output;
skipped, not raised.

**Aggregate**:
A time-binned per-**Geo unit** summary of events — counts, or rate-per-100k once
population is known. Produced by `core/aggregate` from a **Located event table**,
keyed on `geo_unit_id`. The reusable intermediate every **Consumer** builds on;
exportable to CSV.

**Population**:
The resident count of a **Geo unit**, *subtree-aggregated* — a unit's population
is the sum over its whole subtree, so it is defined at every **geo level** (a
leaf's equals its direct residents; a parent's is the sum of its descendants').
Read from the **World file**; the denominator that turns an **Aggregate**'s
counts into rate-per-100k.

**Frame**:
One rendered image in an animation — and **exactly one Aggregate bin**. The
animator rasterises `counts[bin, :]` (or rate) into a **Density heatmap**; it
never re-bins. The config's `days_per_frame` *is* the Aggregate's `days_per_bin`,
one knob seen from two layers — there is no second binning step below the engine.
A **Trailing window** does not weaken this: it rewrites the **Aggregate** *above*
the engine, so a Frame is still exactly one row of whatever Aggregate it is
handed.
_Avoid_: treating `days_per_frame` and `days_per_bin` as independent.

**Trailing window**:
A rewrite of an **Aggregate** in which each bin's value becomes the *mean per
bin* over the `window_days` ending at (and including) that bin — so a Frame reads
a 7-day average rather than one day's events. The window's **step** stays
`days_per_bin`, so consecutive bins overlap; `window_days` records the coverage
and must be a whole multiple of `days_per_bin`. Bins whose window is incomplete
(the first few) are **dropped**, not partially averaged — a smaller divisor is a
different statistic, and would read as a spurious onset spike. Labelled by its
window-*end* date, the epidemiological "as of" convention.
_Avoid_: calling this "smoothing" — in this codebase that word means the
*spatial* Gaussian (`sigma`) of a **Density heatmap**, an independent knob.
_Avoid_: "rolling" — it does not distinguish trailing from centred.

**Density heatmap**:
How each **Frame** is drawn (ADR-0007): per-**Geo unit** scalars are rasterised
onto a UTM grid, Gaussian-smoothed (`sigma`), and shown as a continuous field —
not one mark per unit. Empty cells are transparent, so the **Basemap** shows
through and the colour scale stays global across all frames.
_Avoid_: reading heat as centroid crowding — see **Cell rate**.

**Cell rate**:
A heatmap cell's rate, re-derived as `cell_counts / cell_population × 1e5` from
counts and **Population** accumulated into *separate* grids. Being a ratio of
summed extensives, it is independent of how many centroids fall in the cell.
_Avoid_: summing per-unit rates into a cell — crowded cells would read hot from
density alone, the artefact this re-derivation exists to kill.

**Basemap**:
The shaded-relief tile a **Frame** sits on, fetched once per `(bbox, zone,
resolution)` and cached (ArcGIS World_Shaded_Relief, no key). A failed
*network/HTTP* fetch degrades to a blank background unless `require_basemap`
makes it a hard error; any other failure (malformed input, a bad decode)
always raises.

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
- **Auto-detection** discovers geo levels/hierarchy, disease states, bbox, UTM
  zone, population from the files. A **Preset** supplies only what cannot be
  inferred. Event types are *enumerated* for validation, but **which** one an
  animation renders is an editorial choice a Preset/config must state, not an
  inferred fact — one `event_type` per animation (a **Frame** draws one scalar).
