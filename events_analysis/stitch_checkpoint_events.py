"""Stitch two checkpoint-resumed runs' Events files into one.

Scenario: a run (`--first-run-dir`) wrote checkpoints partway through and was
later resumed from one of them by a second run (`--second-run-dir`, possibly
with different config from that point on — e.g. a different transmissibility).
Both therefore share a prefix of simulated days but diverge from the
checkpoint day onwards. This script builds one `simulation_events.h5` that is
the first run up to (not including) `--split-day`, followed by the whole of
the second run — a seamless timeline with no double-counted day.

The split is *not* a whole day. A checkpoint is written partway through a
day (JUNE's `on_dates` checkpoints land on a timestep boundary, e.g. day 54
at 13:00 = `time` 54.5417), so trimming the first run at `time < 54.0`
discards half a day of events that the second run never regenerates — a
visible downwards spike on the join day. The split time is therefore
auto-detected as the second run's earliest recorded event time; `--split-day`
exists only to override that.

Only plain, already-decompressed `.h5` inputs are supported (see each run
dir's `simulation_events.h5.bz2` — decompress with `bunzip2` first).

Usage (defaults match the full_gb_2.0_checkpointed -> full_gb_0.8_day54 pair;
override the arguments below to stitch a different pair):

    python events_analysis/stitch_checkpoint_events.py \
        --first-run-dir data/runs/full_gb_2.0_checkpointed \
        --second-run-dir data/runs/full_gb_0.8_day54 \
        --output-dir data/runs/full_gb_2.0_then_0.8_day54
"""

import argparse
import datetime
import glob
import logging
import sys
from pathlib import Path

import h5py
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.load_data.june_events.introspect.scan import inspect_file  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVENTS_PREFIX = "events/"
REGISTRIES_PREFIX = "metadata/registries/"
TIME_FIELD = "time"
CHUNK_ROWS = 5_000_000  # matches core/load_data/june_events/io/raw_tables.py

# Rows scanned per second-run event table when auto-detecting the resume time.
# Rows are appended in flush order and every rank's first flush is capped at
# `output.max_event_buffer_size` (1e5), so the earliest simulated timestep is
# far inside this window. `stitch_event_type` recomputes the minimum exactly
# over every row as it copies, and `check_boundary` fails if the two disagree.
RESUME_SCAN_ROWS = CHUNK_ROWS

# The split time must coincide *exactly* with the second run's first event:
# any earlier and the two runs overlap (double-counted events), any later and
# the window between them is lost from both (the join-day dip). Both times
# come off the same timestep grid, so only float noise needs tolerating.
TIME_TOLERANCE_DAYS = 1e-6


# --------------------------------------------------------------------------
# Preconditions: the two runs must be resumable from one another at all.
# --------------------------------------------------------------------------

def _read_manifest(run_dir: Path) -> dict:
    with open(run_dir / "manifest.yaml") as fh:
        return yaml.safe_load(fh)


def _read_start_date(run_dir: Path) -> str:
    """Find `time.start_date` in whichever snapshotted config carries it.

    The main simulation config's filename varies between runs (`simulation.yaml`,
    `simulation2.yaml`, ...), so search `configs/*.yaml` for the one with a
    top-level `time:` block rather than assuming a name.
    """
    for config_path in glob.glob(str(run_dir / "configs" / "*.yaml")):
        with open(config_path) as fh:
            config = yaml.safe_load(fh)
        if isinstance(config, dict) and "time" in config:
            return config["time"]["start_date"]
    raise ValueError(f"no config with a 'time.start_date' block found under {run_dir}/configs")


def check_runs_are_stitchable(first_run_dir: Path, second_run_dir: Path) -> None:
    """Hard-fail if the two runs don't share a world and a start date.

    Same start date makes `time` (days since start) comparable across the two
    files; same world file makes the geo/lookup tables (below) identical, so
    it's safe to take them from either run rather than merging them.
    """
    first_manifest = _read_manifest(first_run_dir)
    second_manifest = _read_manifest(second_run_dir)

    first_world = first_manifest["lineage"]["world_path"]
    second_world = second_manifest["lineage"]["world_path"]
    if first_world != second_world:
        raise ValueError(
            f"world file mismatch: {first_run_dir} used {first_world!r}, "
            f"{second_run_dir} used {second_world!r} — not stitchable"
        )

    first_start = _read_start_date(first_run_dir)
    second_start = _read_start_date(second_run_dir)
    if first_start != second_start:
        raise ValueError(
            f"start_date mismatch: {first_run_dir} started {first_start!r}, "
            f"{second_run_dir} started {second_start!r} — 'time' values aren't comparable"
        )

    logger.info("preconditions OK: same world (%s), same start_date (%s)", first_world, first_start)


