"""Read a JUNE/MAY **World file** (`world_state.h5`) into geography + population.

Thin wrapper over the installed ``world_reader`` dependency (MAY-owned, installed
rather than vendored so fixes flow downstream). Supplies
the coordinates the **Events file** lacks and the population for rate-per-100k.
"""

from .world import World, load_world

__all__ = ["World", "load_world"]
