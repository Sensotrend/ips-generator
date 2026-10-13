"""Shared pytest configuration."""

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Registered here because pyproject.toml uses --strict-markers.
    config.addinivalue_line(
        "markers",
        "integration: needs local services (e.g. Matchbox); skipped when they are unreachable",
    )
    config.addinivalue_line(
        "markers",
        "network: calls a public server (tx.fhir.org); opt-in with RUN_NETWORK_TESTS=1",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Public servers are outside our control: never call them in a default run or in CI.
    if os.environ.get("RUN_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set RUN_NETWORK_TESTS=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