def check_registries_match(first_h5: Path, second_h5: Path) -> None:
    """Hard-fail if the two files' registries differ.

    Event tables store registry *indices*, not labels — if a registry's order
    or contents differ between the two runs, pasting index columns together
    would silently mislabel one half once decoded.
    """
    first_registries = inspect_file(str(first_h5)).registries
    second_registries = inspect_file(str(second_h5)).registries

    if first_registries.keys() != second_registries.keys():
        raise ValueError(
            f"registry set mismatch: {first_h5} has {sorted(first_registries)}, "
            f"{second_h5} has {sorted(second_registries)}"
        )
    for name, first_values in first_registries.items():
        second_values = second_registries[name]
        if first_values != second_values:
            raise ValueError(
                f"registry {name!r} differs between files: "
                f"{first_h5} has {first_values}, {second_h5} has {second_values}"
            )

    logger.info("registries OK: %d registries identical across both files", len(first_registries))


# --------------------------------------------------------------------------
# The merge itself.
# --------------------------------------------------------------------------

def _event_type_paths(h5_path: Path) -> set[str]:
    summary = inspect_file(str(h5_path))
    return {d.path for d in summary.datasets if d.path.startswith(EVENTS_PREFIX)}


def detect_resume_time(second_h5: h5py.File) -> float:
    """Earliest event time recorded by the resumed run — i.e. the timestep the
    checkpoint was taken at, and so the only correct place to cut the first run.

    Scans the head of every `events/*` table rather than every row: see
    `RESUME_SCAN_ROWS`. Minimum is taken across event types because a type can
    be silent at the resume timestep (`events/infections` records nothing until
    the timestep after the resume, so on its own it would put the cut a full
    day late).
    """
    resume_time = None
    for name, dataset in second_h5.get("events", {}).items():
        if TIME_FIELD not in (dataset.dtype.names or ()) or dataset.shape[0] == 0:
            continue
        head_min = float(dataset.fields(TIME_FIELD)[:RESUME_SCAN_ROWS].min())
        resume_time = head_min if resume_time is None else min(resume_time, head_min)
        logger.debug("events/%s: earliest time in second run's first %d rows is %s",
                     name, RESUME_SCAN_ROWS, head_min)

    if resume_time is None:
        raise ValueError(f"{second_h5.filename} has no non-empty event table with a {TIME_FIELD!r} field")
    return resume_time


def _copy_chunks_filtered(
    source_dset: h5py.Dataset, dest_dset: h5py.Dataset, start_offset: int, time_mask_fn
) -> tuple[int, float | None, float | None]:
    """Append `source_dset`'s rows (optionally filtered) onto `dest_dset`, starting
    at row `start_offset` (so a second call appends after a first, rather than
    overwriting it). Returns the row count in `dest_dset` after this call, plus
    the smallest and largest `time` among the rows this call kept (both `None`
    if it kept none).

    Reads in `CHUNK_ROWS`-row blocks so a multi-GB event type never needs to
    fit in memory whole. `time_mask_fn(chunk) -> bool array` selects which
    rows of a chunk to keep; pass `None` to keep every row.

    The min/max are taken over the rows themselves, not over the first and last
    of them: event tables are written in per-rank flush order, so they are only
    loosely time-ordered and their endpoints are not their extremes.
    """
    n_written = start_offset
    kept_min = kept_max = None
    n_rows = source_dset.shape[0]
    for start in range(0, n_rows, CHUNK_ROWS):
        chunk = source_dset[start : start + CHUNK_ROWS]
        if time_mask_fn is not None:
            chunk = chunk[time_mask_fn(chunk)]
        if len(chunk) == 0:
            continue
        chunk_times = chunk[TIME_FIELD]
        chunk_min, chunk_max = float(chunk_times.min()), float(chunk_times.max())
        kept_min = chunk_min if kept_min is None else min(kept_min, chunk_min)
        kept_max = chunk_max if kept_max is None else max(kept_max, chunk_max)
        dest_dset.resize(n_written + len(chunk), axis=0)
        dest_dset[n_written : n_written + len(chunk)] = chunk
        n_written += len(chunk)
    return n_written, kept_min, kept_max


