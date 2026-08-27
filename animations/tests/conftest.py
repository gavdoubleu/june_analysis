"""Shared fixtures for animator tests: reuse the vendored real-shape fixtures
from `core/` rather than building animator-specific ones."""

from core.aggregate.tests.conftest import (  # noqa: F401
    REAL_EVENTS_FIXTURE,
    requires_real_events_fixture,
)
from core.load_data.world.tests.conftest import world_fixture_path  # noqa: F401
