"""Boundary behaviour of `stitch_checkpoint_events`.

Regression cover for the mid-day resume: checkpoints land on a timestep, not
at midnight, so cutting the first run on a whole day drops the events between
midnight and the resume and the join day comes out anomalously low.
"""

import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from events_analysis.stitch_checkpoint_events import (  # noqa: E402
    check_boundary,
    detect_resume_time,
    stitch_event_type,
)

DEATHS = "events/deaths"
DTYPE = [("person_id", "<i4"), ("venue_id", "<i4"), ("time", "<f8")]

SPLIT_DAY = 54.0
RESUME_TIME = 54.5417  # 13:00 on day 54, as in the full_gb_2.0 -> 0.8 pair
# The timestep grid within a day, matching the real runs' schedules.
SLOTS = [0.0, 0.0417, 0.375, 0.4167, 0.5417]


def _rows(times):
    return np.array([(i, i * 10, t) for i, t in enumerate(times)], dtype=DTYPE)


def _first_run_times():
    """Days 52-55 on the grid. Written out of order within each day, as the
    real per-rank flushes are, so any endpoint-instead-of-extreme bug shows."""
    times = []
    for day in (52, 53, 54, 55):
        times.extend(reversed([day + slot for slot in SLOTS]))
    return times


def _second_run_times():
    """The resumed run: starts at RESUME_TIME, then day 55 onwards."""
    return [RESUME_TIME] + [55 + slot for slot in SLOTS]


def _write(path, event_path, times):
    with h5py.File(path, "w") as fh:
        fh.create_dataset(event_path, data=_rows(times))
    return path


def _stitch(tmp_path, split_time):
    first = _write(tmp_path / "first.h5", DEATHS, _first_run_times())
    second = _write(tmp_path / "second.h5", DEATHS, _second_run_times())
    with h5py.File(first, "r") as first_h5, \
         h5py.File(second, "r") as second_h5, \
         h5py.File(tmp_path / "out.h5", "w") as output_h5:
        earliest = stitch_event_type(first_h5, second_h5, output_h5, DEATHS, split_time)
        stitched = np.sort(output_h5[DEATHS]["time"])
    return stitched, earliest


def test_detect_resume_time_finds_the_mid_day_timestep(tmp_path):
    second = _write(tmp_path / "second.h5", DEATHS, _second_run_times())
    with h5py.File(second, "r") as second_h5:
        assert detect_resume_time(second_h5) == pytest.approx(RESUME_TIME)


def test_detect_resume_time_takes_the_minimum_across_event_types(tmp_path):
    """A type silent at the resume timestep must not push the split later."""
    path = tmp_path / "second.h5"
    with h5py.File(path, "w") as fh:
        fh.create_dataset(DEATHS, data=_rows([RESUME_TIME, 55.0]))
        fh.create_dataset("events/infections", data=_rows([55.0, 56.0]))
    with h5py.File(path, "r") as second_h5:
        assert detect_resume_time(second_h5) == pytest.approx(RESUME_TIME)


def test_detect_resume_time_rejects_a_file_with_no_events(tmp_path):
    path = tmp_path / "empty.h5"
    with h5py.File(path, "w") as fh:
        fh.create_dataset(DEATHS, data=np.empty(0, dtype=DTYPE))
    with h5py.File(path, "r") as second_h5, pytest.raises(ValueError, match="no non-empty event table"):
        detect_resume_time(second_h5)


def test_splitting_on_the_resume_time_keeps_every_event_once(tmp_path):
    stitched, _ = _stitch(tmp_path, RESUME_TIME)

    expected = sorted(
        [t for t in _first_run_times() if t < RESUME_TIME] + _second_run_times()
    )
    assert stitched == pytest.approx(expected)
    # The join day is whole: the first run covers it up to the resume, the
    # second run from the resume on.
    assert sum(54 <= t < 55 for t in stitched) == len(SLOTS)


def test_splitting_on_the_whole_day_loses_the_morning_of_the_join_day(tmp_path):
    """The original bug, kept as the contrast case."""
    stitched, _ = _stitch(tmp_path, SPLIT_DAY)

    assert sum(54 <= t < 55 for t in stitched) == 1  # only the resume timestep
    assert not any(SPLIT_DAY <= t < RESUME_TIME for t in stitched)


def test_stitch_event_type_reports_the_second_run_minimum_not_its_first_row(tmp_path):
    first = _write(tmp_path / "first.h5", DEATHS, _first_run_times())
    # Second run written newest-first, so row 0 is not the earliest event.
    second = _write(tmp_path / "second.h5", DEATHS, list(reversed(_second_run_times())))
    with h5py.File(first, "r") as first_h5, \
         h5py.File(second, "r") as second_h5, \
         h5py.File(tmp_path / "out.h5", "w") as output_h5:
        earliest = stitch_event_type(first_h5, second_h5, output_h5, DEATHS, RESUME_TIME)

    assert earliest == pytest.approx(RESUME_TIME)


def test_check_boundary_passes_when_the_second_run_starts_on_the_split():
    check_boundary(RESUME_TIME, {DEATHS: RESUME_TIME, "events/infections": 55.0})


def test_check_boundary_rejects_a_sub_day_gap():
    """The half-day hole the old 1.0-day tolerance let through."""
    with pytest.raises(ValueError, match="gap at the join"):
        check_boundary(SPLIT_DAY, {DEATHS: RESUME_TIME})


def test_check_boundary_rejects_an_overlap():
    with pytest.raises(ValueError, match="overlap at the join"):
        check_boundary(RESUME_TIME, {DEATHS: SPLIT_DAY})


def test_check_boundary_only_warns_when_the_split_was_overridden(caplog):
    with caplog.at_level("WARNING"):
        check_boundary(SPLIT_DAY, {DEATHS: RESUME_TIME}, strict=False)
    assert "gap at the join" in caplog.text


def test_check_boundary_rejects_a_stitch_with_no_shared_event_type():
    with pytest.raises(ValueError, match="nothing was stitched"):
        check_boundary(RESUME_TIME, {})