def stitch_event_type(
    first_h5: h5py.File,
    second_h5: h5py.File,
    output_h5: h5py.File,
    event_path: str,
    split_time: float,
) -> float | None:
    """Write one `events/<type>` dataset: first run's rows before `split_time`,
    then all of the second run's rows. Returns this type's earliest second-run
    event time (`None` if the second run has none), for `check_boundary`.
    """
    first_dset = first_h5.get(event_path)
    second_dset = second_h5.get(event_path)

    if first_dset is None or second_dset is None:
        # Not every file has every event type (june_events/CONTEXT.md). Copy
        # whichever side has it through unchanged rather than dropping it.
        source_h5, source_dset = (first_h5, first_dset) if first_dset is not None else (second_h5, second_dset)
        logger.warning("%s only present in %s — copying through unchanged", event_path, source_h5.filename)
        source_h5.copy(event_path, output_h5, name=event_path)
        return None

    if TIME_FIELD not in first_dset.dtype.names or TIME_FIELD not in second_dset.dtype.names:
        raise ValueError(f"{event_path} is missing a {TIME_FIELD!r} field in one of the input files")

    output_dset = output_h5.create_dataset(
        event_path,
        shape=(0,),
        maxshape=(None,),
        dtype=first_dset.dtype,
        chunks=True,
    )

    n_from_first, _, last_kept_time = _copy_chunks_filtered(
        first_dset, output_dset, 0, lambda chunk: chunk[TIME_FIELD] < split_time
    )
    n_total, first_second_time, _ = _copy_chunks_filtered(second_dset, output_dset, n_from_first, None)
    n_from_second = n_total - n_from_first

    logger.info(
        "%s: %d rows from first run (time<%s, last kept %s) + %d rows from second run "
        "(first %s) = %d total",
        event_path, n_from_first, split_time, last_kept_time, n_from_second,
        first_second_time, n_total,
    )
    return first_second_time


def check_boundary(split_time: float, second_run_first_times: dict[str, float], strict: bool = True) -> None:
    """Report on whether the join came out seamless, using the exact per-row
    minima gathered while copying rather than `detect_resume_time`'s head scan.

    The one invariant that makes the timeline continuous: the second run's
    earliest event sits exactly on `split_time`. Earlier means the runs overlap
    and the shared window is double-counted; later means that window was cut
    from the first run and never replaced by the second — the anomalous dip on
    the join day. The comparison is against the *global* earliest across event
    types, since a type can be silent at the resume timestep and legitimately
    start later.

    `strict` raises on a violation; it is off when the caller overrode the split
    time by hand, where a deliberate gap or overlap is the caller's business.
    """
    if not second_run_first_times:
        raise ValueError("no event type was present in both runs — nothing was stitched")

    earliest_path = min(second_run_first_times, key=second_run_first_times.get)
    earliest_time = second_run_first_times[earliest_path]
    offset = earliest_time - split_time

    if abs(offset) > TIME_TOLERANCE_DAYS:
        if offset > 0:
            problem = (f"gap at the join: {offset:.4f} days were trimmed from the first run and "
                       f"never replaced by the second")
        else:
            problem = (f"overlap at the join: {-offset:.4f} days are present from both runs and "
                       f"double-counted")
        message = (
            f"{problem} — split_time={split_time} but the second run's first event is "
            f"{earliest_time} ({earliest_path}); rerun with --split-day {earliest_time!r}, "
            f"or drop --split-day to auto-detect"
        )
        if strict:
            raise ValueError(message)
        logger.warning("%s", message)
        return

    logger.info("boundary OK: second run's first event (%s, %s) sits on split_time=%s",
                earliest_time, earliest_path, split_time)


