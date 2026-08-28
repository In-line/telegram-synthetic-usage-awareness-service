"""Core usage tracking logic — progressive threshold detection and alert generation.

Design (progressive alerting):
1. Track baseline_remaining (quota % at the start of the current alert cycle).
2. total_consumed = baseline_remaining - current_remaining.
3. If total_consumed <= 0: quota regenerated back to or above the baseline
   → reset baselines (new cycle), no alert.
4. If current_remaining < low_usage_threshold:
   Alert every individual percent drop (track last_low_alert_remaining).
5. Else if total_consumed crosses the NEXT threshold above last_alert_level:
   8h (4%) → 16h (8%) → 24h (12%), send the corresponding alert and advance
   last_alert_level. After 24h fires, reset the cycle (new baseline).
6. Thresholds are progressive: after 8h fires, the next alert is 16h (not
   another 8h). This prevents repeated same-level alerts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from .config import ServiceConfig
from .state import TrackerState
from .synthetic_client import UsageInfo

logger = logging.getLogger("synthetic_usage_awareness.tracker")


class AlertLevel(Enum):
    """Severity / category of an alert."""

    NONE = "none"
    LOW_USAGE = "low_usage"
    SLEEP_8H = "8h"
    AWAKE_16H = "16h"
    FULL_DAY_24H = "24h"
    INFO = "info"  # non-alert informational (e.g. first check)


# Map AlertLevel to tier integer for state tracking
_TIER_MAP = {
    AlertLevel.SLEEP_8H: 1,
    AlertLevel.AWAKE_16H: 2,
    AlertLevel.FULL_DAY_24H: 3,
}


@dataclass(frozen=True)
class Alert:
    """An alert to be sent via Telegram."""

    level: AlertLevel
    message: str
    remaining: float
    consumed: float
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(self, "timestamp", datetime.now(UTC).isoformat())


class UsageTracker:
    """Evaluates current quota against progressive thresholds and generates alerts.

    This class is pure logic — no I/O, no network calls. It receives
    UsageInfo and returns a list of Alerts. The caller (UsageMonitor)
    is responsible for sending alerts and persisting state.
    """

    def __init__(self, config: ServiceConfig, state: TrackerState | None = None) -> None:
        self.config = config
        self.state = state or TrackerState()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def evaluate(self, usage: UsageInfo) -> list[Alert]:
        """Evaluate current usage and return any alerts to send.

        On the first call, establishes baselines and returns no alerts.
        On subsequent calls, checks progressive threshold crossings and
        low-usage tracking.
        """
        remaining = usage.percent_remaining
        alerts: list[Alert] = []

        # First check — establish baselines, no alerts
        if not self.state.initialized:
            self.state.reset_baselines(remaining)
            logger.info(f"Baseline established: remaining={remaining:.2f}%")
            return alerts

        # Get baseline for consumption calculation
        baseline = self.state.baseline_remaining
        if baseline is None:
            # Shouldn't happen if initialized, but guard anyway
            self.state.reset_baselines(remaining)
            return alerts

        total_consumed = baseline - remaining

        # --- Regeneration-aware suppression ---
        # If remaining has regenerated back to or above the baseline,
        # reset the alert cycle and don't alert.
        if total_consumed <= 0:
            logger.debug(
                f"Regeneration detected: remaining={remaining:.2f}% >= "
                f"baseline={baseline:.2f}% — resetting baselines"
            )
            self.state.reset_baselines(remaining)
            return alerts

        # --- Cycle completion: 24h alert already sent, start new cycle ---
        # After the 24h (highest) alert fires, reset the baseline to the current
        # remaining and start a fresh alert cycle.
        if self.state.last_alert_tier >= 3:
            logger.debug(
                f"Cycle complete (24h fired), resetting: baseline={remaining:.2f}%, level=0"
            )
            self.state.reset_baselines(remaining)
            # Re-evaluate from the new baseline (total_consumed is now 0)
            return alerts

        # --- Low usage per-percent tracking ---
        # When below the low_usage_threshold, alert every individual percent drop.
        if remaining < self.config.low_usage_threshold_percent:
            last_low = self.state.last_low_alert_remaining
            if last_low is not None and remaining < last_low:
                # Check if we've dropped at least 1 percentage point
                drop = last_low - remaining
                if drop >= 1.0:
                    alerts.append(
                        self._make_low_alert(remaining, usage, self._calc_interval(remaining))
                    )
                    self.state.mark_alert(remaining)
                    return alerts
            # Even in low mode, we might also have crossed a threshold
            # Check thresholds in case usage dropped fast
            threshold_alert = self._check_thresholds(
                remaining, total_consumed, usage, self.state.last_alert_tier
            )
            if threshold_alert:
                alerts.append(threshold_alert)
                tier = _TIER_MAP.get(threshold_alert.level, 0)
                self.state.mark_alert(remaining, tier)
                # If 24h fired, cycle will reset on next check
            return alerts

        # --- Progressive threshold crossing detection ---
        # Check if total_consumed crosses the NEXT threshold above last_alert_level.
        threshold_alert = self._check_thresholds(
            remaining, total_consumed, usage, self.state.last_alert_tier
        )
        if threshold_alert:
            alerts.append(threshold_alert)
            tier = _TIER_MAP.get(threshold_alert.level, 0)
            self.state.mark_alert(remaining, tier)

        return alerts

    # ------------------------------------------------------------------
    # Threshold checking (progressive)
    # ------------------------------------------------------------------

    def _check_thresholds(
        self,
        remaining: float,
        total_consumed: float,
        usage: UsageInfo,
        last_alert_level: int,
    ) -> Alert | None:
        """Check if total_consumed crosses the next progressive threshold.

        Only returns an alert for a tier HIGHER than last_alert_level.
        Checks from highest to lowest so the highest applicable tier wins.
        """
        # 24h threshold (highest) — only if not already sent
        if last_alert_level < 3 and total_consumed >= self.config.threshold_24h_percent:
            return self._make_threshold_alert(
                AlertLevel.FULL_DAY_24H, remaining, total_consumed, usage
            )
        # 16h threshold — only if not already sent
        if last_alert_level < 2 and total_consumed >= self.config.threshold_16h_percent:
            return self._make_threshold_alert(
                AlertLevel.AWAKE_16H, remaining, total_consumed, usage
            )
        # 8h threshold (lowest) — only if not already sent
        if last_alert_level < 1 and total_consumed >= self.config.threshold_8h_percent:
            return self._make_threshold_alert(AlertLevel.SLEEP_8H, remaining, total_consumed, usage)
        return None

    # ------------------------------------------------------------------
    # Alert message construction
    # ------------------------------------------------------------------

    def _make_threshold_alert(
        self, level: AlertLevel, remaining: float, consumed: float, usage: UsageInfo
    ) -> Alert:
        """Build a threshold alert with the appropriate message template."""
        restore = self.calculate_restore_time(remaining)
        fmt_args = {
            "remaining": remaining,
            "consumed": consumed,
            "max_credits": usage.max_credits,
            "remaining_credits": usage.remaining_credits,
            "restore_hours": restore["hours"],
            "restore_days": restore["days"],
            "regen_pct": self.config.regen_percent,
            "regen_hours": self.config.regen_interval_hours,
        }

        if level == AlertLevel.SLEEP_8H:
            msg = self.config.msg_8h.format(**fmt_args)
        elif level == AlertLevel.AWAKE_16H:
            msg = self.config.msg_16h.format(**fmt_args)
        elif level == AlertLevel.FULL_DAY_24H:
            msg = self.config.msg_24h.format(**fmt_args)
        else:
            msg = f"Usage alert: {consumed:.1f}% consumed, {remaining:.1f}% remaining"

        return Alert(
            level=level,
            message=msg,
            remaining=remaining,
            consumed=consumed,
        )

    def _make_low_alert(self, remaining: float, usage: UsageInfo, interval: float) -> Alert:
        """Build a low-usage per-percent alert."""
        restore = self.calculate_restore_time(remaining)
        fmt_args = {
            "remaining": remaining,
            "max_credits": usage.max_credits,
            "remaining_credits": usage.remaining_credits,
            "restore_hours": restore["hours"],
            "restore_days": restore["days"],
            "regen_pct": self.config.regen_percent,
            "regen_hours": self.config.regen_interval_hours,
            "interval": interval,
        }
        msg = self.config.msg_low.format(**fmt_args)
        return Alert(
            level=AlertLevel.LOW_USAGE,
            message=msg,
            remaining=remaining,
            consumed=0.0,
        )

    # ------------------------------------------------------------------
    # Interval calculation
    # ------------------------------------------------------------------

    def calculate_monitor_interval(self, remaining: float) -> float:
        """Calculate monitoring interval in minutes based on remaining usage.

        - Below low_usage_threshold: low_interval_min (1 min by default)
        - At 100%: normal_interval_min (10 min by default)
        - Linear interpolation between low_usage_threshold and 100%
        """
        low_t = self.config.low_usage_threshold_percent
        low_i = self.config.low_interval_min
        norm_i = self.config.normal_interval_min

        if remaining <= low_t:
            return low_i

        # Linear scale: low_i at low_t → norm_i at 100
        ratio = (remaining - low_t) / (100.0 - low_t)
        ratio = max(0.0, min(1.0, ratio))
        return low_i + ratio * (norm_i - low_i)

    def _calc_interval(self, remaining: float) -> float:
        """Alias for calculate_monitor_interval (for internal use)."""
        return self.calculate_monitor_interval(remaining)

    # ------------------------------------------------------------------
    # Restore time calculation
    # ------------------------------------------------------------------

    def calculate_restore_time(self, remaining: float) -> dict[str, float]:
        """Calculate time to fully restore to 100%.

        Returns dict with 'hours' and 'days' keys.
        """
        regen_per_hour = self.config.regen_rate_per_hour
        if regen_per_hour <= 0:
            return {"hours": float("inf"), "days": float("inf")}
        needed = 100.0 - remaining
        hours = needed / regen_per_hour
        return {"hours": round(hours, 1), "days": round(hours / 24.0, 1)}
