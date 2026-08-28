"""Tests for ServiceConfig — loading from env vars, validation, auto-detection."""

from __future__ import annotations

import os
from unittest.mock import patch

from synthetic_usage_awareness.config import ServiceConfig


class TestServiceConfigFromEnv:
    """Test loading config from environment variables."""

    def test_defaults_when_no_env(self):
        """All env vars unset → sensible defaults."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove all SYN_AWARENESS_ vars
            for key in list(os.environ):
                if key.startswith("SYN_AWARENESS_"):
                    del os.environ[key]
            cfg = ServiceConfig.from_env()
            assert cfg.enabled is True
            assert cfg.api_base == "https://api.synthetic.new"
            assert cfg.quotas_path == "/v2/quotas"
            assert cfg.regen_percent == 2.0
            assert cfg.regen_interval_hours == 4.0
            assert cfg.threshold_8h_percent == 4.0
            assert cfg.threshold_16h_percent == 8.0
            assert cfg.threshold_24h_percent == 12.0
            assert cfg.low_usage_threshold_percent == 12.0
            assert cfg.normal_interval_min == 10.0
            assert cfg.low_interval_min == 1.0

    def test_custom_env_values(self):
        """Custom env vars override defaults."""
        env = {
            "SYN_AWARENESS_ENABLED": "false",
            "SYN_AWARENESS_API_KEY": "syn_custom",
            "SYN_AWARENESS_API_BASE": "https://custom.api.com",
            "SYN_AWARENESS_QUOTAS_PATH": "/custom/quotas",
            "SYN_AWARENESS_BOT_TOKEN": "999:XYZ",
            "SYN_AWARENESS_CHAT_ID": "-100999",
            "SYN_AWARENESS_THREAD_ID": "42",
            "SYN_AWARENESS_REGEN_PERCENT": "5.0",
            "SYN_AWARENESS_REGEN_INTERVAL_HOURS": "2.0",
            "SYN_AWARENESS_THRESHOLD_8H": "10.0",
            "SYN_AWARENESS_THRESHOLD_16H": "20.0",
            "SYN_AWARENESS_THRESHOLD_24H": "30.0",
            "SYN_AWARENESS_LOW_USAGE_THRESHOLD": "15.0",
            "SYN_AWARENESS_NORMAL_INTERVAL_MIN": "20.0",
            "SYN_AWARENESS_LOW_INTERVAL_MIN": "2.0",
        }
        with patch.dict(os.environ, env, clear=False):
            for key in list(os.environ):
                if key.startswith("SYN_AWARENESS_") and key not in env:
                    del os.environ[key]
            cfg = ServiceConfig.from_env()
            assert cfg.enabled is False
            assert cfg.api_key == "syn_custom"
            assert cfg.api_base == "https://custom.api.com"
            assert cfg.quotas_path == "/custom/quotas"
            assert cfg.bot_token == "999:XYZ"
            assert cfg.chat_id == "-100999"
            assert cfg.thread_id == "42"
            assert cfg.regen_percent == 5.0
            assert cfg.regen_interval_hours == 2.0
            assert cfg.threshold_8h_percent == 10.0
            assert cfg.threshold_16h_percent == 20.0
            assert cfg.threshold_24h_percent == 30.0
            assert cfg.low_usage_threshold_percent == 15.0
            assert cfg.normal_interval_min == 20.0
            assert cfg.low_interval_min == 2.0

    def test_env_bool_variations(self):
        """Various boolean representations."""
        for val, expected in [
            ("1", True),
            ("true", True),
            ("True", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("", True),
        ]:  # empty → default
            env = {"SYN_AWARENESS_ENABLED": val}
            with patch.dict(os.environ, env, clear=False):
                # Remove the var after testing each
                cfg = ServiceConfig.from_env()
                if val == "":
                    assert cfg.enabled is True  # default
                else:
                    assert cfg.enabled is expected, f"Failed for value '{val}'"
                os.environ.pop("SYN_AWARENESS_ENABLED", None)


class TestServiceConfigValidate:
    """Test config validation."""

    def test_valid_config(self, default_config):
        """A complete config should have no validation errors."""
        errors = default_config.validate()
        assert errors == []

    def test_missing_api_key(self, default_config):
        default_config.api_key = ""
        errors = default_config.validate()
        assert any("API_KEY" in e for e in errors)

    def test_missing_bot_token(self, default_config):
        default_config.bot_token = ""
        errors = default_config.validate()
        assert any("BOT_TOKEN" in e for e in errors)

    def test_missing_chat_id(self, default_config):
        default_config.chat_id = ""
        errors = default_config.validate()
        assert any("CHAT_ID" in e for e in errors)

    def test_regen_percent_must_be_positive(self, default_config):
        default_config.regen_percent = 0
        errors = default_config.validate()
        assert any("regen_percent" in e for e in errors)

    def test_regen_interval_must_be_positive(self, default_config):
        default_config.regen_interval_hours = -1
        errors = default_config.validate()
        assert any("regen_interval" in e for e in errors)

    def test_threshold_ordering(self, default_config):
        """threshold_16h must be > threshold_8h, etc."""
        default_config.threshold_16h_percent = 3.0  # Less than 8h threshold (4.0)
        errors = default_config.validate()
        assert any("threshold_16h" in e for e in errors)

        default_config.threshold_16h_percent = 8.0
        default_config.threshold_24h_percent = 7.0  # Less than 16h threshold
        errors = default_config.validate()
        assert any("threshold_24h" in e for e in errors)

    def test_normal_interval_must_be_ge_low(self, default_config):
        default_config.normal_interval_min = 0.5
        default_config.low_interval_min = 1.0
        errors = default_config.validate()
        assert any("normal_interval_min" in e for e in errors)


class TestRegenRate:
    """Test the regen_rate_per_hour property."""

    def test_default_rate(self, default_config):
        """2% per 4 hours = 0.5%/hour."""
        assert default_config.regen_rate_per_hour == 0.5

    def test_custom_rate(self, default_config):
        default_config.regen_percent = 5.0
        default_config.regen_interval_hours = 2.0
        assert default_config.regen_rate_per_hour == 2.5
