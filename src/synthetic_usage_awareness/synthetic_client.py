"""Synthetic API client for fetching quota information.

Real client: GET https://api.synthetic.new/v2/quotas
Mock client: Simulates quota with regeneration over time for testing.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

logger = logging.getLogger("synthetic_usage_awareness.client")


@dataclass(frozen=True)
class UsageInfo:
    """Parsed quota information from the Synthetic API."""

    percent_remaining: float  # 0.0–100.0
    max_credits: str  # e.g. "$132.00"
    remaining_credits: str  # e.g. "$126.76"
    next_regen_credits: str  # e.g. "$2.64"
    next_regen_at: str  # ISO 8601 timestamp
    raw: dict[str, Any]  # Full raw API response


class SyntheticClientInterface(Protocol):
    """Protocol that both real and mock clients must satisfy."""

    def get_usage(self) -> UsageInfo: ...


# ---------------------------------------------------------------------------
# Real client
# ---------------------------------------------------------------------------


class SyntheticClient:
    """Fetches quota data from the real Synthetic API.

    Endpoint: GET {api_base}/v2/quotas
    Auth: Bearer {api_key}
    Does NOT count against subscription limits.
    """

    def __init__(
        self, api_key: str, api_base: str, quotas_path: str = "/v2/quotas", timeout: float = 15.0
    ):
        self._api_key = api_key
        self._url = f"{api_base.rstrip('/')}{quotas_path}"
        self._timeout = timeout

    def get_usage(self) -> UsageInfo:
        """Fetch current quota info. Raises on HTTP errors."""
        req = urllib.request.Request(
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Synthetic API HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Synthetic API network error: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Synthetic API returned invalid JSON: {e}") from e

        return _parse_quota_response(data)


def _parse_quota_response(data: dict[str, Any]) -> UsageInfo:
    """Parse the /v2/quotas response into UsageInfo.

    Expected structure:
    {
      "weeklyTokenLimit": {
        "percentRemaining": 95.99,
        "maxCredits": "$132.00",
        "remainingCredits": "$126.71",
        "nextRegenCredits": "$2.64",
        "nextRegenAt": "2026-07-30T22:18:31.000Z"
      },
      ...
    }
    """
    wtl = data.get("weeklyTokenLimit", {})
    return UsageInfo(
        percent_remaining=float(wtl.get("percentRemaining", 0.0)),
        max_credits=str(wtl.get("maxCredits", "$0.00")),
        remaining_credits=str(wtl.get("remainingCredits", "$0.00")),
        next_regen_credits=str(wtl.get("nextRegenCredits", "$0.00")),
        next_regen_at=str(wtl.get("nextRegenAt", "")),
        raw=data,
    )


# ---------------------------------------------------------------------------
# Mock client — for unit tests
# ---------------------------------------------------------------------------


class MockSyntheticClient:
    """Simulates Synthetic quota with time-based regeneration.

    Usage:
        mock = MockSyntheticClient(initial_percent=80.0)
        mock.simulate_usage(10.0)      # consume 10%
        mock.advance_time(hours=4.0)   # regenerate 2%
        info = mock.get_usage()         # → 72.0%
    """

    def __init__(
        self,
        initial_percent: float = 100.0,
        regen_percent: float = 2.0,
        regen_interval_hours: float = 4.0,
        max_credits: str = "$132.00",
        next_regen_credits: str = "$2.64",
    ):
        self._percent = max(0.0, min(100.0, initial_percent))
        self._regen_percent = regen_percent
        self._regen_interval_hours = regen_interval_hours
        self._max_credits = max_credits
        self._next_regen_credits = next_regen_credits
        self._start_time = datetime.now(UTC)

        # Simulated clock — advances via advance_time() or automatically via wall clock
        self._sim_time: datetime | None = None  # If None, uses real wall clock
        self._last_regen_time = self._current_time

    # --- Simulated clock ---

    @property
    def _current_time(self) -> datetime:
        if self._sim_time is not None:
            return self._sim_time
        return datetime.now(UTC)

    def advance_time(self, hours: float) -> None:
        """Advance the simulated clock and apply regeneration."""
        if self._sim_time is None:
            self._sim_time = datetime.now(UTC)
        old_time = self._sim_time
        self._sim_time = self._sim_time + timedelta(hours=hours)
        self._apply_regeneration(old_time, self._sim_time)

    def set_time(self, dt: datetime) -> None:
        """Set the simulated clock to a specific time."""
        if self._sim_time is not None:
            self._apply_regeneration(self._sim_time, dt)
        else:
            self._last_regen_time = dt
        self._sim_time = dt

    # --- Usage simulation ---

    def simulate_usage(self, percent_used: float) -> None:
        """Simulate consuming `percent_used` of quota."""
        self._percent = max(0.0, self._percent - percent_used)

    def set_percent(self, percent: float) -> None:
        """Directly set the remaining percentage (for test scenarios)."""
        self._percent = max(0.0, min(100.0, percent))

    # --- Regeneration ---

    def _apply_regeneration(self, from_time: datetime, to_time: datetime) -> None:
        """Apply regeneration for the time elapsed between from_time and to_time."""
        elapsed_hours = (to_time - from_time).total_seconds() / 3600.0
        if elapsed_hours <= 0:
            return
        regen_ticks = elapsed_hours / self._regen_interval_hours
        regen_amount = regen_ticks * self._regen_percent
        self._percent = min(100.0, self._percent + regen_amount)

    def _maybe_apply_realtime_regen(self) -> None:
        """If using real wall clock, apply regeneration since last check."""
        if self._sim_time is not None:
            return  # Using simulated time — regen handled by advance_time
        now = datetime.now(UTC)
        self._apply_regeneration(self._last_regen_time, now)
        self._last_regen_time = now

    # --- Interface ---

    def get_usage(self) -> UsageInfo:
        """Return current quota info (same format as real client)."""
        self._maybe_apply_realtime_regen()

        remaining_credits = f"${self._percent / 100.0 * 132.0:.2f}"
        next_regen_at = (
            self._current_time + timedelta(hours=self._regen_interval_hours)
        ).isoformat()

        return UsageInfo(
            percent_remaining=round(self._percent, 6),
            max_credits=self._max_credits,
            remaining_credits=remaining_credits,
            next_regen_credits=self._next_regen_credits,
            next_regen_at=next_regen_at,
            raw={
                "weeklyTokenLimit": {
                    "percentRemaining": round(self._percent, 6),
                    "maxCredits": self._max_credits,
                    "remainingCredits": remaining_credits,
                    "nextRegenCredits": self._next_regen_credits,
                    "nextRegenAt": next_regen_at,
                },
                "_mock": True,
            },
        )
