# 0006 — Animator renders a per-geo Aggregate, not per-person points

Status: accepted

## Context

`june_animator`, the reference tool, animates the epidemic as a **per-person
point cloud**: it scatters each individual at their own coordinate and fades them
over a visibility window (`anim_styles.get_visibility_window`), colouring points
by symptom state. The Phase 4a plan told us to borrow exactly that machinery.

But every seam built since (ADR-0005) deliberately discards per-person, per-event
coordinates: the *Located event table* is `time, geo_unit_id`, and `aggregate`
produces a dense `(n_bins, n_geo)` **count per Geo unit**. There is no
coordinate-per-event path, and reintroducing one would bypass `aggregate`
entirely and resurrect the person/venue coupling ADR-0005 removed.

## Decision

The animator renders **model (A): a per-Geo-unit choropleth/bubble map driven by
the dense `Aggregate`.** Each **Frame** draws one scalar per Geo unit —
rate-per-100k by default, `count` as a config opt-in — at that unit's coordinate
(`world.geo_unit_coords()` + `infer_missing_coordinates`), on a **global** colour
scale fixed across all frames. The engine consumes the `Aggregate` directly.

Explicitly dropped from the `june_animator` borrow:

- **per-person point cloud** — no coord-per-event path (this is model (B),
  rejected);
- **`get_visibility_window` fade** — a per-person concept with no per-Geo-unit
  meaning;
- **symptom-state colouring** — the map scalar encodes *magnitude*, not a state
  distribution; multiple event types belong as lines in the curve panel, not as
  per-geo colours.

## Consequences

- The engine stays a pure consumer of `core/aggregate` + `core/load_data/world`;
  no new extraction seam, no return of per-person coupling.
- Visual fidelity to `june_animator` is *not* a goal — the old fade/point look is
  gone by design. A future per-event render would be a new, additive path, not a
  regression to fix.
- `visual_settings/` reduces to a sequential ramp + global normalisation; symptom
  -state groupings are out of scope for the animator.
- **Rendering is at the native Geo level** the events resolve to (leaf). Rolling
  leaf counts up the world hierarchy to a coarser target level is a separate,
  deferred `core` slice (near `aggregate`/`world`), with its own tests and likely
  its own ADR — not part of the animator.
