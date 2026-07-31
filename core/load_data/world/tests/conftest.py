"""Shared fixtures for the world-wrapper tests."""

from pathlib import Path

import pytest

from .fixtures.build_fixture import FIXTURE_PATH, build_fixture
from .fixtures.build_ragged_fixture import (
    FIXTURE_PATH as RAGGED_FIXTURE_PATH,
    build_ragged_fixture,
)


@pytest.fixture(scope="session")
def world_fixture_path() -> Path:
    """Path to the small synthetic ``world_state.h5`` (built if absent)."""
    if not FIXTURE_PATH.exists():
        build_fixture()
    return FIXTURE_PATH


@pytest.fixture(scope="session")
def ragged_world_fixture_path() -> Path:
    """Path to the three-level ragged ``world_state.h5`` (built if absent)."""
    if not RAGGED_FIXTURE_PATH.exists():
        build_ragged_fixture()
    return RAGGED_FIXTURE_PATH
