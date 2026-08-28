"""Background monitoring thread — polls Synthetic API and sends alerts.

Runs in a daemon thread started by register(). Uses an Event for
graceful shutdown. Sleep interval scales with remaining quota.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC

from .config import ServiceConfig
from .notifier import TelegramNotifier
from .state import TrackerState
from .synthetic_client import SyntheticClient, UsageInfo
from .usage_tracker import Alert, UsageTracker

logger = logging.getLogger("synthetic_usage_awareness.monitor")


class UsageMonitor:
    """Background thread that periodically checks Synthetic quota and alerts.

    Lifecycle:
        monitor = UsageMonitor(config)
        monitor.start()    # launches daemon thread
        monitor.stop()     # signals thread to exit, joins with timeout

    The thread loop:
        1. Fetch usage from Synthetic API (or mock)
        2. Evaluate thresholds via UsageTracker
        3. Send any alerts via TelegramNotifier
        4. Persist state
        5. Sleep for calculated interval (scales with remaining quota)
    """

    def __init__(
        self,
        config: ServiceConfig,
        client: SyntheticClient | None = None,
        tracker: UsageTracker | None = None,
        notifier: TelegramNotifier | None = None,
        state: TrackerState | None = None,
    ) -> None:
        self.config = config
        self.state = state or TrackerState.load(config.state_file)
        self.client = client or SyntheticClient(
            api_key=config.api_key,
            api_base=config.api_base,
            quotas_path=config.quotas_path,
            timeout=config.request_timeout_sec,
        )
        self.tracker = tracker or UsageTracker(config, self.state)
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.bot_token,
            chat_id=config.chat_id,
            thread_id=config.thread_id,
        )

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Configurable hooks for testing
        self._on_check: Callable[[UsageInfo], None] | None = None
        self._on_alert: Callable[[Alert], None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Monitor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="synthetic-usage-monitor",
        )
        self._thread.start()
        logger.info("Synthetic usage monitor started")

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the monitor to stop and wait briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Synthetic usage monitor stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main monitoring loop. Runs until stop() is called."""
        # Do an initial check immediately
        self._check_once()

        while not self._stop_event.is_set():
            # Calculate sleep interval based on last known remaining
            interval_min = self.config.normal_interval_min
            if self.state.last_check_remaining is not None:
                interval_min = self.tracker.calculate_monitor_interval(
                    self.state.last_check_remaining
                )

            sleep_sec = max(1.0, interval_min * 60.0)
            logger.debug(
                f"Sleeping {sleep_sec:.0f}s (interval={interval_min:.1f}min, "
                f"remaining={self.state.last_check_remaining})"
            )

            # Wait in a way that allows early wakeup on stop
            woken = self._stop_event.wait(timeout=sleep_sec)
            if woken:
                break

            self._check_once()

    def _check_once(self) -> None:
        """Perform one check cycle: fetch → evaluate → alert → persist."""
        try:
            with self._lock:
                # 1. Fetch usage
                usage = self.client.get_usage()
                remaining = usage.percent_remaining

                if self._on_check:
                    self._on_check(usage)

                logger.debug(
                    f"Quota check: remaining={remaining:.2f}%, "
                    f"credits={usage.remaining_credits}/{usage.max_credits}"
                )

                # 2. Evaluate thresholds
                alerts = self.tracker.evaluate(usage)

                # 3. Send alerts
                for alert in alerts:
                    success = self.notifier.send_alert(alert)
                    if success:
                        logger.info(
                            f"Alert sent: level={alert.level.value}, "
                            f"remaining={alert.remaining:.1f}%, "
                            f"consumed={alert.consumed:.1f}%"
                        )
                    else:
                        logger.error(f"Failed to send alert: {alert.level.value}")

                    if self._on_alert:
                        self._on_alert(alert)

                # 4. Persist state
                self.state.mark_check(remaining)
                self.state.save(self.config.state_file)

        except Exception as e:
            logger.error(f"Monitor check failed: {e}", exc_info=True)
            # On error, still update the check time to prevent tight loops
            self.state.last_check_time = _now_iso()
            self.state.save(self.config.state_file)

    # ------------------------------------------------------------------
    # Test hooks
    # ------------------------------------------------------------------

    def set_on_check(self, callback: Callable[[UsageInfo], None]) -> None:
        """Set a callback invoked after each successful API check (for testing)."""
        self._on_check = callback

    def set_on_alert(self, callback: Callable[[Alert], None]) -> None:
        """Set a callback invoked for each alert sent (for testing)."""
        self._on_alert = callback

    def check_now(self) -> None:
        """Trigger an immediate check (thread-safe, for manual/testing use)."""
        self._check_once()


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
