# 0007 — Density-heatmap render model with per-cell re-derived rate

Status: accepted

## Context

ADR-0006 settled *what* the animator draws: a scalar per **Geo unit** from the
dense `Aggregate`, on a global colour scale. It left *how* to draw it open. Two
render models remained:

- **Discrete marks** — one bubble/patch per Geo unit at its coordinate. Legible
  for tens of units; at JUNE2's thousands of leaf units it degenerates into
  overlapping dots, and dense metropolitan areas read as solid blobs whose
  darkness is *centroid crowding*, not epidemic intensity.
- **Density heatmap** — rasterise the per-unit scalars onto a metric grid,
  Gaussian-smooth, and `imshow`. Reads as a continuous field, scales to thousands
  of units, and lets a basemap show through the transparent low end.

A naive heatmap has a trap. If each unit's *rate* is splatted onto the grid and
cells sum their contributions, a cell covering many crowded centroids sums many
rates and reads hot purely from centroid density — the same artefact discrete
marks suffer, reintroduced through the back door.

Separately, ADR-0006's "draw at `world.geo_unit_coords()` +
`infer_missing_coordinates`" left the *uncoordinated-unit* case unspecified: what
happens to a unit that carries events but has no coordinate even after inference?

## Decision

**Render each Frame as a smoothed density heatmap on a UTM grid, with the cell
rate re-derived from separately-accumulated counts and population.**

1. **Project once.** Centroids go to UTM metres (zone/EPSG from the coordinate
   medians). The map axis is a cartopy `GeoAxes`; its projection defaults to that
   UTM but is pluggable, so a Frame can be rendered onto a non-UTM basemap's
   native projection (the UTM-metre layers carry `transform=data_crs`).
2. **Accumulate counts and population into *separate* grids**, then divide:
   `cell_rate = cell_counts / cell_population × 1e5`. Rate is a ratio of summed
   extensives, so crowding cancels — ten crowded low-rate units read low, not
   hot. Summing per-unit rates is the rejected mistake above. (`count` metric
   accumulates counts only; empty cells are NaN, not a solid floor of zeros.)
3. **Empty cells are NaN** — transparent through the alpha ramp, excluded from
   the global `vmin/vmax`, and NaN-safe under Gaussian smoothing (absence does
   not bleed into neighbours).
4. **Uncoordinated units are a hard error.** A unit carrying events with no
   coordinate after inference raises, rather than being skipped.

## Consequences

- The engine layers as `projection → raster → ramp → prepare (data) → Scene
  (render) → writers`: `prepare()` returns render-free `Prepared` data, `Scene`
  owns all matplotlib/cartopy, and `writers` is a one-way sink fed a heavy-dep-
  free `AnimationSource` (`Scene → writers → ∅`). Every layer is render-free at
  import (matplotlib/cartopy/pyproj/pillow/scipy lazy-imported — ADR-0002).
- **Rate is density-independent by construction**, the property discrete marks
  and naive splatting both lack. `grid_resolution` and `sigma` (config) trade
  spatial detail against smoothness; both are cosmetic, not correctness.
- The hard error on uncoordinated units **deliberately diverges** from the
  **Geo source** policy of skipping `Absent`/`Malformed` rows (see
  `core/load_data/geo_events`). There, a skipped row is one unlocated event among
  many; here, a skipped *unit* would silently erase every event it carries from
  the map — a misleading picture, not a lossy one. Rendering fails loudly so the
  caller fixes the World file or excludes the unit upstream, consciously.
- A Frame is no longer "one mark per unit at its coordinate" but "one rasterised
  field per bin"; the **Frame** glossary entry is updated to match. Frame ≡
  Aggregate bin is unchanged.
- Basemaps are fetched once per `(bbox, zone, resolution, style)` and cached; a failed
  fetch degrades to a blank background unless `require_basemap` forces the error.
- `RenderConfig.cache_dir = None` resolves to a repo-local default
  (`core/animations_core/.cache/basemaps`, anchored via `__file__` so it doesn't
  depend on the caller's working directory) rather than disabling the cache.
  There is deliberately no way to fully turn caching off — nothing needs it, and
  a `None`-means-disabled reading contradicted the module's own docstring.

## Amendment — a coarser Geo level does not fix a map, it degrades one

A recurring suggestion is that national-scale maps need events rolled up to a
coarser **Geo level** first, on the assumption that thousands of fine units are
what makes them slow and illegible. This ADR already answers that: rasterising to
a grid is what scales to thousands of units, and re-deriving **Cell rate** from
separately-summed extensives is what stops crowding reading as intensity. The
unit count is not the problem.

Coarsening before rendering makes the picture worse. Each unit's scalar is
splatted at its **centroid**, so a rolled-up unit puts a whole region's counts
*and* population on one grid point. The field collapses to a handful of Gaussian
blobs centred on points that are frequently uninhabited, with NaN between them.
**Cell rate** stays arithmetically valid — it is still a ratio of summed
extensives — but the spatial resolution the grid exists to provide has been
discarded before rasterisation ever runs. Nor is it a speed win: splatting a few
thousand centroids is negligible beside grid × frame work.

So **Rollup** (see ADR-0005's amendment) lives in `core` for tables, curves and
cross-run comparison, and the animator does not expose a level knob. Should a
genuine map need for one appear, it costs a single config key — but it must be
justified by that need, not by unit count. If national maps prove unsatisfactory,
look first at extent, `grid_resolution`, `sigma` and basemap resolution, which
are the knobs that actually govern how the field reads.
