"""Thin wrapper over the installed ``world_reader`` dependency (MAY-owned,
installed rather than vendored so fixes flow downstream).

Reads a ``world_state.h5`` (**World file**) and exposes just what the analysis
platform needs: geo-unit coordinates and resident population per geo unit. It
supplies the coordinates the **Events file** lacks; ``core/aggregate`` never
imports this module (ADR-0003) — population is passed *into* ``rate_per_100k``.

``world_reader`` is light (h5py/numpy/pandas only), so importing it at module
top level does not breach the render-agnostic core boundary (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
from world_reader.geography import (
    GeographyManager,
    infer_missing_coordinates,
    load_geography,
)
from world_reader.statistics import compute_unit_statistics


def _read_geography_metadata(world_file: h5py.File):
    """Return ``(geo_names, level_registry)`` from the ``metadata`` group, or
    ``(None, None)`` when absent.

    Mirrors the metadata handling in the upstream single-call entry point
    (``world_reader/world_store.py`` ``build_world_store``): unit names and the
    level-code registry live under ``metadata`` and must be passed to
    ``load_geography`` or levels/names decode wrongly.
    """
    geo_names = level_registry = None
    if "metadata" in world_file:
        metadata = world_file["metadata"]
        if "names" in metadata and "geography" in metadata["names"]:
            geo_names = metadata["names"]["geography"][:].astype(str)
        if "registries" in metadata and "geo_levels" in metadata["registries"]:
            level_registry = metadata["registries"]["geo_levels"][:].astype(str)
    return geo_names, level_registry


@dataclass(frozen=True)
class World:
    """A loaded **World file**: geography plus resident population per geo unit.

    ``geography`` is the ``world_reader`` hierarchy; ``population_by_geo_unit``
    maps each geo unit to its subtree-aggregated resident count.
    """

    geography: GeographyManager
    _population_by_geo_unit: dict[int, int]
    # Coarse->fine, from `metadata/registries/geo_levels`; the *only* ordered
    # source of level names. `GeographyManager.levels` is first-seen over unit
    # file order, which has no relation to depth. ``None`` when the World file
    # carries no registry.
    _level_registry: tuple[str, ...] | None = None

    def geo_unit_coords(self) -> dict[int, tuple[float, float]]:
        """``{geo_unit_id: (lat, lon)}`` (WGS84) for every unit with coordinates."""
        return self.geography.geo_unit_coords()

    def population_by_geo_unit(self) -> dict[int, int]:
        """``{geo_unit_id: population}`` — subtree-aggregated resident count.

        Defined for every unit (leaf or parent), so ``rate_per_100k`` is correct
        whatever geo level the aggregate keys on. The value feeding per-100k
        normalisation.
        """
        return dict(self._population_by_geo_unit)

    def geo_levels(self) -> list[str]:
        """The run's **Geo level** names; order not guaranteed.

        From the World file's level registry. Falls back to the hierarchy's own
        first-seen list where a World file carries no registry — the names are
        still right, but the *order* is then meaningless. Use
        :meth:`geo_levels_coarsest_first` where the order itself matters.
        """
        if self._level_registry is not None:
            return list(self._level_registry)
        return list(self.geography.levels)

    def geo_levels_coarsest_first(self) -> tuple[str, ...]:
        """The run's **Geo level** names, coarsest first — order guaranteed.

        Raises ``ValueError`` where the World file carries no level registry,
        rather than silently handing back a meaningless order.
        """
        if self._level_registry is None:
            raise ValueError(
                "this world has no geo-level registry; the levels are "
                f"{self.geo_levels()}, but their order is meaningless"
            )
        return self._level_registry

    def ancestor_by_geo_unit(self, level: str) -> dict[int, int]:
        """``{geo_unit_id: ancestor_geo_unit_id}`` at `level` — a **Rollup**'s map.

        Walks each unit's parent chain until a unit at `level` is found; a unit
        already at `level` maps to itself. Units with no ancestor there — an
        **Orphan unit**, a ragged branch, or a unit coarser than `level` — are
        **omitted**, and `core.aggregate.rollup.rollup` keeps their columns as
        they are rather than dropping their counts.

        The walk needs no level ordering, so a ragged hierarchy is fine.

        Raises ``ValueError`` for a level name this run does not have: level
        names are per-run, so a typo would otherwise return an empty map and
        roll every column up to nothing.
        """
        known_levels = self.geo_levels()
        if level not in known_levels:
            order_claim = " (coarsest first)" if self._level_registry is not None else ""
            raise ValueError(
                f"unknown geo level {level!r}; this world has "
                f"{known_levels}{order_claim}"
            )

        ancestors = {}
        # Sourced from the hierarchy, not `population_by_geo_unit()`: upstream
        # omits childless zero-population units from the statistics entirely.
        for unit_id, unit in self.geography.units_by_id.items():
            ancestor = unit
            while ancestor is not None and ancestor.level != level:
                ancestor = ancestor.parent
            if ancestor is not None:
                ancestors[unit_id] = ancestor.id
        return ancestors

    def infer_missing_coordinates(self) -> int:
        """Fill coord-less units from their children's mean, in place.

        Opt-in (maps need full coverage; the events-only path does not). Returns
        the number of units whose coordinates were newly inferred.
        """
        return infer_missing_coordinates(self.geography)


def load_world(path: str | Path) -> World:
    """Load a ``world_state.h5`` into a :class:`World`.

    Raises ``FileNotFoundError`` (with an actionable message) when the World file
    is absent — the map/rate path needs it, but the events-only path does not
    (ADR-0003), so the caller can degrade rather than crash on a bare traceback.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"World file not found: {path}. A world_state.h5 is required for maps "
            "and rate-per-100k; the events-only analysis path does not need it."
        )
    with h5py.File(path, "r") as world_file:
        if "geography" not in world_file:
            raise OSError(
                f"World file {path} has no 'geography' group; it is not a valid "
                "world_state.h5 (or was written by an incompatible version)."
            )
        geo_names, level_registry = _read_geography_metadata(world_file)
        geography = load_geography(world_file["geography"], geo_names, level_registry)
        unit_statistics = compute_unit_statistics(
            world_file, geography, include_activity_counts=False
        )
    population_by_geo_unit = {
        unit_id: stats.population for unit_id, stats in unit_statistics.items()
    }
    return World(
        geography=geography,
        _population_by_geo_unit=population_by_geo_unit,
        _level_registry=(
            None if level_registry is None else tuple(str(name) for name in level_registry)
        ),
    )
