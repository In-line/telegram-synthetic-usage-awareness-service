"""Tests for UsageMonitor — background monitoring, check cycles, error handling."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from synthetic_usage_awareness.config import ServiceConfig
from synthetic_usage_awareness.monitor import UsageMonitor
from synthetic_usage_awareness.notifier import MockNotifier
from synthetic_usage_awareness.state import TrackerState
from synthetic_usage_awareness.synthetic_client import MockSyntheticClient, UsageInfo
from synthetic_usage_awareness.usage_tracker import AlertLevel, UsageTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_monitor(
    config=None,
    client=None,
    notifier=None,
    state=None,
    tmp_state_file=None,
):
    """Build a UsageMonitor with test doubles."""
    cfg = config or ServiceConfig(
        api_key="syn_test",
        bot_token="123:ABC",
        chat_id="-100999",
        state_file=tmp_state_file or "/tmp/test_monitor_state.json",
        normal_interval_min=0.01,  # Fast for testing
        low_interval_min=0.01,
    )
    cli = client or MockSyntheticClient(initial_percent=80.0)
    notif = notifier or MockNotifier()
    st = state or TrackerState()

    return UsageMonitor(
        config=cfg,
        client=cli,
        tracker=UsageTracker(cfg, st),
        notifier=notif,
        state=st,
    )


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestMonitorLifecycle:
    """Test start/stop lifecycle."""

    def test_start_creates_thread(self):
        monitor = make_monitor()
        assert not monitor.is_running
        monitor.start()
        assert monitor.is_running
        monitor.stop(timeout=2.0)
        assert not monitor.is_running

    def test_start_when_already_running(self):
        """Starting twice doesn't create a second thread."""
        monitor = make_monitor()
        monitor.start()
        thread1 = monitor._thread
        monitor.start()  # Should be a no-op
        assert monitor._thread is thread1
        monitor.stop(timeout=2.0)

    def test_stop_is_idempotent(self):
        monitor = make_monitor()
        monitor.stop()  # No-op if not started
        monitor.stop()  # Still no-op

    def test_daemon_thread(self):
        """Monitor thread should be a daemon."""
        monitor = make_monitor()
        monitor.start()
        assert monitor._thread.daemon is True
        monitor.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# Single check cycle
# ---------------------------------------------------------------------------


