import h5py

from .types import DatasetSummary, FileSummary

_REGISTRIES_PREFIX = "metadata/registries/"


def _decode(value):
    return value.decode() if isinstance(value, bytes) else value


def inspect_file(path: str) -> FileSummary:
    with h5py.File(path, "r") as fh:
        datasets = []
        registries = {}

        def collect(name, obj):
            if not isinstance(obj, h5py.Dataset):
                return
            if name.startswith(_REGISTRIES_PREFIX):
                registry_name = name[len(_REGISTRIES_PREFIX):]
                registries[registry_name] = [_decode(v) for v in obj[:]]
                return
            datasets.append(
                DatasetSummary(
                    path=name,
                    n_rows=obj.shape[0],
                    dtype=str(obj.dtype),
                    nbytes=obj.nbytes,
                )
            )

        fh.visititems(collect)

    return FileSummary(path=path, datasets=datasets, registries=registries)


def dataset_field_names(path: str, dataset_path: str) -> tuple[str, ...] | None:
    """Field names of one compound dataset, header-only.

    Reads `dtype.names` without touching row data — the targeted answer to
    "does this dataset carry field X?" that `inspect_file` throws away at its
    `str(dtype)`. Returns `None` if the dataset is absent (same missing-table
    semantics as `inspect_file`), or `None` for a non-compound dtype.
    """
    with h5py.File(path, "r") as fh:
        if dataset_path not in fh:
            return None
        return fh[dataset_path].dtype.names
