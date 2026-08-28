"""Tests for UsageTracker — progressive alert logic, threshold detection, regeneration handling.

This is the most important test file — it validates the heart of the plugin:
- First check baseline establishment (no alert)
- Regeneration suppression (total_consumed <= 0 → no alert)
- Progressive threshold crossing: 8h (4%) → 16h (8%) → 24h (12%)
- After 8h fires, next alert is 16h (NOT another 8h)
- Threshold skipping (consumed 12% in one check → 24h alert)
- Low usage per-percent tracking (below 12%)
- Custom message formatting
- Interval calculation (linear scaling)
- Restore time calculation
"""

from __future__ import annotations

from synthetic_usage_awareness.config import ServiceConfig
from synthetic_usage_awareness.state import TrackerState
from synthetic_usage_awareness.synthetic_client import UsageInfo
from synthetic_usage_awareness.usage_tracker import (
    AlertLevel,
    UsageTracker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_usage(percent: float) -> UsageInfo:
    """Create a UsageInfo with the given remaining percent."""
    return UsageInfo(
        percent_remaining=percent,
        max_credits="$132.00",
        remaining_credits=f"${percent / 100.0 * 132.0:.2f}",
        next_regen_credits="$2.64",
        next_regen_at="2026-07-31T00:00:00Z",
        raw={"weeklyTokenLimit": {"percentRemaining": percent}},
    )


def make_tracker(config=None, state=None):
    """Create a fresh UsageTracker."""
    cfg = config or ServiceConfig(
        api_key="syn_test",
        bot_token="123:ABC",
        chat_id="-100999",
        state_file="/tmp/test_sua.json",
    )
    return UsageTracker(cfg, state or TrackerState())


def initialized_tracker(initial_percent=100.0, config=None):
    """Create a tracker that has already done its first check."""
    tracker = make_tracker(config)
    tracker.evaluate(make_usage(initial_percent))
    assert tracker.state.initialized
    return tracker


# ---------------------------------------------------------------------------
# First check / baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    """Test first-check behavior — establishes baselines, no alerts."""

    def test_first_check_no_alert(self):
        """First check should return no alerts."""
        tracker = make_tracker()
        alerts = tracker.evaluate(make_usage(80.0))
        assert alerts == []
        assert tracker.state.initialized

    def test_first_check_sets_baselines(self):
        """First check sets all baseline values to current remaining."""
        tracker = make_tracker()
        tracker.evaluate(make_usage(75.0))
        assert tracker.state.baseline_remaining == 75.0
        assert tracker.state.last_low_alert_remaining == 75.0
        assert tracker.state.last_check_remaining == 75.0
        assert tracker.state.last_alert_tier == 0
        assert tracker.state.initialized is True

    def test_first_check_at_0_percent(self):
        """First check at 0% should still set baselines without alerting."""
        tracker = make_tracker()
        alerts = tracker.evaluate(make_usage(0.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 0.0


# ---------------------------------------------------------------------------
# Regeneration suppression
# ---------------------------------------------------------------------------


class TestRegenerationSuppression:
    """Test that regenerated quota doesn't trigger false alerts."""

    def test_no_alert_when_regenerated_back(self):
        """If remaining regenerates back to baseline, no alert."""
        tracker = initialized_tracker(80.0)
        # Usage regenerates back to 80% (same as baseline)
        alerts = tracker.evaluate(make_usage(80.0))
        assert alerts == []

    def test_no_alert_when_regenerated_above(self):
        """If remaining regenerates above baseline, no alert."""
        tracker = initialized_tracker(70.0)
        # Regenerated to 75% (above 70% baseline)
        alerts = tracker.evaluate(make_usage(75.0))
        assert alerts == []
        # Baselines should be reset to the new higher value
        assert tracker.state.baseline_remaining == 75.0
        assert tracker.state.last_alert_tier == 0

    def test_usage_then_regen_then_usage_still_tracks(self):
        """After regeneration resets baselines, subsequent usage is tracked from new baseline."""
        tracker = initialized_tracker(80.0)

        # Use 8% → 72%
        alerts = tracker.evaluate(make_usage(72.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H  # 8% consumed → 16h alert
        assert tracker.state.baseline_remaining == 80.0  # baseline unchanged
        assert tracker.state.last_alert_tier == 2

        # Regenerate back to 80%
        alerts = tracker.evaluate(make_usage(80.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 80.0
        assert tracker.state.last_alert_tier == 0  # reset

        # Use 4% → 76%
        alerts = tracker.evaluate(make_usage(76.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H  # 4% → 8h

    def test_small_usage_within_regen_no_alert(self):
        """Small usage that's covered by ongoing regeneration should not alert."""
        tracker = initialized_tracker(90.0)
        # Use 2% — less than the 4% (8h) threshold
        alerts = tracker.evaluate(make_usage(88.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 90.0  # unchanged


# ---------------------------------------------------------------------------
# Progressive threshold crossing — 8h (4%) then 16h (8%) then 24h (12%)
# ---------------------------------------------------------------------------


class TestProgressiveThresholds:
    """Test progressive alerting: 8h → 16h → 24h (the core fix)."""

    def test_8h_then_16h_then_24h_progressive(self):
        """The key test: 4% → 8h alert, then 8% total → 16h alert, then 12% total → 24h alert."""
        tracker = initialized_tracker(100.0)

        # 4% consumed → 8h alert
        alerts = tracker.evaluate(make_usage(96.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H
        assert tracker.state.last_alert_tier == 1
        assert tracker.state.baseline_remaining == 100.0  # baseline stays

        # 8% total consumed (4% more) → should be 16h, NOT another 8h
        alerts = tracker.evaluate(make_usage(92.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H
        assert tracker.state.last_alert_tier == 2
        assert tracker.state.baseline_remaining == 100.0  # baseline still stays

        # 12% total consumed (4% more) → should be 24h
        alerts = tracker.evaluate(make_usage(88.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert tracker.state.last_alert_tier == 3

    def test_no_repeated_8h_alert(self):
        """After 8h fires, another 4% drop should NOT produce another 8h."""
        tracker = initialized_tracker(80.0)

        alerts = tracker.evaluate(make_usage(76.0))  # 4% drop
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

        alerts = tracker.evaluate(make_usage(72.0))  # another 4% drop (8% total)
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H  # 16h, NOT 8h

    def test_no_alert_between_thresholds(self):
        """After 8h fires, a small drop below 16h threshold produces no alert."""
        tracker = initialized_tracker(80.0)

        tracker.evaluate(make_usage(76.0))  # 4% → 8h alert
        assert tracker.state.last_alert_tier == 1

        # 6% total consumed — above 8h (4%) but below 16h (8%)
        alerts = tracker.evaluate(make_usage(74.0))
        assert alerts == []  # no alert — waiting for 16h threshold

    def test_baseline_preserved_across_alerts(self):
        """Baseline_remaining should NOT reset after each alert."""
        tracker = initialized_tracker(100.0)

        tracker.evaluate(make_usage(96.0))  # 8h alert
        assert tracker.state.baseline_remaining == 100.0

        tracker.evaluate(make_usage(92.0))  # 16h alert
        assert tracker.state.baseline_remaining == 100.0

    def test_consumed_shows_total_from_baseline(self):
        """The consumed value in alerts should be total from baseline, not from last alert."""
        tracker = initialized_tracker(100.0)

        alerts = tracker.evaluate(make_usage(96.0))
        assert alerts[0].consumed == 4.0  # 100 - 96

        alerts = tracker.evaluate(make_usage(92.0))
        assert alerts[0].consumed == 8.0  # 100 - 92, NOT 96 - 92 = 4


# ---------------------------------------------------------------------------
# Threshold crossing — 8h (4%)
# ---------------------------------------------------------------------------


class TestThreshold8h:
    """Test 8-hour worth (4%) threshold crossing."""

    def test_alert_at_exactly_4_percent(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(76.0))  # 80 - 76 = 4%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H
        assert alerts[0].consumed == 4.0
        assert alerts[0].remaining == 76.0

    def test_alert_just_above_4_percent(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(75.9))  # 4.1%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

    def test_no_alert_just_below_4_percent(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(76.1))  # 3.9%
        assert alerts == []

    def test_alert_advances_level(self):
        """After 8h alert, last_alert_tier should be 1."""
        tracker = initialized_tracker(80.0)
        tracker.evaluate(make_usage(76.0))
        assert tracker.state.last_alert_tier == 1
        assert tracker.state.baseline_remaining == 80.0  # baseline preserved


# ---------------------------------------------------------------------------
# Threshold crossing — 16h (8%)
# ---------------------------------------------------------------------------


class TestThreshold16h:
    """Test 16-hour worth (8%) threshold crossing."""

    def test_alert_at_exactly_8_percent(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(72.0))  # 8%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H
        assert alerts[0].consumed == 8.0

    def test_alert_above_8_below_12(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(71.0))  # 9%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H

    def test_8h_alert_for_7_percent(self):
        """7% consumed is above the 4% threshold, triggers 8h alert (not 16h)."""
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(73.0))  # 7% consumed
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

    def test_16h_takes_priority_over_8h(self):
        """When 8% is consumed in one jump, only the 16h alert should fire (not both)."""
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(72.0))  # 8% → 16h
        assert len(alerts) == 1  # Only one alert, not two
        assert alerts[0].level == AlertLevel.AWAKE_16H

    def test_16h_only_after_8h(self):
        """After 8h fires, 16h requires 8% total consumed from baseline."""
        tracker = initialized_tracker(80.0)

        # 4% → 8h alert
        tracker.evaluate(make_usage(76.0))
        assert tracker.state.last_alert_tier == 1

        # 7% total — above 8h (4%) but below 16h (8%) → no alert
        alerts = tracker.evaluate(make_usage(73.0))
        assert alerts == []

        # 8% total → 16h alert
        alerts = tracker.evaluate(make_usage(72.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H


# ---------------------------------------------------------------------------
# Threshold crossing — 24h (12%)
# ---------------------------------------------------------------------------


class TestThreshold24h:
    """Test 24-hour worth (12%) threshold crossing."""

    def test_alert_at_exactly_12_percent(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(68.0))  # 12%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert alerts[0].consumed == 12.0

    def test_alert_above_12(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(67.0))  # 13%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H

    def test_24h_takes_priority_over_lower(self):
        """When 12% is consumed, only the 24h alert fires."""
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(68.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H

    def test_threshold_skip_from_4_to_12(self):
        """Jumping from 0% consumed to 12% should only produce 24h alert."""
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(68.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H

    def test_threshold_skip_from_4_to_15(self):
        """Jumping to 15% consumed should produce 24h alert (highest applicable)."""
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(65.0))  # 15%
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert alerts[0].consumed == 15.0

    def test_24h_resets_cycle(self):
        """After 24h fires, the cycle resets — next 4% triggers a new 8h alert."""
        tracker = initialized_tracker(80.0)

        # 12% consumed → 24h alert
        alerts = tracker.evaluate(make_usage(68.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert tracker.state.last_alert_tier == 3

        # Next check — cycle resets (baseline → 68, level → 0)
        alerts = tracker.evaluate(make_usage(68.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 68.0
        assert tracker.state.last_alert_tier == 0

        # 4% from new baseline → new 8h alert
        alerts = tracker.evaluate(make_usage(64.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H


# ---------------------------------------------------------------------------
# Low usage per-percent tracking
# ---------------------------------------------------------------------------


class TestLowUsageTracking:
    """Test per-percent tracking when remaining < low_usage_threshold (12%)."""

    def test_low_usage_alert_at_1_percent_drop(self):
        """Below 12%, every 1% drop should alert."""
        tracker = initialized_tracker(13.0)
        # Drop from 13% to 12% (still >= 12, so no low alert yet)
        alerts = tracker.evaluate(make_usage(12.0))
        # 12.0 is not < 12.0 (threshold), so it's in normal territory
        # 13 - 12 = 1% consumed, below 4% threshold → no alert
        assert alerts == []

    def test_low_usage_alert_below_threshold(self):
        """When remaining drops below 12%, per-percent tracking activates."""
        tracker = initialized_tracker(12.0)
        # Baseline at 12%, now drop to 10% (2% drop, below threshold)
        alerts = tracker.evaluate(make_usage(10.0))
        # 10% < 12% (low threshold), drop >= 1% → low usage alert
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.LOW_USAGE

    def test_low_usage_every_percent(self):
        """Each 1% drop below threshold produces a separate alert."""
        tracker = initialized_tracker(12.0)
        # Note: 12.0 is NOT below 12.0, so we need to start below
        tracker.state.baseline_remaining = 11.0
        tracker.state.last_low_alert_remaining = 11.0

        alerts = tracker.evaluate(make_usage(10.0))  # 1% drop
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.LOW_USAGE

        alerts = tracker.evaluate(make_usage(9.0))  # another 1% drop
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.LOW_USAGE

        alerts = tracker.evaluate(make_usage(8.0))  # another 1% drop
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.LOW_USAGE

    def test_low_usage_no_alert_without_drop(self):
        """If remaining stays the same below threshold, no alert."""
        tracker = initialized_tracker(10.0)
        tracker.state.baseline_remaining = 10.0
        tracker.state.last_low_alert_remaining = 10.0

        alerts = tracker.evaluate(make_usage(10.0))  # no change
        assert alerts == []

    def test_low_usage_regen_below_threshold(self):
        """If remaining regenerates below threshold, no alert."""
        tracker = initialized_tracker(8.0)
        tracker.state.baseline_remaining = 8.0
        tracker.state.last_low_alert_remaining = 8.0

        # Regenerate to 9%
        alerts = tracker.evaluate(make_usage(9.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 9.0

    def test_low_usage_threshold_crossing(self):
        """If usage drops fast below threshold, threshold alerts also fire."""
        tracker = initialized_tracker(15.0)
        # Drop to 3% (12% consumed — crosses 24h threshold AND is below low threshold)
        alerts = tracker.evaluate(make_usage(3.0))
        # Should get at least one alert — either LOW_USAGE or FULL_DAY_24H
        assert len(alerts) >= 1
        # The 24h threshold (12%) is crossed
        levels = [a.level for a in alerts]
        assert AlertLevel.FULL_DAY_24H in levels or AlertLevel.LOW_USAGE in levels


# ---------------------------------------------------------------------------
# Custom message formatting
# ---------------------------------------------------------------------------


class TestMessageFormatting:
    """Test alert message content."""

    def test_8h_message_contains_remaining(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(76.0))
        assert "76.0%" in alerts[0].message

    def test_16h_message_contains_consumed(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(72.0))
        assert "8.0%" in alerts[0].message

    def test_24h_message_contains_restore_time(self):
        tracker = initialized_tracker(80.0)
        alerts = tracker.evaluate(make_usage(68.0))
        # 32% needed, 0.5%/hour → 64 hours
        assert "64.0h" in alerts[0].message
        assert "2.7 days" in alerts[0].message

    def test_low_message_contains_interval(self):
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
        )
        tracker = make_tracker(cfg)
        tracker.state.reset_baselines(10.0)
        tracker.state.baseline_remaining = 10.0
        tracker.state.last_low_alert_remaining = 10.0

        alerts = tracker.evaluate(make_usage(8.0))
        assert len(alerts) == 1
        assert "1 min" in alerts[0].message  # interval at 8% should be ~1 min

    def test_custom_message_template(self):
        """Custom message templates are used when configured."""
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
            msg_8h="CUSTOM: {remaining:.1f}% left, {consumed:.1f}% used",
        )
        tracker = make_tracker(cfg)
        tracker.evaluate(make_usage(80.0))  # baseline
        alerts = tracker.evaluate(make_usage(76.0))  # 4% consumed
        assert len(alerts) == 1
        assert alerts[0].message == "CUSTOM: 76.0% left, 4.0% used"

    def test_message_says_total_consumed(self):
        """Messages should say 'Total consumed', not 'Consumed since last alert'."""
        tracker = initialized_tracker(100.0)
        alerts = tracker.evaluate(make_usage(96.0))
        assert "Total consumed" in alerts[0].message
        assert "Consumed since last alert" not in alerts[0].message


# ---------------------------------------------------------------------------
# Interval calculation
# ---------------------------------------------------------------------------


class TestIntervalCalculation:
    """Test calculate_monitor_interval — linear scaling with remaining quota."""

    def test_interval_at_100_percent(self):
        tracker = make_tracker()
        assert tracker.calculate_monitor_interval(100.0) == 10.0  # normal interval

    def test_interval_at_low_threshold(self):
        tracker = make_tracker()
        # At exactly 12% (threshold), should be low_interval
        assert tracker.calculate_monitor_interval(12.0) == 1.0

    def test_interval_below_threshold(self):
        tracker = make_tracker()
        assert tracker.calculate_monitor_interval(5.0) == 1.0
        assert tracker.calculate_monitor_interval(0.0) == 1.0

    def test_interval_at_midpoint(self):
        """At 56% (midpoint between 12 and 100), interval should be ~5.5 min."""
        tracker = make_tracker()
        interval = tracker.calculate_monitor_interval(56.0)
        # 1 + (56-12)/(100-12) * 9 = 1 + 44/88 * 9 = 1 + 4.5 = 5.5
        assert abs(interval - 5.5) < 0.01

    def test_interval_scales_linearly(self):
        """Interval should increase linearly from low_threshold to 100%."""
        tracker = make_tracker()
        intervals = [tracker.calculate_monitor_interval(p) for p in range(12, 101)]
        # Check monotonic increase
        for i in range(1, len(intervals)):
            assert intervals[i] >= intervals[i - 1]

    def test_custom_intervals(self):
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
            normal_interval_min=20.0,
            low_interval_min=2.0,
            low_usage_threshold_percent=20.0,
        )
        tracker = make_tracker(cfg)
        assert tracker.calculate_monitor_interval(100.0) == 20.0
        assert tracker.calculate_monitor_interval(20.0) == 2.0
        assert tracker.calculate_monitor_interval(10.0) == 2.0
        # At 60% (midpoint): 2 + (60-20)/(100-20) * 18 = 2 + 40/80 * 18 = 2 + 9 = 11
        assert abs(tracker.calculate_monitor_interval(60.0) - 11.0) < 0.01


# ---------------------------------------------------------------------------
# Restore time calculation
# ---------------------------------------------------------------------------


class TestRestoreTime:
    """Test calculate_restore_time."""

    def test_restore_from_50_percent(self):
        tracker = make_tracker()
        # 50% needed, 0.5%/hour → 100 hours
        result = tracker.calculate_restore_time(50.0)
        assert result["hours"] == 100.0
        assert result["days"] == 4.2  # 100/24 ≈ 4.17 → rounded to 4.2

    def test_restore_from_100_percent(self):
        tracker = make_tracker()
        result = tracker.calculate_restore_time(100.0)
        assert result["hours"] == 0.0
        assert result["days"] == 0.0

    def test_restore_from_0_percent(self):
        tracker = make_tracker()
        result = tracker.calculate_restore_time(0.0)
        # 100% needed, 0.5%/hour → 200 hours
        assert result["hours"] == 200.0
        assert result["days"] == 8.3  # 200/24 ≈ 8.33 → 8.3

    def test_restore_with_custom_regen(self):
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
            regen_percent=5.0,
            regen_interval_hours=1.0,
        )
        tracker = make_tracker(cfg)
        # 50% needed, 5%/hour → 10 hours
        result = tracker.calculate_restore_time(50.0)
        assert result["hours"] == 10.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_repeated_no_change(self):
        """Multiple checks with no change produce no alerts."""
        tracker = initialized_tracker(80.0)
        for _ in range(5):
            alerts = tracker.evaluate(make_usage(80.0))
            assert alerts == []

    def test_large_drop_then_regen(self):
        """Large drop → alert → regeneration → no alert → usage → alert."""
        tracker = initialized_tracker(90.0)

        # Drop 12% → 78%
        alerts = tracker.evaluate(make_usage(78.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert tracker.state.last_alert_tier == 3
        # Baseline stays at 90 (not reset to 78)
        assert tracker.state.baseline_remaining == 90.0

        # Next check: cycle resets (level >= 3)
        alerts = tracker.evaluate(make_usage(78.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 78.0
        assert tracker.state.last_alert_tier == 0

        # Regenerate to 88%
        alerts = tracker.evaluate(make_usage(88.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 88.0
        assert tracker.state.last_alert_tier == 0

        # Drop 4% → 84%
        alerts = tracker.evaluate(make_usage(84.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

    def test_slow_drain_no_threshold_crossed(self):
        """Small repeated usage that never crosses 4% threshold."""
        tracker = initialized_tracker(90.0)
        # 1% drop each time — never reaches 4% threshold
        for percent in [89.0, 88.0, 87.0]:
            alerts = tracker.evaluate(make_usage(percent))
            assert alerts == []
            # baseline stays at 90 because we never alerted
        assert tracker.state.baseline_remaining == 90.0

    def test_slow_drain_then_threshold(self):
        """Small drops accumulate then cross 4% threshold."""
        tracker = initialized_tracker(90.0)
        tracker.evaluate(make_usage(89.0))  # 1% — no alert
        tracker.evaluate(make_usage(88.0))  # 2% — no alert
        tracker.evaluate(make_usage(87.0))  # 3% — no alert
        alerts = tracker.evaluate(make_usage(86.0))  # 4% — alert!
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

    def test_zero_remaining_alert(self):
        """Reaching 0% should trigger appropriate alerts."""
        tracker = initialized_tracker(10.0)
        tracker.state.baseline_remaining = 10.0
        tracker.state.last_low_alert_remaining = 10.0
        # Drop to 0% — 10% consumed, crosses 8h and 16h but not 24h (12%)
        alerts = tracker.evaluate(make_usage(0.0))
        # 10% consumed → 16h threshold (8%)
        assert len(alerts) >= 1
        levels = [a.level for a in alerts]
        # Should be either AWAKE_16H or LOW_USAGE (since 0% < 12%)
        assert AlertLevel.AWAKE_16H in levels or AlertLevel.LOW_USAGE in levels

    def test_configurable_thresholds(self):
        """Custom threshold values work correctly with progressive logic."""
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
            threshold_8h_percent=2.0,
            threshold_16h_percent=4.0,
            threshold_24h_percent=6.0,
        )
        tracker = make_tracker(cfg)
        tracker.evaluate(make_usage(80.0))  # baseline
        # 2% drop → 8h threshold
        alerts = tracker.evaluate(make_usage(78.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.SLEEP_8H

        # 4% total from baseline → 16h (progressive: not another 8h)
        alerts = tracker.evaluate(make_usage(76.0))
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.AWAKE_16H

    def test_full_cycle_with_custom_thresholds(self):
        """Complete 8h → 16h → 24h cycle with custom thresholds."""
        cfg = ServiceConfig(
            api_key="syn_test",
            bot_token="123:ABC",
            chat_id="-100999",
            state_file="/tmp/test_sua.json",
            threshold_8h_percent=2.0,
            threshold_16h_percent=4.0,
            threshold_24h_percent=6.0,
        )
        tracker = make_tracker(cfg)
        tracker.evaluate(make_usage(80.0))  # baseline

        # 2% → 8h
        alerts = tracker.evaluate(make_usage(78.0))
        assert alerts[0].level == AlertLevel.SLEEP_8H
        assert tracker.state.last_alert_tier == 1

        # 4% total → 16h
        alerts = tracker.evaluate(make_usage(76.0))
        assert alerts[0].level == AlertLevel.AWAKE_16H
        assert tracker.state.last_alert_tier == 2

        # 6% total → 24h
        alerts = tracker.evaluate(make_usage(74.0))
        assert alerts[0].level == AlertLevel.FULL_DAY_24H
        assert tracker.state.last_alert_tier == 3

        # Cycle resets on next check
        alerts = tracker.evaluate(make_usage(74.0))
        assert alerts == []
        assert tracker.state.baseline_remaining == 74.0
        assert tracker.state.last_alert_tier == 0
