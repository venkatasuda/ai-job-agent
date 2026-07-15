"""
tests/conftest.py — Shared pytest configuration and fixtures
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is always on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="Run integration tests (needs API keys)")
    parser.addoption("--slow", action="store_true", help="Run slow tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip_integration = pytest.mark.skip(reason="Pass --integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not config.getoption("--slow"):
        skip_slow = pytest.mark.skip(reason="Pass --slow to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
