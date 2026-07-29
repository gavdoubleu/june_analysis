"""Config-driven animator driver (Phase 4b Consumer).

A thin app over the Phase 4a engine: reads a ``--config`` YAML, composes the
already-built core (load located events -> aggregate -> load world ->
RenderConfig -> render), and writes one animation to ``animations/output/``.
Lives in ``animations/`` (a Consumer), imports nothing new into ``core/``.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

# Run as a bare script (`python animations/animate_epidemic_example.py`) the repo
# root is not on sys.path, so `import core` fails; put it there. A no-op under
# pytest / `python -m`, where the root is already importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.animations_core import RenderConfig

_INTERPOLATION = re.compile(r"\$\{([^}]+)\}")
_METRICS = ("rate_per_100k", "count")
_NO_GEOGRAPHY_ID = -1  # geo_unit_id sentinel: seed / foreign-travel, no geography


_VENUE_THEN_PERSON = ("venue", "person")
_PERSON_ONLY = ("person",)


def default_geo_priority(metric: str):
    """Which **Geo source** to attribute an event to, given the map's metric.

    ``rate_per_100k`` divides by a Geo unit's *resident* population, so its
    numerator must count *residents* too — attribute by **person**. Venue
    attribution counts whoever was at the venue, so a fair or market in a
    200-person unit accumulates infections from visitors across the world and
    reports rates of thousands of percent (observed: 119 infections per
    resident). Residence attribution caps the ratio at 1.0, as it must.

    ``count`` has no denominator, and "where did transmission happen" is the
    interesting signal, so it keeps **venue**-then-person. Override either
    default with ``aggregate.geo_priority`` in the config.
    """
    return _PERSON_ONLY if metric == "rate_per_100k" else _VENUE_THEN_PERSON


def resolve_geo_priority(aggregate_block: dict, metric: str):
    """Config's ``aggregate.geo_priority``, else the metric's default.

    Accepts a single source (``person``) or a priority list
    (``[venue, person]``), coalesced in order by ``geo_events``.
    """
    requested = aggregate_block.get("geo_priority")
    if requested is None:
        return default_geo_priority(metric)
    if isinstance(requested, str):
        requested = [requested]
    unknown = [source for source in requested if source not in _VENUE_THEN_PERSON]
    if unknown:
        raise ValueError(
            f"unknown geo_priority source(s) {unknown}; expected any of "
            f"{list(_VENUE_THEN_PERSON)}"
        )
    return tuple(requested)


def located_events_for_map(events, event_type, geo_priority=_VENUE_THEN_PERSON):
    """Located table for animation, with the ``-1`` geo sentinel map-resolved.

    In ``core`` a ``geo_unit_id`` of ``-1`` is *meaningful* — an infection seed
    or foreign-travel event with no home geography — so ``load_geo_events`` keeps
    it. A map cannot place ``-1``, so **for animation only** we fall back to the
    person's residence geo; any event still unplaceable becomes ``NaN`` (dropped
    by ``aggregate_events``). ``events`` is a :class:`SimulationEvents`.

    ``geo_priority`` picks the **Geo source**(s) — see :func:`default_geo_priority`.
    """
    import numpy as np

    located = events.geo_events(event_type, geo_priority=geo_priority)
    seed = located["geo_unit_id"] == _NO_GEOGRAPHY_ID
    # Person residence is the only fallback for a seed venue; pointless (and a
    # wasted load) when person is already the priority.
    if seed.any() and tuple(geo_priority) != _PERSON_ONLY:
        by_person = events.geo_events(event_type, geo_priority=_PERSON_ONLY)
        located.loc[seed, "geo_unit_id"] = by_person.loc[seed, "geo_unit_id"]
    located.loc[located["geo_unit_id"] == _NO_GEOGRAPHY_ID, "geo_unit_id"] = np.nan
    return located


_DEFAULT_CONFIG = Path(__file__).parent / "configs" / "config_default.yaml"


def parse_args(argv=None):
    """CLI: ``--config PATH`` only (decision 4). Defaults to the driver's
    ``configs/config_default.yaml``; roots and overrides live in the YAML."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="path to a config YAML (default: configs/config_default.yaml)",
    )
    return parser.parse_args(argv)


def load_config(path) -> dict:
    """Read a config YAML and resolve its ``${...}`` interpolations."""
    import yaml

    with open(path) as handle:
        raw = yaml.safe_load(handle) or {}
    return resolve_interpolations(raw)


