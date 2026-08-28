"""Command line interface for synthetic-usage-awareness.

Modes:
  --once   run a single check and exit (default for the systemd user timer)
  --loop   run continuously in the foreground (monitor thread + signal wait)
  --show-config print the effective configuration with secrets redacted

Exit codes: 0 success/skipped, 1 configuration error, 2 runtime failure.

Copyright (C) 2026 Alik
Licensed under GPL-3.0-or-later. See the LICENSE file for details.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from . import __version__
from .config import ServiceConfig, default_config_path

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_RUNTIME_ERROR = 2

logger = logging.getLogger("synthetic_usage_awareness.cli")

_SECRET_FIELDS = ("api_key", "bot_token")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthetic-usage-awareness",
        description=(
            "Synthetic subscription usage tracker — polls the Synthetic API and "
            "sends Telegram alerts when quota usage crosses thresholds. "
            "Designed to run under a systemd user timer with --once."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help=f"config file path (default: {default_config_path()})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="perform one check cycle and exit (systemd timer mode)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="run continuously in the foreground until SIGINT/SIGTERM",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="print the effective configuration (secrets redacted) and exit",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="validate configuration and exit",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default=None,
        help="override log level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _redacted(cfg: ServiceConfig) -> dict:
    data = {
        "enabled": cfg.enabled,
        "api_base": cfg.api_base,
        "quotas_path": cfg.quotas_path,
        "request_timeout_sec": cfg.request_timeout_sec,
        "bot_token": "***" if cfg.bot_token else "",
        "api_key": "***" if cfg.api_key else "",
        "chat_id": cfg.chat_id,
        "thread_id": cfg.thread_id,
        "regen_percent": cfg.regen_percent,
        "regen_interval_hours": cfg.regen_interval_hours,
        "threshold_8h_percent": cfg.threshold_8h_percent,
        "threshold_16h_percent": cfg.threshold_16h_percent,
        "threshold_24h_percent": cfg.threshold_24h_percent,
        "low_usage_threshold_percent": cfg.low_usage_threshold_percent,
        "normal_interval_min": cfg.normal_interval_min,
        "low_interval_min": cfg.low_interval_min,
        "state_file": cfg.state_file,
        "log_level": cfg.log_level,
    }
    return data


def run_once(cfg: ServiceConfig) -> int:
    """Single check cycle: fetch → evaluate → alert → persist."""
    from .monitor import UsageMonitor

    monitor = UsageMonitor(cfg)
    try:
        monitor.check_now()
    except Exception:
        logger.exception("Check cycle failed")
        return EXIT_RUNTIME_ERROR
    return EXIT_OK


def run_loop(cfg: ServiceConfig) -> int:
    """Run the monitoring loop in the foreground until signalled."""
    from .monitor import UsageMonitor

    stop = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("Received signal %s — shutting down", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    monitor = UsageMonitor(cfg)
    monitor.start()
    try:
        stop.wait()
    finally:
        monitor.stop(timeout=5.0)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not (args.once or args.loop or args.show_config or args.validate):
        # Default to timer-friendly single-shot behavior.
        args.once = True

    cfg = ServiceConfig.load(config_path=args.config)

    if args.log_level:
        cfg.log_level = args.log_level
    _setup_logging(cfg.log_level)

    if args.show_config:
        import json

        print(json.dumps(_redacted(cfg), indent=2, ensure_ascii=False))
        return EXIT_OK

    if not cfg.enabled:
        logger.info("synthetic-usage-awareness is disabled (enabled = false)")
        return EXIT_OK

    errors = cfg.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        logger.error(
            "Fix the config file %s or the SYN_AWARENESS_* env vars", default_config_path()
        )
        return EXIT_CONFIG_ERROR

    if args.validate:
        logger.info("Configuration OK (state file: %s)", cfg.state_file)
        return EXIT_OK

    if args.loop:
        return run_loop(cfg)
    return run_once(cfg)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