class TestCheckCycle:
    """Test the _check_once method."""

    def test_first_check_establishes_baseline(self, tmp_path):
        """First check sets baselines and sends no alerts."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=80.0)
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        monitor.check_now()

        assert monitor.state.initialized
        assert monitor.state.last_check_remaining == 80.0
        assert mock_notifier.count == 0
        assert os.path.exists(state_file)

    def test_check_sends_alert_on_threshold_crossing(self, tmp_path):
        """Check cycle sends alert when threshold is crossed."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=80.0)
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        # First check — baseline
        monitor.check_now()
        assert mock_notifier.count == 0

        # Simulate 4% usage
        mock_client.simulate_usage(4.0)
        monitor.check_now()

        assert mock_notifier.count == 1
        sent_alert = mock_notifier.sent[0]
        assert sent_alert.level == AlertLevel.SLEEP_8H

    def test_check_sends_multiple_alerts_on_fast_drop(self, tmp_path):
        """Fast drop crossing multiple thresholds sends at least one alert."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=80.0)
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        # Baseline
        monitor.check_now()

        # Drop 12% (24h threshold)
        mock_client.simulate_usage(12.0)
        monitor.check_now()

        assert mock_notifier.count == 1
        assert mock_notifier.sent[0].level == AlertLevel.FULL_DAY_24H

    def test_state_persisted_after_check(self, tmp_path):
        """State file is written after each check."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=75.0)
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
        )

        monitor.check_now()

        saved = json.loads(Path(state_file).read_text())
        assert saved["initialized"] is True
        assert saved["last_check_remaining"] == 75.0
        # reset_baselines sets total_checks=0, then mark_check increments to 1
        assert saved["total_checks"] == 1

    def test_on_check_callback(self, tmp_path):
        """_on_check callback is invoked with UsageInfo."""
        monitor = make_monitor(tmp_state_file=str(tmp_path / "state.json"))
        received = []
        monitor.set_on_check(lambda usage: received.append(usage))
        monitor.check_now()
        assert len(received) == 1
        assert isinstance(received[0], UsageInfo)

    def test_on_alert_callback(self, tmp_path):
        """_on_alert callback is invoked for each alert."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=80.0)
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
        )
        received_alerts = []
        monitor.set_on_alert(lambda alert: received_alerts.append(alert))

        monitor.check_now()  # baseline
        mock_client.simulate_usage(4.0)
        monitor.check_now()  # alert

        assert len(received_alerts) == 1
        assert received_alerts[0].level == AlertLevel.SLEEP_8H


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error handling in check cycles."""

    def test_api_failure_handled_gracefully(self, tmp_path):
        """API failure doesn't crash the monitor."""
        state_file = str(tmp_path / "state.json")

        failing_client = MagicMock()
        failing_client.get_usage.side_effect = RuntimeError("API down")

        monitor = make_monitor(
            tmp_state_file=state_file,
            client=failing_client,
        )

        # Should not raise
        monitor.check_now()

        # State should still be saved
        assert os.path.exists(state_file)

    def test_notifier_failure_doesnt_crash(self, tmp_path):
        """Notifier failure doesn't crash the check cycle."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=80.0)

        failing_notifier = MagicMock()
        failing_notifier.send_alert.return_value = False

        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=failing_notifier,
        )

        monitor.check_now()  # baseline
        mock_client.simulate_usage(4.0)
        monitor.check_now()  # alert attempt

        # Should not crash, and state should still be saved
        assert os.path.exists(state_file)
        assert failing_notifier.send_alert.call_count == 1


# ---------------------------------------------------------------------------
# Interval calculation in monitor context
# ---------------------------------------------------------------------------


class TestMonitorInterval:
    """Test that the monitor uses the correct sleep interval."""

    def test_interval_at_high_usage(self):
        """At 90% remaining, interval should be ~8.98 min with default config."""
        from synthetic_usage_awareness.config import ServiceConfig

        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
        )
        monitor = make_monitor(config=cfg)
        monitor.state.last_check_remaining = 90.0
        interval = monitor.tracker.calculate_monitor_interval(90.0)
        # 90% → 1 + (90-12)/(100-12) * 9 = 1 + 78/88 * 9 ≈ 8.98
        assert abs(interval - 8.98) < 0.1

    def test_interval_at_low_usage(self):
        """Below 12% remaining, interval should be 1 min with default config."""
        from synthetic_usage_awareness.config import ServiceConfig

        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
        )
        monitor = make_monitor(config=cfg)
        monitor.state.last_check_remaining = 5.0
        interval = monitor.tracker.calculate_monitor_interval(5.0)
        assert interval == 1.0  # Below threshold → 1 min


# ---------------------------------------------------------------------------
# Integration: full cycle with mock client
# ---------------------------------------------------------------------------


class TestIntegrationCycle:
    """Integration tests with MockSyntheticClient simulating real usage patterns."""

    def test_realistic_usage_pattern(self, tmp_path):
        """Simulate a realistic day of usage and verify alerts."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=100.0)
        # Pin the simulated clock: without this, get_usage() applies real
        # wall-clock regeneration between checks, so exact-boundary floats
        # (e.g. 96.0) drift by microseconds and asserts flake on slow CI.
        mock_client.set_time(datetime.now(UTC))
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        # Baseline check
        monitor.check_now()
        assert mock_notifier.count == 0

        # Use 4% (8h worth)
        mock_client.simulate_usage(4.0)
        monitor.check_now()
        assert mock_notifier.count == 1
        assert mock_notifier.sent[0].level == AlertLevel.SLEEP_8H

        # Regenerate 2% (4 hours pass)
        mock_client.advance_time(hours=4.0)
        monitor.check_now()
        assert mock_notifier.count == 1  # No new alert (regenerated)

        # Use 4% more — from 98%, drop to 94%
        # total_consumed from baseline(100) = 6%, above 8h(4%) but below 16h(8%)
        # Since 8h already fired (tier=1), no new alert
        mock_client.simulate_usage(4.0)
        monitor.check_now()
        assert mock_notifier.count == 1  # No new alert (between 8h and 16h thresholds)

    def test_sleep_cycle_simulation(self, tmp_path):
        """Simulate 8 hours of sleep (no usage, full regeneration)."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=70.0)
        # Pin the simulated clock (see test_realistic_usage_pattern).
        mock_client.set_time(datetime.now(UTC))
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        # Baseline
        monitor.check_now()

        # Sleep 8 hours → regen 4%
        mock_client.advance_time(hours=8.0)
        monitor.check_now()

        # No alert (regenerated)
        assert mock_notifier.count == 0
        assert monitor.state.baseline_remaining == 74.0  # Reset to regenerated value

    def test_full_day_simulation(self, tmp_path):
        """Simulate a full day: use 12%, check at intervals."""
        state_file = str(tmp_path / "state.json")
        mock_client = MockSyntheticClient(initial_percent=100.0)
        # Pin the simulated clock (see test_realistic_usage_pattern) — this
        # test asserts exact floats (88.0) and flaked on CI with
        # 88.000004 from wall-clock regeneration between checks.
        mock_client.set_time(datetime.now(UTC))
        mock_notifier = MockNotifier()
        monitor = make_monitor(
            tmp_state_file=state_file,
            client=mock_client,
            notifier=mock_notifier,
        )

        # Baseline
        monitor.check_now()

        # Use 4% (morning)
        mock_client.simulate_usage(4.0)
        monitor.check_now()
        assert mock_notifier.count == 1
        assert mock_notifier.sent[0].level == AlertLevel.SLEEP_8H

        # Use 4% more (afternoon) — from 96%, use 4% → 92%
        # total_consumed = 8% → 16h alert (progressive: 8h already sent)
        mock_client.simulate_usage(4.0)
        monitor.check_now()
        assert mock_notifier.count == 2
        assert mock_notifier.sent[1].level == AlertLevel.AWAKE_16H

        # Use 4% more (evening) — from 92%, use 4% → 88%
        # total_consumed = 12% → 24h alert (progressive: 8h and 16h already sent)
        mock_client.simulate_usage(4.0)
        monitor.check_now()
        assert mock_notifier.count == 3
        assert mock_notifier.sent[2].level == AlertLevel.FULL_DAY_24H

        # Total: 12% used in 3 separate 4% chunks
        # Progressive alerts: 8h → 16h → 24h
        assert mock_client.get_usage().percent_remaining == 88.0
