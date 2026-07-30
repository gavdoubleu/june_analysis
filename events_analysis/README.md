# Analysing a run without a map

Epidemic curves, per-area tables, anything that isn't an animation. This is the
**events-only** path: it needs `simulation_events.h5` and nothing else — no
World file, no coordinates ([ADR-0003](../docs/adr/0003-events-only-degradation.md)).
For maps and animation see [animations/README.md](../animations/README.md).

## 1. Install

```bash
pip install -r requirements.txt -r requirements-render.txt
```

Curves need matplotlib, which lives in the render group. You do **not** need
`world_reader` here — that is only for the World file, i.e. maps and
rate-per-100k.

## 2. Run the notebooks

```bash
jupyter lab events_analysis/example_scripts/
```

There is no `pyproject.toml` yet, so `import core` only works if the repo root
is on `sys.path`. Each notebook's first cell walks up from `Path.cwd()` until it
finds `core/` and inserts it — so the notebooks work from any working
directory, but your own scripts need the same three lines, or run them from the
repo root.

| Notebook | Shows |
|---|---|
| `plot_infections_facade.ipynb` | **Start here.** The whole path via the `SimulationEvents` facade |
| `plot_infections.ipynb` | The same result built from the low-level `june_events` calls |

Both produce the same two-panel figure — infections/day above, deaths and
hospital admissions below — then a per-geo `Aggregate`. Read the facade one
unless you are working *on* the reader rather than *with* it.

## 3. Point them at your run

Cell 2 of each notebook sets one parameter:

```python
events_path = repo_root.parent / "JUNE2" / "runs" / "run_full_england_modern" / "simulation_events.h5"
```

That default is a run on the author's machine, so it will not exist for you —
the cell prints `(exists: False)` rather than failing, so check that line before
running on. Two things to point it at:

```python
# a committed 824-infection fixture: tiny, always present, good for a first run
events_path = repo_root / "core/load_data/june_events/tests/fixtures/simulation_events_fixture.h5"

# or your own run
events_path = Path("/path/to/your/run/simulation_events.h5")
```

The fixture has the same structure as a real file (`infections`, `deaths`,
`hospital_admissions`, `symptom_changes`, …), just far fewer rows, so every cell
runs — the curves are simply jagged.

## 4. The three loading paths

`SimulationEvents` binds one run's Events file and offers three ways to read an
event type. They differ only in how much they join, so pick the cheapest that
answers your question — on a full-England run the difference is minutes and
gigabytes.

```python
from core.load_data import SimulationEvents

simulation = SimulationEvents(events_path)
[(event.name, event.n_rows) for event in simulation.event_types()]
```

| Call | Returns | Use for |
|---|---|---|
| `.events(type, columns=["time"])` | **Decoded event table** — registry codes resolved to labels, no joins | curves; anything needing only the event's own fields |
| `.geo_events(type)` | **Located event table** — `time, geo_unit_id` only | per-area work; the feed for an `Aggregate` |
| `.enriched(type)` | **Enriched event table** — full people + venue metadata joined | when you genuinely need age, sex, venue type … |

`columns=` is worth using: it names the *raw stored* fields, and the loader only
reads what you ask for.

## 5. From events to an Aggregate

An **Aggregate** is a time-binned per-geo-unit summary — the reusable
intermediate the animator also builds on, so a curve and a map are the same
object read two ways.

```python
from core.aggregate import aggregate_events, epidemic_curve, to_long_dataframe

located = simulation.geo_events("infections")          # time, geo_unit_id
aggregate = aggregate_events(located, event_type="infections", days_per_bin=1.0)

epidemic_curve(aggregate)      # bin_start, count — summed over all geo units
to_long_dataframe(aggregate)   # bin_start, geo_unit_id, event_type, count — tidy, CSV-ready
```

`to_long_dataframe(aggregate).to_csv("infections_by_area.csv")` is usually the
fastest route to a table for someone else.

Two things that surprise people:

- **`geo_unit_id == -1` is meaningful, not missing.** It is an infection seed or
  a foreign-travel event — a real event with no home geography. The events-only
  path keeps it (it is a genuine count); only the animator drops it, because a
  map cannot place it. Filter it yourself if a per-area table shouldn't carry it.
- **A trailing average is a separate step.**
  `core.aggregate.trailing_window.trailing_mean(aggregate, window_days=7.0)`
  rewrites an Aggregate into 7-day means. Not exported from `core.aggregate`'s
  top level; see §6 of [animations/README.md](../animations/README.md) for what
  it does to the first few bins.

## 6. Rate per 100k

Needs population, which lives in the **World file** — so this one step leaves the
events-only path and does need `world_reader` installed (see
[animations/README.md](../animations/README.md) §1). Without it you get counts,
which is what most curves want anyway.

## Troubleshooting

**`ModuleNotFoundError: core`** — the repo root isn't on `sys.path`. Re-run cell
2, or start Jupyter from the repo root.

**`(exists: False)` printed by cell 2** — the default `events_path` is the
author's; see §3.

**`KeyError: unknown event type ...`** — the error lists what the run *does*
have. Runs differ; not every file records every type.
