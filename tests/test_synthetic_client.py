"""Tests for SyntheticClient and MockSyntheticClient.

Tests cover:
- Response parsing
- Mock client usage simulation
- Mock client time-based regeneration
- Edge cases (0%, 100%, over-regeneration cap)
"""

from __future__ import annotations

from datetime import UTC, datetime

from synthetic_usage_awareness.synthetic_client import (
    MockSyntheticClient,
    UsageInfo,
    _parse_quota_response,
)

# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestParseQuotaResponse:
    """Test _parse_quota_response with various API response shapes."""

    def test_full_response(self):
        """Parse a complete API response."""
        data = {
            "subscription": {"limit": 2750, "requests": 0, "renewsAt": "2026-07-31T02:28:09Z"},
            "weeklyTokenLimit": {
                "nextRegenAt": "2026-07-30T22:18:31Z",
                "percentRemaining": 95.99,
                "maxCredits": "$132.00",
                "remainingCredits": "$126.71",
                "nextRegenCredits": "$2.64",
            },
            "rollingFiveHourLimit": {"remaining": 2743.6, "max": 2750, "limited": False},
        }
        info = _parse_quota_response(data)
        assert info.percent_remaining == 95.99
        assert info.max_credits == "$132.00"
        assert info.remaining_credits == "$126.71"
        assert info.next_regen_credits == "$2.64"
        assert info.next_regen_at == "2026-07-30T22:18:31Z"
        assert info.raw == data

    def test_missing_weekly_token_limit(self):
        """Response without weeklyTokenLimit defaults to 0."""
        data = {"subscription": {"limit": 100, "requests": 50}}
        info = _parse_quota_response(data)
        assert info.percent_remaining == 0.0
        assert info.max_credits == "$0.00"

    def test_partial_weekly_token_limit(self):
        """Response with partial weeklyTokenLimit."""
        data = {"weeklyTokenLimit": {"percentRemaining": 42.0}}
        info = _parse_quota_response(data)
        assert info.percent_remaining == 42.0
        assert info.max_credits == "$0.00"
        assert info.remaining_credits == "$0.00"

    def test_response_with_string_percent(self):
        """percentRemaining as string should be coerced to float."""
        data = {"weeklyTokenLimit": {"percentRemaining": "50.5"}}
        info = _parse_quota_response(data)
        assert info.percent_remaining == 50.5


# ---------------------------------------------------------------------------
# MockSyntheticClient — usage simulation
# ---------------------------------------------------------------------------


class TestMockClientUsage:
    """Test MockSyntheticClient usage consumption."""

    def test_initial_percent(self):
        mock = MockSyntheticClient(initial_percent=80.0)
        info = mock.get_usage()
        assert info.percent_remaining == 80.0

    def test_simulate_usage(self):
        mock = MockSyntheticClient(initial_percent=100.0)
        mock.simulate_usage(10.0)
        assert mock.get_usage().percent_remaining == 90.0

    def test_simulate_usage_multiple(self):
        mock = MockSyntheticClient(initial_percent=100.0)
        mock.simulate_usage(5.0)
        mock.simulate_usage(3.0)
        assert mock.get_usage().percent_remaining == 92.0

    def test_simulate_usage_below_zero_clamped(self):
        mock = MockSyntheticClient(initial_percent=10.0)
        mock.simulate_usage(20.0)  # Would go to -10
        assert mock.get_usage().percent_remaining == 0.0

    def test_set_percent(self):
        mock = MockSyntheticClient(initial_percent=100.0)
        mock.set_percent(42.5)
        assert mock.get_usage().percent_remaining == 42.5

    def test_set_percent_clamped(self):
        mock = MockSyntheticClient(initial_percent=50.0)
        mock.set_percent(150.0)
        assert mock.get_usage().percent_remaining == 100.0
        mock.set_percent(-10.0)
        assert mock.get_usage().percent_remaining == 0.0


# ---------------------------------------------------------------------------
# MockSyntheticClient — time-based regeneration
# ---------------------------------------------------------------------------