def copy_non_event_data(source_h5: h5py.File, output_h5: h5py.File) -> None:
    """Copy every top-level group except `events/` straight across.

    Covers `metadata/` (registries) and `lookups/` (people, venues,
    people_properties/*) — deterministic from the shared world file, so
    identical between the two runs (checked by `check_registries_match` for
    the registries; the rest follow the same reasoning). Taken from
    `source_h5` alone rather than merged.
    """
    for name in source_h5:
        if name == "events":
            continue
        source_h5.copy(name, output_h5, name=name)
        logger.info("copied %r from %s", name, source_h5.filename)


# --------------------------------------------------------------------------
# Provenance.
# --------------------------------------------------------------------------

def write_manifest(
    output_dir: Path,
    first_run_dir: Path,
    second_run_dir: Path,
    split_time: float,
    split_time_auto_detected: bool,
) -> None:
    manifest = {
        "stitched_by": "events_analysis/stitch_checkpoint_events.py",
        "stitched_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "first_run_dir": str(first_run_dir),
        "second_run_dir": str(second_run_dir),
        "split_time": split_time,
        "split_time_auto_detected": split_time_auto_detected,
        "rule": (
            f"events/* = first_run[time < {split_time}] followed by all of second_run; "
            "metadata/ and lookups/ copied from first_run"
        ),
    }
    with open(output_dir / "manifest.yaml", "w") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False)


# --------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--first-run-dir", type=Path, default=Path("data/runs/full_gb_2.0_checkpointed"),
                         help="run dir whose tail gets trimmed")
    parser.add_argument("--second-run-dir", type=Path, default=Path("data/runs/full_gb_0.8_day54"),
                         help="run dir resumed from a checkpoint of the first")
    parser.add_argument("--split-day", type=float, default=None,
                         help="override the auto-detected resume time, in days since start_date; "
                              "the first run is trimmed to time < this. Checkpoints land mid-day, so "
                              "a whole number is almost always wrong — leave this unset")
    parser.add_argument("--output-dir", type=Path, default=Path("data/runs/full_gb_2.0_then_0.8_day54"),
                         help="destination run dir for the stitched simulation_events.h5")
    args = parser.parse_args()

    first_h5_path = args.first_run_dir / "simulation_events.h5"
    second_h5_path = args.second_run_dir / "simulation_events.h5"
    for path in (first_h5_path, second_h5_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found — decompress its .h5.bz2 first")

    check_runs_are_stitchable(args.first_run_dir, args.second_run_dir)
    check_registries_match(first_h5_path, second_h5_path)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_h5_path = args.output_dir / "simulation_events.h5"

    with h5py.File(first_h5_path, "r") as first_h5, \
         h5py.File(second_h5_path, "r") as second_h5:
        resume_time = detect_resume_time(second_h5)
        logger.info("second run resumed at time=%s (day %d, %s of a day in)",
                    resume_time, int(resume_time), round(resume_time % 1, 4))

        split_time = resume_time if args.split_day is None else args.split_day
        if args.split_day is not None and abs(args.split_day - resume_time) > TIME_TOLERANCE_DAYS:
            # Cheap version of check_boundary, before hours of copying.
            logger.warning(
                "--split-day %s disagrees with the detected resume time %s by %.4f days — "
                "the join will gap or overlap; drop --split-day to auto-detect",
                args.split_day, resume_time, abs(args.split_day - resume_time),
            )

        with h5py.File(output_h5_path, "w") as output_h5:
            copy_non_event_data(first_h5, output_h5)

            second_run_first_times = {}
            event_paths = _event_type_paths(first_h5_path) | _event_type_paths(second_h5_path)
            for event_path in sorted(event_paths):
                first_time = stitch_event_type(first_h5, second_h5, output_h5, event_path, split_time)
                if first_time is not None:
                    second_run_first_times[event_path] = first_time

    check_boundary(split_time, second_run_first_times, strict=args.split_day is None)
    write_manifest(args.output_dir, args.first_run_dir, args.second_run_dir,
                   split_time, args.split_day is None)
    logger.info("wrote %s", output_h5_path)


if __name__ == "__main__":
    main()
