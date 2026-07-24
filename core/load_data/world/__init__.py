"""Read a JUNE/MAY **World file** (`world_state.h5`) into geography + population.

Thin wrapper over the installed ``world_reader`` dependency (ADR-0001). Supplies
the coordinates the **Events file** lacks and the population for rate-per-100k.
"""

from .world import World, load_world

__all__ = ["World", "load_world"]
