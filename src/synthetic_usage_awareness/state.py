"""State persistence for synthetic-usage-awareness plugin.

State is saved to a JSON file and tracks:
- baseline_remaining: quota % at the start of the current alert cycle (set on
  first check or when quota regenerates back to/above baseline)
- last_alert_tier: highest tier alert sent in current cycle (0=none, 1=8h,
  2=16h, 3=24h/1day, 4=1day+8h, 5=1day+16h, 6=2days, ...).
  Each tier = threshold_8h_percent (4%) more consumed than the previous.
  Tiers cycle: 8h → 16h → 24h, then 1day+8h → 1day+16h → 2days, etc.
  Resets to 0 when baseline resets (regeneration).
- last_low_alert_remaining: for per-percent tracking below low_usage_threshold
- last_check_remaining: quota % at the most recent API check
- last_check_time: ISO timestamp of the most recent check
- initialized: whether the first check has completed (baseline established)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("synthetic_usage_awareness.state")


@dataclass
class TrackerState:
    """Mutable state persisted across plugin restarts."""

    # Quota % remaining at the start of the current alert cycle.
    # Set on first check, and reset when quota regenerates back to/above this
    # level.  Stays fixed across alerts (no reset after each alert).
    baseline_remaining: float | None = None

    # Highest tier alert sent in the current cycle.
    # 0 = none, 1 = 8h, 2 = 16h, 3 = 24h/1day, 4 = 1day+8h, 5 = 1day+16h,
    # 6 = 2days, etc.  Each tier = 4% (threshold_8h_percent) more consumed.
    # Resets to 0 when baseline resets.
    last_alert_tier: int = 0

    # Quota % remaining when the last low-usage per-percent alert was sent.
    # Only used when remaining < low_usage_threshold.
    last_low_alert_remaining: float | None = None

    # Quota % at the most recent API check (for interval calculation).
    last_check_remaining: float | None = None

    # ISO 8601 timestamp of the most recent check.
    last_check_time: str = ""

    # Whether the first check has completed and baseline is established.
    # On the first check, we set baselines but don't send alerts.
    initialized: bool = False

    # Monotonic counter of total checks performed.
    total_checks: int = 0

    # Monotonic counter of total alerts sent.
    total_alerts_sent: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackerState:
        """Create state from a dict, handling backward compatibility.

        Old state files used 'last_alert_remaining' (float) instead of
        'baseline_remaining'.  Intermediate versions used 'last_alert_level'
        (0-3) instead of 'last_alert_tier' (0+).  Both are migrated.
        """
        known = {
            "baseline_remaining",
            "last_alert_tier",
            "last_low_alert_remaining",
            "last_check_remaining",
            "last_check_time",
            "initialized",
            "total_checks",
            "total_alerts_sent",
        }
        filtered = {k: v for k, v in data.items() if k in known}

        # Backward compat: migrate old 'last_alert_remaining' → 'baseline_remaining'
        if "baseline_remaining" not in filtered and "last_alert_remaining" in data:
            filtered["baseline_remaining"] = data["last_alert_remaining"]
            logger.info("Migrated old state field 'last_alert_remaining' → 'baseline_remaining'")

        # Backward compat: migrate 'last_alert_level' → 'last_alert_tier'
        if "last_alert_tier" not in filtered and "last_alert_level" in data:
            filtered["last_alert_tier"] = data["last_alert_level"]
            logger.info("Migrated old state field 'last_alert_level' → 'last_alert_tier'")

        return cls(**filtered)

    def save(self, path: str | Path) -> None:
        """Save state to a JSON file. Creates parent dirs as needed."""
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save state to {p}: {e}")

    @classmethod
    def load(cls, path: str | Path) -> TrackerState:
        """Load state from a JSON file. Returns fresh state if file is missing/corrupt."""
        p = Path(path)
        if not p.exists():
            logger.info(f"State file {p} not found — starting fresh")
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"State file {p} corrupt ({e}) — starting fresh")
            return cls()
        except Exception as e:
            logger.error(f"Failed to load state from {p}: {e}")
            return cls()

    def mark_check(self, remaining: float) -> None:
        """Update state after a successful API check."""
        self.last_check_remaining = remaining
        self.last_check_time = datetime.now(UTC).isoformat()
        self.total_checks += 1

    def mark_alert(self, remaining: float, tier: int | None = None) -> None:
        """Update state after sending an alert.

        Args:
            remaining: Current quota % remaining.
            tier: Tier number of the alert (1+, or None for low-usage alerts
                  which don't change last_alert_tier).
        """
        self.last_low_alert_remaining = remaining
        self.total_alerts_sent += 1
        if tier is not None:
            self.last_alert_tier = tier

    def reset_baselines(self, remaining: float) -> None:
        """Set initial baselines on first check or after regeneration reset."""
        self.baseline_remaining = remaining
        self.last_alert_tier = 0
        self.last_low_alert_remaining = remaining
        self.last_check_remaining = remaining
        self.last_check_time = datetime.now(UTC).isoformat()
        self.initialized = True
