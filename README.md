# june_analysis

Render-agnostic analysis platform for the output of any JUNE2 simulation.
A shared `core/` (data load + aggregate) feeds many consumers — a map animator,
epidemic-curve plots, summary tables, notebooks. See [CONTEXT.md](CONTEXT.md) for
the domain glossary and [docs/adr/](docs/adr/) for architecture decisions.

## Layout

```
core/            libraries only — NO matplotlib/ffmpeg below this boundary
  load_data/
    june_events/ vendored reader of simulation_events.h5 (Events file)
    world/       wraps world_reader dep, reads world_state.h5 (World file)  [Phase 3]
  aggregate/     time-bin events -> per-geo counts / rate-per-100k          [Phase 2]
  animations_core/ reusable animation engine                               [Phase 4a]
animations/      APP: config-driven map animator                           [Phase 4b]
events_analysis/ APP: notebooks (epidemic curves, static map)              [Phase 2/5]
```

Core imports nothing from the app folders; apps import core.

## Install

Split requirements enforce the render-agnostic boundary — install only what a task
needs. Core alone never requires matplotlib/ffmpeg.

```bash
pip install -r requirements.txt                              # core: load + aggregate
pip install -r requirements.txt -r requirements-plotting.txt # + epidemic curves / static plots
pip install -r requirements-maps.txt                         # + projection + background fetch
pip install -r requirements-animation.txt                    # + mp4/gif video render
pip install -r requirements-aggregate.txt                    # optional numba JIT speed-up
```

`world_reader` (for `core/load_data/world`, i.e. maps + rate-per-100k) is an
installed dependency, not vendored — it is MAY-owned, so installing rather than
copying lets fixes flow downstream. It ships inside the MAY2 repo with a minimal
packaging shim; install it editable from there:

```bash
pip install -e /path/to/MAY2/may_world_visualiser   # exposes top-level world_reader
```

## Imports

No `pyproject.toml` yet. Run from the repo root with it on `PYTHONPATH`; import as
`core.load_data.june_events`, `core.aggregate`, etc.

## Tests

```bash
python -m pytest core            # from repo root
```
