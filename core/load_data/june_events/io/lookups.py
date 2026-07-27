import h5py

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


def load_venues_lookup(path: str, columns: list[str] | None = None):
    # Column validation (friendly KeyError on unknown names) is owned by
    # load_raw_table, which validates from its single open read handle.
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
    # below is unaffected. Column validation is owned by load_raw_table.
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
