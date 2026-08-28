"""Tests for TrackerState — persistence, loading, and state transitions."""

from __future__ import annotations

import json
import os
from pathlib import Path

from synthetic_usage_awareness.state import TrackerState


class TestStatePersistence:
    """Test save/load round-trip."""

    def test_save_and_load(self, tmp_path):
        """State survives save → load round-trip."""
        path = str(tmp_path / "state.json")
        state = TrackerState(
            baseline_remaining=75.5,
            last_alert_tier=2,
            last_low_alert_remaining=75.5,
            last_check_remaining=73.2,
            last_check_time="2026-07-31T01:00:00+00:00",
            initialized=True,
            total_checks=42,
            total_alerts_sent=3,
        )
        state.save(path)

        loaded = TrackerState.load(path)
        assert loaded.baseline_remaining == 75.5
        assert loaded.last_alert_tier == 2
        assert loaded.last_low_alert_remaining == 75.5
        assert loaded.last_check_remaining == 73.2
        assert loaded.last_check_time == "2026-07-31T01:00:00+00:00"
        assert loaded.initialized is True
        assert loaded.total_checks == 42
        assert loaded.total_alerts_sent == 3

    def test_load_missing_file(self, tmp_path):
        """Loading a non-existent file returns fresh state."""
        path = str(tmp_path / "nonexistent.json")
        state = TrackerState.load(path)
        assert state.initialized is False
        assert state.baseline_remaining is None
        assert state.last_alert_tier == 0
        assert state.total_checks == 0

    def test_load_corrupt_file(self, tmp_path):
        """Loading a corrupt JSON file returns fresh state."""
        path = str(tmp_path / "corrupt.json")
        Path(path).write_text("{ this is not valid json")
        state = TrackerState.load(path)
        assert state.initialized is False
        assert state.baseline_remaining is None

    def test_load_partial_data(self, tmp_path):
        """Loading a file with extra/unknown keys ignores them."""
        path = str(tmp_path / "partial.json")
        data = {
            "baseline_remaining": 50.0,
            "initialized": True,
            "unknown_key": "should be ignored",
            "total_checks": 10,
        }
        Path(path).write_text(json.dumps(data))
        state = TrackerState.load(path)
        assert state.baseline_remaining == 50.0
        assert state.initialized is True
        assert state.total_checks == 10
        assert not hasattr(state, "unknown_key")

    def test_save_creates_parent_dirs(self, tmp_path):
        """Save creates parent directories if they don't exist."""
        path = str(tmp_path / "subdir" / "deeper" / "state.json")
        state = TrackerState()
        state.save(path)
        assert os.path.exists(path)


class TestStateBackwardCompat:
    """Test backward compatibility with old state format."""

    def test_migrate_old_last_alert_remaining(self, tmp_path):
        """Old state files with 'last_alert_remaining' should migrate to 'baseline_remaining'."""
        path = str(tmp_path / "old_state.json")
        data = {
            "last_alert_remaining": 92.4,
            "last_low_alert_remaining": 92.4,
            "last_check_remaining": 91.7,
            "last_check_time": "2026-07-31T21:56:38+00:00",
            "initialized": True,
            "total_checks": 76,
            "total_alerts_sent": 2,
        }
        Path(path).write_text(json.dumps(data))
        state = TrackerState.load(path)
        assert state.baseline_remaining == 92.4
        assert state.last_alert_tier == 0  # default for migrated state
        assert state.total_alerts_sent == 2
        assert state.initialized is True


class TestStateTransitions:
    """Test state mutation methods."""

    def test_reset_baselines(self):
        """reset_baselines sets all tracking points to the same value."""
        state = TrackerState()
        assert not state.initialized

        state.reset_baselines(80.0)

        assert state.initialized is True
        assert state.baseline_remaining == 80.0
        assert state.last_alert_tier == 0
        assert state.last_low_alert_remaining == 80.0
        assert state.last_check_remaining == 80.0
        assert state.last_check_time != ""

    def test_mark_check(self):
        """mark_check updates check tracking without touching alert tracking."""
        state = TrackerState()
        state.reset_baselines(80.0)

        state.mark_check(75.0)

        assert state.last_check_remaining == 75.0
        assert state.last_check_time != ""
        assert state.total_checks == 1  # reset_baselines doesn't count, mark_check is first
        # Alert tracking should NOT change
        assert state.baseline_remaining == 80.0
        assert state.last_alert_tier == 0

    def test_mark_alert_with_level(self):
        """mark_alert with a tier level updates last_alert_tier."""
        state = TrackerState()
        state.reset_baselines(80.0)

        state.mark_alert(70.0, tier=1)  # 8h alert

        assert state.last_low_alert_remaining == 70.0
        assert state.last_alert_tier == 1
        assert state.total_alerts_sent == 1

    def test_mark_alert_without_level(self):
        """mark_alert without level (low-usage) doesn't change last_alert_tier."""
        state = TrackerState()
        state.reset_baselines(80.0)
        state.last_alert_tier = 2  # simulate 16h already sent

        state.mark_alert(70.0)  # low-usage alert

        assert state.last_low_alert_remaining == 70.0
        assert state.last_alert_tier == 2  # unchanged
        assert state.total_alerts_sent == 1

    def test_mark_check_then_alert(self):
        """Simulate a full check cycle: check → alert."""
        state = TrackerState()
        state.reset_baselines(80.0)

        # Check finds 70% remaining
        state.mark_check(70.0)
        assert state.last_check_remaining == 70.0
        assert state.baseline_remaining == 80.0  # unchanged

        # Alert sent at 70%
        state.mark_alert(70.0, tier=1)
        assert state.last_alert_tier == 1
        assert state.total_alerts_sent == 1


class TestStateSerialization:
    """Test to_dict / from_dict."""

    def test_to_dict_contains_all_fields(self):
        state = TrackerState(baseline_remaining=50.0, initialized=True, total_checks=5)
        d = state.to_dict()
        assert "baseline_remaining" in d
        assert "last_alert_tier" in d
        assert "last_low_alert_remaining" in d
        assert "last_check_remaining" in d
        assert "last_check_time" in d
        assert "initialized" in d
        assert "total_checks" in d
        assert "total_alerts_sent" in d

    def test_from_dict_roundtrip(self):
        state = TrackerState(
            baseline_remaining=60.0,
            last_alert_tier=2,
            last_low_alert_remaining=60.0,
            last_check_remaining=55.0,
            last_check_time="2026-01-01T00:00:00+00:00",
            initialized=True,
            total_checks=100,
            total_alerts_sent=10,
        )
        d = state.to_dict()
        restored = TrackerState.from_dict(d)
        assert restored == state
