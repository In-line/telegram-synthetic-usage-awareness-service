"""Shared pytest fixtures for synthetic-usage-awareness tests.

Imports the package from src/ without requiring installation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


@pytest.fixture
def tmp_state_file(tmp_path):
    """Provide a temporary state file path."""
    return str(tmp_path / "state.json")


@pytest.fixture
def default_config():
    """Default ServiceConfig with test values."""
    from synthetic_usage_awareness.config import ServiceConfig

    return ServiceConfig(
        enabled=True,
        api_key="syn_test_key",
        api_base="https://api.synthetic.new",
        bot_token="123:ABC",
        chat_id="-1001234567890",
        thread_id="3649",
        state_file="/tmp/test_sua_state.json",
    )


@pytest.fixture
def config_with_state(tmp_state_file):
    """ServiceConfig with a temporary state file."""
    from synthetic_usage_awareness.config import ServiceConfig

    return ServiceConfig(
        enabled=True,
        api_key="syn_test_key",
        api_base="https://api.synthetic.new",
        bot_token="123:ABC",
        chat_id="-1001234567890",
        thread_id="3649",
        state_file=tmp_state_file,
    )


@pytest.fixture
def mock_client_100():
    """MockSyntheticClient starting at 100% remaining."""
    from synthetic_usage_awareness.synthetic_client import MockSyntheticClient

    return MockSyntheticClient(initial_percent=100.0)


@pytest.fixture
def mock_client_80():
    """MockSyntheticClient starting at 80% remaining."""
    from synthetic_usage_awareness.synthetic_client import MockSyntheticClient

    return MockSyntheticClient(initial_percent=80.0)


@pytest.fixture
def mock_notifier():
    """MockNotifier that captures alerts instead of sending them."""
    from synthetic_usage_awareness.notifier import MockNotifier

    return MockNotifier()


@pytest.fixture
def fresh_tracker(config_with_state):
    """UsageTracker with fresh state."""
    from synthetic_usage_awareness.state import TrackerState
    from synthetic_usage_awareness.usage_tracker import UsageTracker

    state = TrackerState()
    return UsageTracker(config_with_state, state)


@pytest.fixture
def initialized_tracker(fresh_tracker):
    """UsageTracker that has already done its first check (baseline at 100%)."""
    from synthetic_usage_awareness.synthetic_client import MockSyntheticClient

    client = MockSyntheticClient(initial_percent=100.0)
    fresh_tracker.evaluate(client.get_usage())  # Establish baseline
    return fresh_tracker
