# 0002 — Core is render-agnostic

Status: accepted

## Context

The platform must serve many consumers — animator, epidemic curves, static maps,
summary tables, notebooks. The existing `june_animator` fused data access with
matplotlib/ffmpeg, so nothing could reuse its loading/aggregation without dragging
in the whole video stack. A person doing a static curve should not need ffmpeg
installed.

## Decision

No matplotlib / ffmpeg / cartopy **below the core boundary**. `core/`
(`load_data`, `aggregate`) holds libraries only; rendering lives in consumers
(`animations/`, `events_analysis/`) and in the animation *engine*
(`core/animations_core`), which is itself driven entirely by config + core data.

Enforced by:

- **Split requirements**: mandatory `requirements.txt` (h5py/pandas/numpy) +
  optional `requirements-{plotting,maps,animation,aggregate}.txt`. Each consumer
  pulls only what it needs.
- **Lazy imports**: heavy optional deps are imported *inside* the functions that
  use them, never at module top-level in `core`. A missing optional dep raises a
  clear "install requirements-X.txt" message, only when that path is exercised.

## Consequences

- `import core.load_data` / `core.aggregate` must succeed in a mandatory-deps-only
  environment — a standing test/invariant.
- Optional-dep code carries slightly more ceremony (import-inside-function + a
  helpful error).
- The animation engine sits *in* `core/` yet may use matplotlib — permitted
  because it is a library consumed by drivers and still keeps its heavy imports
  lazy; the boundary is about not forcing render deps on data/aggregate users.
- Shapes every module boundary and the events-only degraded path
  (see [0003](0003-events-only-degradation.md)).
