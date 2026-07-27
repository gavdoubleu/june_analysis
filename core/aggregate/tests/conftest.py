"""Synthetic *Located event tables* with known geo/time counts.

Mirrors the shape produced by `core.load_data.geo_events.load_geo_events`: a
pandas DataFrame carrying `time` plus a single resolved `geo_unit_id`. Kept
in-memory so the exact-count tracer tests own their expected answers. (The
venue-vs-person resolution that used to happen inside `aggregate_events` now
lives in `load_geo_events` — see its own tests.)
"""

import os

import numpy as np
import pandas as pd
import pytest

# Reuse the Phase-1 real-events fixture for real-shape integration tests.
REAL_EVENTS_FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "load_data",
    "june_events",
    "tests",
    "fixtures",
    "simulation_events_fixture.h5",
)

requires_real_events_fixture = pytest.mark.skipif(
    not os.path.exists(REAL_EVENTS_FIXTURE),
    reason="real simulation_events.h5 fixture missing",
)


@pytest.fixture
def located_events_simple():
    """Six events over two days across geo units {10, 20}, geo already resolved:
      day 0 (time in [0, 1)): geo 10 x2, geo 20 x1
      day 1 (time in [1, 2)): geo 10 x1, geo 20 x2
    """
    return pd.DataFrame(
        {
            "time": [0.1, 0.2, 0.9, 1.1, 1.5, 1.9],
            "geo_unit_id": [10, 10, 20, 10, 20, 20],
        }
    )
