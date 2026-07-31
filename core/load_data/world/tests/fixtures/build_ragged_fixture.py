"""Build the ragged three-level ``world_state.h5`` used by the rollup tests.

Same schema as ``build_fixture.py`` — see that module for the dataset layout.
This one exists because the two-level fixture cannot exercise a **Rollup**: it
has no multi-hop walk, no ragged branch, and it lists coarse units first, which
*hides* the upstream ordering trap rather than covering it.

    nation 1 "Albion"        parent -1
    ├── region 2 "North"     parent 1
    │   ├── area 40 "A"      parent 2   3 residents
    │   └── area 50 "B"      parent 2   2 residents
    ├── region 3 "South"     parent 1
    │   └── area 60 "C"      parent 3   4 residents
    └── area 70 "D"          parent 1   1 resident   <- ragged: no region above it

Two deliberate awkwardnesses:

- **Ragged**: area 70 hangs straight off the nation, so it has *no* ancestor at
  the region level and a rollup to "region" must omit it (the caller then keeps
  its column and warns).
- **Leaf-first unit rows**: areas, then regions, then the nation. ``levels`` in
  ``metadata/registries/geo_levels`` is coarse->fine, but ``load_geography``
  recomputes ``GeographyManager.levels`` as first-seen over *file* order, so
  here the two disagree. Any code needing level order must read the registry.

Expected after load:
    population_by_geo_unit() -> {40:3, 50:2, 60:4, 70:1, 2:5, 3:4, 1:10}
    GeographyManager.levels  -> ["area", "region", "nation"]   (i.e. *wrong*)

Rerun manually if the schema ever changes:

    python build_ragged_fixture.py
"""

from pathlib import Path

import h5py
import numpy as np

FIXTURE_PATH = Path(__file__).with_name("world_state_ragged_fixture.h5")

# Coarse->fine, as the real serialiser writes it: index 0 -> nation, 2 -> area.
_LEVELS = ["nation", "region", "area"]

# Geography: (id, name, level_code, parent_id, latitude, longitude).
# Written leaf-first on purpose — see the module docstring.
_UNITS = [
    (40, "A", 2, 2, 51.0, -1.0),          # area under North
    (50, "B", 2, 2, 53.0, -3.0),          # area under North
    (60, "C", 2, 3, 50.0, 0.0),           # area under South
    (70, "D", 2, 1, 55.0, -5.0),          # area straight under the nation
    (2, "North", 1, 1, np.nan, np.nan),   # region
    (3, "South", 1, 1, np.nan, np.nan),   # region
    (1, "Albion", 0, -1, np.nan, np.nan), # nation, root
]

# Population: one row per person -> (geo_unit_id, age, sex_code).
_PEOPLE = [
    (40, 30, 0), (40, 8, 1), (40, 71, 0),          # 3 residents of area 40
    (50, 45, 1), (50, 19, 0),                      # 2 residents of area 50
    (60, 22, 0), (60, 61, 1), (60, 5, 0), (60, 38, 1),  # 4 residents of area 60
    (70, 12, 1),                                   # 1 resident of area 70
]


def build_ragged_fixture(path: Path = FIXTURE_PATH) -> Path:
    ids = np.array([unit[0] for unit in _UNITS], dtype=np.int64)
    names = np.array([unit[1] for unit in _UNITS], dtype=object)
    level_codes = np.array([unit[2] for unit in _UNITS], dtype=np.int64)
    parent_ids = np.array([unit[3] for unit in _UNITS], dtype=np.int64)
    latitudes = np.array([unit[4] for unit in _UNITS], dtype=np.float64)
    longitudes = np.array([unit[5] for unit in _UNITS], dtype=np.float64)

    person_geo_ids = np.array([person[0] for person in _PEOPLE], dtype=np.int64)
    person_ages = np.array([person[1] for person in _PEOPLE], dtype=np.int64)
    person_sexes = np.array([person[2] for person in _PEOPLE], dtype=np.int64)
    person_ids = np.arange(len(_PEOPLE), dtype=np.int64)

    string_dtype = h5py.string_dtype(encoding="utf-8")

    with h5py.File(path, "w") as world_file:
        metadata = world_file.create_group("metadata")
        metadata.create_dataset(
            "names/geography", data=names.astype("S"), dtype=string_dtype
        )
        metadata.create_dataset(
            "registries/geo_levels",
            data=np.array(_LEVELS, dtype=object).astype("S"),
            dtype=string_dtype,
        )

        geography = world_file.create_group("geography")
        geography.create_dataset("ids", data=ids)
        geography.create_dataset("names", data=names.astype("S"), dtype=string_dtype)
        geography.create_dataset("levels", data=level_codes)
        geography.create_dataset("parent_ids", data=parent_ids)
        geography.create_dataset("latitudes", data=latitudes)
        geography.create_dataset("longitudes", data=longitudes)

        population = world_file.create_group("population")
        population.create_dataset("ids", data=person_ids)
        population.create_dataset("geo_unit_ids", data=person_geo_ids)
        population.create_dataset("ages", data=person_ages)
        population.create_dataset("sexes", data=person_sexes)

    return path


if __name__ == "__main__":
    written = build_ragged_fixture()
    print(f"Wrote {written}")
