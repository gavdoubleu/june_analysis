import os

import pytest

# Reuse the real events fixture that ships with the june_events reader tests.
REAL_EVENTS_FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "june_events",
    "tests",
    "fixtures",
    "simulation_events_fixture.h5",
)

requires_real_events_fixture = pytest.mark.skipif(
    not os.path.exists(REAL_EVENTS_FIXTURE),
    reason="real simulation_events.h5 fixture missing from june_events/tests/fixtures/",
)
