"""Build the small synthetic ``world_state.h5`` used by the world-wrapper tests.

Mirrors the real schema the installed ``world_reader`` reads (see
``MAY2/.../world_reader/world_store.py`` metadata handling and
``geography.load_geography`` / ``statistics.compute_unit_statistics``):

- ``metadata/names/geography``   — decoded unit names
- ``metadata/registries/geo_levels`` — level-code -> level-name registry
- ``geography/{ids,names,levels,parent_ids,latitudes,longitudes}``
- ``population/{ids,geo_unit_ids,ages,sexes}`` — one row per person

The hierarchy is deliberately tiny with fully known expected values:

    region 10  "North"  coords MISSING (NaN)  -> inferred = mean of children
    ├── area 20 "A"     coords (51.0, -1.0)   3 residents
    └── area 30 "B"     coords (53.0, -3.0)   2 residents

Expected after load:
    geo_unit_coords()          -> {20:(51.0,-1.0), 30:(53.0,-3.0)}   (10 has no coord)
    infer_missing_coordinates()-> fills 10 = (52.0, -2.0); returns 1
    population_by_geo_unit()   -> {20:3, 30:2, 10:5}  (subtree-aggregated)

Rerun manually if the schema ever changes:

    python build_fixture.py
"""

from pathlib import Path

import h5py
import numpy as np

FIXTURE_PATH = Path(__file__).with_name("world_state_fixture.h5")

# Geography: (id, name, level_code, parent_id, latitude, longitude)
_LEVELS = ["region", "area"]  # index 0 -> region, 1 -> area
_UNITS = [
    (10, "North", 0, -1, np.nan, np.nan),  # region, coords missing
    (20, "A", 1, 10, 51.0, -1.0),          # area under North
    (30, "B", 1, 10, 53.0, -3.0),          # area under North
]

# Population: one row per person -> (geo_unit_id, age, sex_code)
_PEOPLE = [
    (20, 30, 0), (20, 8, 1), (20, 71, 0),   # 3 residents of area 20
    (30, 45, 1), (30, 19, 0),               # 2 residents of area 30
]


def build_fixture(path: Path = FIXTURE_PATH) -> Path:
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
    written = build_fixture()
    print(f"Wrote {written}")
