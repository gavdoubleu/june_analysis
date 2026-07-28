# 0008 — Animator config is single-event-type; `event_type` is required, not inferred

Status: accepted

## Context

The Phase 4b driver (`animations/animate_epidemic_example.py`) reads a `--config`
YAML and composes the Phase 4a engine. Two config-contract questions had genuine
alternatives:

1. **How many event types per run?** The PRD sketched a plural `events:
   [infections, deaths]` (PRD line 166). But `aggregate_events(..., event_type=...)`
   is singular and a **Frame** draws *one* scalar per Geo unit (ADR-0006) — there
   is no multi-event render.
2. **Is the event type inferred?** geo/bbox/UTM/population *are* auto-detected in
   `prepare()`. Event types are enumerable too (`SimulationEvents.event_types()`),
   so a "guess the highest-count type" default was possible.
3. **How many output formats per run?** `RenderConfig.formats` defaults to
   `("mp4", "gif")`, suggesting the driver might emit both.

## Decision

- **One `event_type` per animation.** The config carries a single `event_type:`
  scalar → one `Aggregate` → one render. The PRD's plural `events:` is superseded.
- **`event_type` is required, never inferred.** Which event to animate is an
  *editorial* choice; an omitted or unknown `event_type` raises a clear error
  listing the run's available types (via `SimulationEvents.event_types()`), never
  a guess. Auto-detection covers geo/bbox/UTM/population only.
- **One format per run.** `output.format` (default `mp4`) drives a single
  `scene.save(path, fmt)`; to get mp4 *and* gif, run twice flipping the key. The
  driver never loops `RenderConfig.formats`.

## Rejected alternatives

- **Plural `events:` → one output per type** — a list-loop hides that each output
  is an independent single-scalar render; the caller can loop configs instead.
- **Guess the highest-count event type** — silently animates something the user
  did not choose; wrong for an editorial decision.
- **Emit mp4 + gif per run** — couples two encodes into one invocation for no
  gain over re-running with a different `format`.

## Consequences

- The config schema stays flat and honest: one run = one event type = one file.
- The driver reuses `SimulationEvents` for both event-type validation *and* the
  located-table load — no separate introspection call.
- A future multi-event or multi-format need is an additive Consumer-side loop over
  configs, not a change to this contract.
- **Map-only geo sentinel fallback.** `geo_unit_id == -1` is meaningful in `core`
  (an infection seed / foreign-travel event with no home geography), so
  `load_geo_events` keeps it. A map cannot place `-1`, so the driver alone
  (`located_events_for_map`) falls its events back to the person's residence geo,
  dropping any still unplaceable — a Consumer reinterpretation, never a `core`
  change.
