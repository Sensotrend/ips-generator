"""Shared pytest configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Registered here because pyproject.toml uses --strict-markers.
    config.addinivalue_line(
        "markers",
        "integration: needs local services (e.g. Matchbox); skipped when they are unreachable",
    )
