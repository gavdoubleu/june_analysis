"""The animator config's owning module (Phase 4b Consumer).

The `--config` YAML is the platform's user-facing interface: an analyst edits
it and re-runs. It carries four blocks — `inputs:`, `aggregate:`, `render:`,
`output:` — plus top-level scalars used as `${}` interpolation anchors. Before
this module, knowledge of the schema (key names, defaults, coercions,
validity) was spread across `animate_epidemic_example.py`, `build_pipeline.py`
and `core`'s `RenderConfig`, with two defaults that could silently disagree
and no rejection of a typo'd key. This module is the single place that reads
a raw config dict and returns a fully-typed, validated `AnimatorConfig`.

`render:`'s schema stays owned by `core.animations_core.RenderConfig` — the
engine's cosmetic knobs are core's public surface (ADR-0002/0008) — but this
module wraps its construction so a `render:` typo raises the same clean
`ValueError` as every other block, instead of a raw `TypeError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.animations_core import RenderConfig

_INTERPOLATION = re.compile(r"\$\{([^}]+)\}")

_METRICS = ("rate_per_100k", "count")
_VENUE_THEN_PERSON = ("venue", "person")
_PERSON_ONLY = ("person",)

_UNEXPECTED_KWARG = re.compile(r"unexpected keyword argument '(\w+)'")


@dataclass(frozen=True)
class InputsConfig:
    """`inputs:` — paths to the run's Events/World files. Existence is checked
    by the driver (I/O), deliberately not here (construction stays pure)."""

    events: str | None = None
    world: str | None = None


@dataclass(frozen=True)
class AggregateConfig:
    """`aggregate:` — how events are located, binned and windowed.

    `event_type`'s requiredness is deliberately *not* checked here: the full
    ADR-0008 error ("required, never inferred; available: [...]") needs the
    run's live event list, which isn't open yet at config-parse time — that
    check stays `build_pipeline.resolve_event_type`'s job.

    `geo_priority` arrives here already resolved to a source tuple (see
    `load_animator_config`), not the raw config value — it only depends on
    `render.metric`, which is known before this block is even read.
    """

    event_type: str | None = None
    days_per_frame: float = 1.0
    window_days: float | None = None
    time_start: float | None = None
    time_end: float | None = None
    geo_priority: tuple[str, ...] = _VENUE_THEN_PERSON

    def __post_init__(self) -> None:
        object.__setattr__(self, "days_per_frame", float(self.days_per_frame))
        if self.window_days is not None:
            object.__setattr__(self, "window_days", float(self.window_days))
        if self.time_start is not None:
            object.__setattr__(self, "time_start", float(self.time_start))
        if self.time_end is not None:
            object.__setattr__(self, "time_end", float(self.time_end))

        if self.window_days is None:
            return
        window_bins = self.window_days / self.days_per_frame
        if not _isclose_to_int(window_bins):
            raise ValueError(
                f"aggregate.window_days {self.window_days:g} is not a whole "
                f"multiple of aggregate.days_per_frame {self.days_per_frame:g}"
            )


@dataclass(frozen=True)
class OutputConfig:
    """`output:` — where the one rendered animation is written."""

    root: str = "output"
    name: str | None = None
    format: str = "mp4"


@dataclass(frozen=True)
class AnimatorConfig:
    """The whole `--config` YAML, typed and validated."""

    inputs: InputsConfig
    aggregate: AggregateConfig
    render: RenderConfig
    output: OutputConfig

    @property
    def resolved_output_path(self) -> str:
        """``{output.root}/{name}.{format}`` (decision 6, ADR-0008).

        ``name`` defaults to the config's own ``aggregate.event_type``; needs
        no parameter, unlike the old ``resolve_output_path``, since both
        blocks live on the same config.
        """
        name = self.output.name or self.aggregate.event_type
        return str(Path(self.output.root) / f"{name}.{self.output.format}")


def _isclose_to_int(value: float) -> bool:
    return abs(value - round(value)) < 1e-9


def _construct(cls, block: dict | None, block_name: str):
    """``cls(**block)``, turning an unknown-key ``TypeError`` into a clean
    ``ValueError`` naming the block and the offending key — the uniform fix
    for a silently-ignored `aggregate:` typo and a raw-traceback `render:`
    typo alike."""
    block = dict(block or {})
    try:
        return cls(**block)
    except TypeError as error:
        match = _UNEXPECTED_KWARG.search(str(error))
        if match:
            raise ValueError(
                f"unknown key {match.group(1)!r} in {block_name}: {error}"
            ) from error
        raise ValueError(f"invalid {block_name}: {error}") from error


def _render_config_from(render_block: dict | None) -> RenderConfig:
    """Build a :class:`RenderConfig` from a ``render:`` block.

    A Preset is a *partial* override: only the keys present are set, each over
    ``RenderConfig``'s own default (no file-to-file layering). ``start_date``
    is coerced from an ISO string and ``metric`` is validated before the
    frozen config is built (and before an unknown key is caught by
    :func:`_construct`, so a typo and a bad ``metric`` both read the same).
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

    return _construct(RenderConfig, fields, "render:")


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


def resolve_interpolations(raw: dict) -> dict:
    """Resolve ``${key}`` references against ``raw``'s top-level scalars.

    Generic interpolation (mirrors MAY's ``config.yaml``): any ``${key}`` in a
    string value is replaced by the top-level scalar ``key``. Supports the
    events/world-in-different-dirs case; absolute paths carry no ``${}`` and
    pass through untouched.
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


def load_animator_config(path) -> AnimatorConfig:
    """Read a config YAML, resolve ``${}`` interpolation, validate, and
    construct the whole :class:`AnimatorConfig`. The single entry point a
    caller needs — no other function in this module is required to load a
    config end to end."""
    import yaml

    with open(path) as handle:
        raw = yaml.safe_load(handle) or {}
    resolved = resolve_interpolations(raw)

    inputs = _construct(InputsConfig, resolved.get("inputs"), "inputs:")
    output = _construct(OutputConfig, resolved.get("output"), "output:")
    render = _render_config_from(resolved.get("render"))

    aggregate_block = dict(resolved.get("aggregate") or {})
    geo_priority = resolve_geo_priority(aggregate_block, render.metric)
    aggregate_block["geo_priority"] = geo_priority
    aggregate = _construct(AggregateConfig, aggregate_block, "aggregate:")

    return AnimatorConfig(inputs=inputs, aggregate=aggregate, render=render, output=output)