def resolve_output_path(output_block: dict, event_type: str) -> str:
    """Assemble ``{root}/{name}.{format}`` for the single output (decision 6).

    ``name`` defaults to ``event_type``; ``format`` defaults to ``mp4`` (flip to
    ``gif`` and re-run for a second format — the driver never emits two per run).
    """
    root = output_block.get("root", "output")
    name = output_block.get("name") or event_type
    fmt = output_block.get("format", "mp4")
    return str(Path(root) / f"{name}.{fmt}")


def resolve_event_type(events, aggregate_block: dict) -> str:
    """The one event type to animate — required, never inferred (ADR-0008).

    geo/bbox/UTM/population are auto-detected downstream, but *which* event to
    animate is an editorial choice the config must state. Both an omitted
    ``event_type`` and one absent from the run raise a clear error listing the
    run's available types (``events`` is a :class:`SimulationEvents`).
    """
    available = [event.name for event in events.event_types()]
    requested = aggregate_block.get("event_type")
    if not requested:
        raise ValueError(
            "aggregate.event_type is required (never inferred); choose one of the "
            f"run's available types: {available}"
        )
    if requested not in available:
        raise ValueError(
            f"unknown event_type {requested!r}; available: {available}"
        )
    return requested


def render_config_from(render_block: dict | None) -> RenderConfig:
    """Build a :class:`RenderConfig` from a ``render:`` block.

    A Preset is a *partial* override: only the keys present are set, each over
    ``RenderConfig``'s own default (no file-to-file layering). An empty or absent
    block yields all defaults. ``start_date`` is coerced from an ISO string and
    ``metric`` is validated before the frozen config is built.
    """
    fields = dict(render_block or {})

    start_date = fields.get("start_date")
    if isinstance(start_date, str):
        fields["start_date"] = date.fromisoformat(start_date)

    metric = fields.get("metric")
    if metric is not None and metric not in _METRICS:
        raise ValueError(
            f"unknown metric {metric!r}; expected one of {list(_METRICS)}"
        )

    return RenderConfig(**fields)


def resolve_interpolations(raw: dict) -> dict:
    """Resolve ``${key}`` references against ``raw``'s top-level scalars.

    Generic interpolation (mirrors MAY's ``config.yaml``): any ``${key}`` in a
    string value is replaced by the top-level scalar ``key``. Supports the
    events/world-in-different-dirs case; absolute paths carry no ``${}`` and pass
    through untouched.
    """
    anchors = {
        key: value
        for key, value in raw.items()
        if isinstance(value, (str, int, float, bool))
    }

    def resolve_key(match):
        key = match.group(1)
        if key not in anchors:
            raise ValueError(
                f"unknown interpolation ${{{key}}}; define it as a top-level "
                f"scalar. Available: {sorted(anchors)}"
            )
        return str(anchors[key])

    def substitute(value):
        if isinstance(value, str):
            return _INTERPOLATION.sub(resolve_key, value)
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item) for item in value]
        return value

    return substitute(raw)


def run(config: dict) -> str:
    """Compose the engine from a resolved config and write one animation.

    Orchestration only — every step is a built, tested ``core`` seam: load the
    located events, aggregate, load the world, build the RenderConfig, then
    render one file. Returns the written path.
    """
    from core.aggregate.aggregate import aggregate_events
    from core.animations_core import animate
    from core.load_data.simulation_events import SimulationEvents
    from core.load_data.world.world import load_world

    inputs = config.get("inputs", {})
    aggregate_block = config.get("aggregate", {})
    output_block = config.get("output", {})

    events = SimulationEvents(inputs["events"])
    event_type = resolve_event_type(events, aggregate_block)

    # RenderConfig first: the metric decides how events are attributed to Geo
    # units, so it must be known before the Aggregate is built (a rate needs
    # resident-attributed events — see default_geo_priority).
    render_config = render_config_from(config.get("render"))
    geo_priority = resolve_geo_priority(aggregate_block, render_config.metric)
    located = located_events_for_map(events, event_type, geo_priority)

    aggregate = aggregate_events(
        located,
        event_type=event_type,
        days_per_bin=aggregate_block.get("days_per_frame", 1.0),
        time_start=aggregate_block.get("time_start"),
        time_end=aggregate_block.get("time_end"),
    )

    world = load_world(inputs["world"])

    output_path = resolve_output_path(output_block, event_type)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    animate(aggregate, world, render_config, output_path, output_block.get("format"))
    return output_path


def main(argv=None) -> None:
    """CLI entry: parse ``--config``, load it, render. Turns the expected
    config/data failures into a clean one-line message, not a raw traceback."""
    args = parse_args(argv)
    try:
        output_path = run(load_config(args.config))
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise SystemExit(f"error: {error}")
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
