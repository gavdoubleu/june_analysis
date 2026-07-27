import h5py

from ..introspect import dataset_field_names
from .raw_tables import load_raw_table

_PEOPLE_PROPERTIES_GROUP = "lookups/people_properties"

# Single source of truth for the lookup dataset paths — kept here (behind the
# lookup seam) so consumers ask for "venues"/"people" data, not file layout.
VENUES_DATASET = "lookups/venues"
PEOPLE_DATASET = "lookups/people"


def _decode_value(value):
    return value.decode() if isinstance(value, bytes) else value


def _decode_byte_columns(df):
    for column in df.columns:
        if df[column].dtype.kind in ("S", "O"):
            df[column] = df[column].apply(_decode_value)
    return df


def _validate_columns(path: str, dataset_path: str, columns):
    # Names speak the raw stored fields (no registry decode here, unlike
    # load_decoded_events) — reject anything not in the compound record.
    available = dataset_field_names(path, dataset_path)
    if available is None:
        return
    unknown = [name for name in columns if name not in available]
    if unknown:
        raise KeyError(
            f"unknown column(s) {unknown!r} for {dataset_path!r}; "
            f"valid columns are {list(available)!r}"
        )


def load_venues_lookup(path: str, columns: list[str] | None = None):
    if columns is not None:
        _validate_columns(path, VENUES_DATASET, columns)
    venues = load_raw_table(path, VENUES_DATASET, columns=columns)
    if venues is None:
        return None
    return _decode_byte_columns(venues)


def load_people_lookup(
    path: str, include_properties: bool = True, columns: list[str] | None = None
):
    # `columns` projects the main lookups/people record only; property names
    # live in separate datasets and are never requestable here. Field
    # projection keeps every row, so the positional people_properties alignment
    # below is unaffected.
    if columns is not None:
        _validate_columns(path, PEOPLE_DATASET, columns)
    people = load_raw_table(path, PEOPLE_DATASET, columns=columns)
    if people is None:
        return None
    people = _decode_byte_columns(people)

    if include_properties:
        with h5py.File(path, "r") as fh:
            if _PEOPLE_PROPERTIES_GROUP in fh:
                for property_name, dataset in fh[_PEOPLE_PROPERTIES_GROUP].items():
                    if len(dataset) != len(people):
                        raise ValueError(
                            f"people_properties/{property_name} has {len(dataset)} "
                            f"rows, but lookups/people has {len(people)} — these "
                            f"must be aligned by construction"
                        )
                    people[property_name] = [_decode_value(v) for v in dataset[:]]

    return people
