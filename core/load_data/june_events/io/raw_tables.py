import logging

import h5py
import pandas as pd

logger = logging.getLogger(__name__)


def load_raw_table(
    path: str,
    dataset_path: str,
    columns: list[str] | None = None,
    chunk_threshold_bytes: int = 500_000_000,
    chunk_rows: int = 5_000_000,
):
    # Owns projected-column validation: because the file is already open here,
    # bad `columns` raise the friendly KeyError from the single read handle — no
    # separate header peek. Names speak the raw stored fields (dtype.names).
    with h5py.File(path, "r") as fh:
        if dataset_path not in fh:
            logger.warning("dataset %r not found in %r", dataset_path, path)
            return None

        dset = fh[dataset_path]
        available = dset.dtype.names
        if columns is not None and available is not None:
            unknown = [name for name in columns if name not in available]
            if unknown:
                raise KeyError(
                    f"unknown column(s) {unknown!r} for {dataset_path!r}; "
                    f"valid columns are {list(available)!r}"
                )
        # Project the requested fields at read time (h5py reads only those into
        # memory) so a wide event table costs RAM in proportion to the columns
        # actually wanted; None reads the whole compound record as before.
        source = dset.fields(columns) if columns is not None else dset

        # Size the chunk decision on what we actually read, not the whole record.
        selected_itemsize = source.dtype.itemsize if columns is not None else dset.dtype.itemsize
        nbytes = dset.shape[0] * selected_itemsize
        if nbytes <= chunk_threshold_bytes:
            return pd.DataFrame(source[:])

        n_rows = dset.shape[0]
        chunks = [
            pd.DataFrame(source[start : start + chunk_rows])
            for start in range(0, n_rows, chunk_rows)
        ]
        return pd.concat(chunks, ignore_index=True, copy=False)