class TestMockClientRegeneration:
    """Test MockSyntheticClient regeneration over simulated time."""

    def test_regen_one_interval(self):
        """After 4 hours (one interval), should regenerate 2%."""
        mock = MockSyntheticClient(
            initial_percent=80.0, regen_percent=2.0, regen_interval_hours=4.0
        )
        mock.advance_time(hours=4.0)
        assert mock.get_usage().percent_remaining == 82.0

    def test_regen_multiple_intervals(self):
        """After 8 hours (two intervals), should regenerate 4%."""
        mock = MockSyntheticClient(
            initial_percent=50.0, regen_percent=2.0, regen_interval_hours=4.0
        )
        mock.advance_time(hours=8.0)
        assert mock.get_usage().percent_remaining == 54.0

    def test_regen_partial_interval(self):
        """After 2 hours (half interval), should regenerate 1%."""
        mock = MockSyntheticClient(
            initial_percent=80.0, regen_percent=2.0, regen_interval_hours=4.0
        )
        mock.advance_time(hours=2.0)
        assert mock.get_usage().percent_remaining == 81.0

    def test_regen_caps_at_100(self):
        """Regeneration cannot exceed 100%."""
        mock = MockSyntheticClient(
            initial_percent=99.0, regen_percent=2.0, regen_interval_hours=4.0
        )
        mock.advance_time(hours=4.0)
        assert mock.get_usage().percent_remaining == 100.0

    def test_regen_after_usage(self):
        """Use some quota, then regenerate."""
        mock = MockSyntheticClient(initial_percent=80.0)
        mock.simulate_usage(10.0)  # → 70%
        mock.advance_time(hours=4.0)  # regen 2% → 72%
        assert mock.get_usage().percent_remaining == 72.0

    def test_regen_multiple_cycles_with_usage(self):
        """Simulate realistic usage + regeneration cycle."""
        mock = MockSyntheticClient(
            initial_percent=100.0, regen_percent=2.0, regen_interval_hours=4.0
        )

        # Use 12% (full day worth)
        mock.simulate_usage(12.0)  # → 88%
        assert mock.get_usage().percent_remaining == 88.0

        # Wait 4 hours → regen 2%
        mock.advance_time(hours=4.0)  # → 90%
        assert mock.get_usage().percent_remaining == 90.0

        # Use 4% more
        mock.simulate_usage(4.0)  # → 86%
        assert mock.get_usage().percent_remaining == 86.0

        # Wait 8 hours → regen 4%
        mock.advance_time(hours=8.0)  # → 90%
        assert mock.get_usage().percent_remaining == 90.0

    def test_set_time_advances_regen(self):
        """set_time() also applies regeneration."""
        mock = MockSyntheticClient(initial_percent=80.0)
        mock.set_time(datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC))
        mock.set_time(datetime(2026, 7, 31, 16, 0, 0, tzinfo=UTC))  # +4h
        assert mock.get_usage().percent_remaining == 82.0

    def test_zero_time_advance_no_regen(self):
        """Advancing 0 hours should not regenerate."""
        mock = MockSyntheticClient(initial_percent=80.0)
        mock.advance_time(hours=0.0)
        assert mock.get_usage().percent_remaining == 80.0

    def test_custom_regen_params(self):
        """Mock with custom regeneration parameters."""
        mock = MockSyntheticClient(
            initial_percent=50.0, regen_percent=5.0, regen_interval_hours=1.0
        )
        mock.advance_time(hours=2.0)  # 2 intervals → +10%
        assert mock.get_usage().percent_remaining == 60.0


# ---------------------------------------------------------------------------
# UsageInfo dataclass
# ---------------------------------------------------------------------------


class TestUsageInfo:
    """Test UsageInfo dataclass behavior."""

    def test_immutable(self):
        info = UsageInfo(
            percent_remaining=50.0,
            max_credits="$132.00",
            remaining_credits="$66.00",
            next_regen_credits="$2.64",
            next_regen_at="2026-07-31T00:00:00Z",
            raw={},
        )
        try:
            info.percent_remaining = 60.0
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

    def test_raw_preserved(self):
        raw = {"test": "data", "nested": {"key": "value"}}
        info = UsageInfo(
            percent_remaining=50.0,
            max_credits="$100",
            remaining_credits="$50",
            next_regen_credits="$2",
            next_regen_at="",
            raw=raw,
        )
        assert info.raw == raw
