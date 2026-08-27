"""Config-driven animator driver (Phase 4b Consumer).

A thin app over the Phase 4a engine: reads a ``--config`` YAML, resolves input
paths, hands the ordering-sensitive composition to :mod:`build_pipeline`, and
writes one animation to ``animations/output/``. Lives in ``animations/`` (a
Consumer), imports nothing new into ``core/``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Run as a bare script (`python animations/animate_epidemic_example.py`) the repo
# root is not on sys.path, so `import core` fails; put it there. A no-op under
# pytest / `python -m`, where the root is already importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from animations.build_pipeline import build_pipeline

_INTERPOLATION = re.compile(r"\$\{([^}]+)\}")

_DEFAULT_CONFIG = Path(__file__).parent / "configs" / "config_default.yaml"

# inputs: key -> (CONTEXT term, the filename a run writes it as)
_INPUT_KINDS = {
    "events": ("Events file", "simulation_events.h5"),
    "world": ("World file", "world_state.h5"),
}


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


def resolve_input_path(inputs: dict, key: str) -> str:
    """One `inputs:` path, checked for existence before any reader touches it.

    The shipped ``config_default.yaml`` is a template with ``/path/to/...``
    placeholders, so "you did not edit the config" is the single most likely
    first failure. h5py reports that as a wall of ``errno = 2`` text naming
    flags and o_flags; say it plainly instead.
    """
    kind, filename = _INPUT_KINDS[key]
    path = inputs.get(key)
    if not path:
        raise ValueError(
            f"inputs.{key} is missing from the config; it must point at your "
            f"run's {kind} ({filename})"
        )
    if not Path(path).exists():
        hint = (
            " — that is the template's placeholder, edit the config's roots"
            if "/path/to/" in str(path)
            else ""
        )
        raise FileNotFoundError(f"{kind} not found (inputs.{key}): {path}{hint}")
    return path


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

    Orchestration only: resolve input paths, hand the ordering-sensitive
    composition to :func:`build_pipeline`, assemble the output path, render.
    """
    from core.animations_core import animate
    from core.load_data.simulation_events import SimulationEvents

    inputs = config.get("inputs", {})
    aggregate_block = config.get("aggregate", {})
    output_block = config.get("output", {})

    # Both paths up front: a missing World file should not surface only after the
    # whole events load and aggregate have run.
    events_path = resolve_input_path(inputs, "events")
    world_path = resolve_input_path(inputs, "world")

    events = SimulationEvents(events_path)
    outputs = build_pipeline(events, aggregate_block, config.get("render"), world_path)

    output_path = resolve_output_path(output_block, outputs.event_type)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    animate(
        outputs.aggregate,
        outputs.world,
        outputs.render_config,
        output_path,
        output_block.get("format"),
    )
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
