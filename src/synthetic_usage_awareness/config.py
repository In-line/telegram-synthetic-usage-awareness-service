"""Configuration for synthetic-usage-awareness.

Layered configuration, highest precedence last:

1. Built-in defaults
2. TOML config file:
   $XDG_CONFIG_HOME/synthetic-usage-awareness/config.toml
   (default: $HOME/.config/synthetic-usage-awareness/config.toml)
3. Environment variables with the SYN_AWARENESS_ prefix

Environment variables always win over the file, which keeps the service
scriptable (systemd units, containers, CI) without editing the file.

Copyright (C) 2026 Alik
Licensed under GPL-3.0-or-later. See the LICENSE file for details.
"""

from __future__ import annotations

import os

try:
    import tomllib
except ImportError:  # Python < 3.11 (e.g. RHEL 8 python39)
    # Fall back to the vendored tomli backport (MIT, see
    # _vendored_tomli/__init__.py) so the package stays dependency-free.
    from synthetic_usage_awareness import _vendored_tomli as tomllib

from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "synthetic-usage-awareness"
ENV_PREFIX = "SYN_AWARENESS_"


def config_dir() -> Path:
    """Directory holding the service configuration file."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or ""
    base = Path(xdg) if xdg.strip() else Path.home() / ".config"
    return base / APP_NAME


def cache_dir() -> Path:
    """Directory holding persistent state (cache semantics)."""
    xdg = os.environ.get("XDG_CACHE_HOME") or ""
    base = Path(xdg) if xdg.strip() else Path.home() / ".cache"
    return base / APP_NAME


def default_config_path() -> Path:
    """Full path of the TOML config file."""
    override = os.environ.get(f"{ENV_PREFIX}CONFIG") or ""
    if override.strip():
        return Path(override.strip())
    return config_dir() / "config.toml"


def default_state_path() -> Path:
    """Full path of the state file, under $XDG_CACHE_HOME by default."""
    override = os.environ.get(f"{ENV_PREFIX}STATE_FILE") or ""
    if override.strip():
        return Path(override.strip())
    return cache_dir() / "state.json"


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass
class ServiceConfig:
    """All configuration for the usage awareness service."""

    # --- Master switch ---
    enabled: bool = True

    # --- Synthetic API ---
    api_key: str = ""
    api_base: str = "https://api.synthetic.new"
    quotas_path: str = "/v2/quotas"
    request_timeout_sec: float = 15.0

    # --- Telegram notification ---
    bot_token: str = ""
    chat_id: str = ""
    thread_id: str = ""  # message_thread_id for forum topics

    # --- Regeneration model ---
    # Synthetic restores 2% every 4 hours = 0.5%/hour
    regen_percent: float = 2.0
    regen_interval_hours: float = 4.0

    # --- Alert thresholds (in % of total quota consumed from baseline) ---
    # 8h of usage = 8 * 0.5 = 4%
    threshold_8h_percent: float = 4.0
    # 16h of usage = 16 * 0.5 = 8%
    threshold_16h_percent: float = 8.0
    # 24h of usage = 24 * 0.5 = 12%
    threshold_24h_percent: float = 12.0

    # --- Low usage tracking ---
    # Below this remaining %, alert every individual percent drop
    low_usage_threshold_percent: float = 12.0

    # --- Monitoring intervals (minutes) ---
    normal_interval_min: float = 10.0
    low_interval_min: float = 1.0

    # --- State persistence ---
    state_file: str = ""

    # --- Custom alert messages ---
    # Placeholders: {remaining}, {used}, {max_credits}, {remaining_credits},
    #                {consumed}, {restore_hours}, {restore_days}, {regen_pct},
    #                {regen_hours}, {interval}
    msg_8h: str = field(
        default=(
            "🌙 *Sleep Amount Used* (8h worth)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Remaining: *{remaining:.1f}%* ({remaining_credits} / {max_credits})\n"
            "📉 Total consumed: *{consumed:.1f}%*\n"
            "🔄 Regeneration: {regen_pct:.0f}% every {regen_hours:.0f}h\n"
            "⏱️ Full restore in: *{restore_hours:.1f}h* ({restore_days:.1f} days)"
        )
    )
    msg_16h: str = field(
        default=(
            "☀️ *Awake Amount Used* (16h worth)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Remaining: *{remaining:.1f}%* ({remaining_credits} / {max_credits})\n"
            "📉 Total consumed: *{consumed:.1f}%*\n"
            "🔄 Regeneration: {regen_pct:.0f}% every {regen_hours:.0f}h\n"
            "⏱️ Full restore in: *{restore_hours:.1f}h* ({restore_days:.1f} days)"
        )
    )
    msg_24h: str = field(
        default=(
            "📅 *Full Day Used* (24h worth)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Remaining: *{remaining:.1f}%* ({remaining_credits} / {max_credits})\n"
            "📉 Total consumed: *{consumed:.1f}%*\n"
            "🔄 Regeneration: {regen_pct:.0f}% every {regen_hours:.0f}h\n"
            "⏱️ Full restore in: *{restore_hours:.1f}h* ({restore_days:.1f} days)"
        )
    )
    msg_low: str = field(
        default=(
            "⚠️ *Low Usage: {remaining:.0f}% remaining*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Remaining: *{remaining:.1f}%* ({remaining_credits} / {max_credits})\n"
            "🔄 Regeneration: {regen_pct:.0f}% every {regen_hours:.0f}h\n"
            "⏱️ Full restore in: *{restore_hours:.1f}h* ({restore_days:.1f} days)\n"
            "📉 Monitoring every ~{interval:.0f} min"
        )
    )

    # --- Logging ---
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> ServiceConfig:
        """Load configuration: defaults → TOML file → environment.

        The optional ``config_path`` argument overrides the discovery order
        (used by ``--config`` on the CLI and by tests).
        """
        path = Path(config_path) if config_path else default_config_path()
        file_data = _read_toml(path)

        cfg = cls()

        # --- TOML values (flat keys; strings/numbers/bools) ---
        _apply(cfg, file_data)

        # --- Environment overrides ---
        _apply(cfg, _env_overrides())

        # --- Derived defaults that depend on XDG dirs ---
        if not cfg.state_file:
            cfg.state_file = str(default_state_path())

        return cfg

    # Kept for backward compatibility with existing tooling/tests.
    from_env = load

    def validate(self) -> list[str]:
        """Return list of validation errors (empty if valid)."""
        errors = []
        if not self.api_key:
            errors.append("api_key is required ([api] section or SYN_AWARENESS_API_KEY)")
        if not self.bot_token:
            errors.append("bot_token is required ([telegram] section or SYN_AWARENESS_BOT_TOKEN)")
        if not self.chat_id:
            errors.append("chat_id is required ([telegram] section or SYN_AWARENESS_CHAT_ID)")
        if self.regen_percent <= 0:
            errors.append("regen_percent must be > 0")
        if self.regen_interval_hours <= 0:
            errors.append("regen_interval_hours must be > 0")
        if self.threshold_8h_percent <= 0:
            errors.append("threshold_8h_percent must be > 0")
        if self.threshold_16h_percent <= self.threshold_8h_percent:
            errors.append("threshold_16h_percent must be > threshold_8h_percent")
        if self.threshold_24h_percent <= self.threshold_16h_percent:
            errors.append("threshold_24h_percent must be > threshold_16h_percent")
        if self.low_usage_threshold_percent <= 0:
            errors.append("low_usage_threshold_percent must be > 0")
        if self.low_interval_min <= 0:
            errors.append("low_interval_min must be > 0")
        if self.normal_interval_min < self.low_interval_min:
            errors.append("normal_interval_min must be >= low_interval_min")
        return errors

    @property
    def regen_rate_per_hour(self) -> float:
        """Regeneration rate in percent per hour."""
        return self.regen_percent / self.regen_interval_hours


# ----------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------


def _read_toml(path: Path) -> dict:
    """Read the TOML file if it exists; missing file is not an error."""
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Invalid TOML in config file {path}: {e}") from e
    if not isinstance(data, dict):
        return {}
    # Flatten: [section] key → both "section_key" and bare "key" so both
    # layouts work ("api_key = ..." at top level or inside [api]).
    flat: dict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat.setdefault(f"{key}_{sub_key}", sub_value)
                flat.setdefault(sub_key, sub_value)
        else:
            flat[key] = value
    return flat


_FIELD_ALIASES = {
    # toml key → dataclass field
    "bot_token": "bot_token",
    "chat_id": "chat_id",
    "thread_id": "thread_id",
    "api_key": "api_key",
    "api_base": "api_base",
    "quotas_path": "quotas_path",
    "request_timeout_sec": "request_timeout_sec",
    "timeout": "request_timeout_sec",
    "state_file": "state_file",
    "log_level": "log_level",
    "enabled": "enabled",
    "regen_percent": "regen_percent",
    "regen_interval_hours": "regen_interval_hours",
    "threshold_8h_percent": "threshold_8h_percent",
    "threshold_16h_percent": "threshold_16h_percent",
    "threshold_24h_percent": "threshold_24h_percent",
    "low_usage_threshold_percent": "low_usage_threshold_percent",
    "normal_interval_min": "normal_interval_min",
    "low_interval_min": "low_interval_min",
    "msg_8h": "msg_8h",
    "msg_16h": "msg_16h",
    "msg_24h": "msg_24h",
    "msg_low": "msg_low",
}


# Environment variable short names (post-prefix, lowercased) → field.
# e.g. SYN_AWARENESS_THRESHOLD_8H → threshold_8h_percent
_ENV_ALIASES = {
    "threshold_8h": "threshold_8h_percent",
    "threshold_16h": "threshold_16h_percent",
    "threshold_24h": "threshold_24h_percent",
    "low_usage_threshold": "low_usage_threshold_percent",
    "normal_interval": "normal_interval_min",
    "low_interval": "low_interval_min",
    "timeout": "request_timeout_sec",
}


def _apply(cfg: ServiceConfig, data: dict) -> None:
    """Apply a flat key/value dict onto the config if the key is known."""
    for key, value in data.items():
        field_name = _FIELD_ALIASES.get(key)
        if field_name is None:
            continue
        current = getattr(cfg, field_name, None)
        try:
            if isinstance(current, bool):
                if isinstance(value, bool):
                    setattr(cfg, field_name, value)
                elif isinstance(value, str) and not value.strip():
                    continue  # empty env var = unset, keep default
                else:
                    setattr(
                        cfg,
                        field_name,
                        str(value).strip().lower() in ("1", "true", "yes", "on"),
                    )
            elif isinstance(current, float):
                setattr(cfg, field_name, float(value))
            elif isinstance(current, int):
                setattr(cfg, field_name, int(value))
            else:
                setattr(cfg, field_name, str(value))
        except (TypeError, ValueError):
            # Keep default when the value cannot be coerced.
            continue


def _env_overrides() -> dict:
    """Collect SYN_AWARENESS_* environment variables as flat keys."""
    out: dict = {}
    for name, value in os.environ.items():
        if not name.startswith(ENV_PREFIX) or name == f"{ENV_PREFIX}CONFIG":
            continue
        key = name[len(ENV_PREFIX) :].lower()
        out[_ENV_ALIASES.get(key, key)] = value
    return out


# ----------------------------------------------------------------------
# First-run convenience: fall back to a systemd-style EnvironmentFile
# ----------------------------------------------------------------------


def _maybe_load_env_file() -> None:
    """Source KEY=VALUE pairs from the packaged env file, if present.

    The Debian/RPM package ships /etc/default/synthetic-usage-awareness for
    secrets. systemd loads it via EnvironmentFile=; for manual runs we
    import it here (without overriding variables already set).
    """
    for candidate in (
        Path("/etc/default/synthetic-usage-awareness"),
        Path.home() / ".config" / APP_NAME / "env",
    ):
        try:
            if not candidate.is_file():
                continue
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue


_maybe_load_env_file()
