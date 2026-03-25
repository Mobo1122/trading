"""Shared pytest fixtures for the trading system test suite."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _force_paper_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests always run in paper mode for safety."""
    monkeypatch.setenv("TRADING_MODE", "paper")


@pytest.fixture
def test_settings():
    """Provide a Settings instance configured for testing.

    Uses paper mode with default values suitable for unit tests.
    Database and Redis URLs point to localhost defaults.
    """
    # Import here to avoid import-time side effects
    from trading.config import Settings

    os.environ["TRADING_MODE"] = "paper"
    return Settings()
