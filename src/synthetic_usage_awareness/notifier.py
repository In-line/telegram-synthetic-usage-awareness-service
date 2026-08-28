"""Telegram notifier — sends alerts via the Telegram Bot API.

Uses urllib (stdlib) to avoid external dependencies.
Sends to a specific chat_id with optional message_thread_id for forum topics.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger("synthetic_usage_awareness.notifier")


class TelegramNotifier:
    """Sends alert messages via the Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str, thread_id: str = ""):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a text message. Returns True on success, False on failure."""
        url = f"{self._base_url}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if self._thread_id:
            try:
                payload["message_thread_id"] = int(self._thread_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid thread_id '{self._thread_id}' — ignoring")

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    logger.debug(f"Telegram message sent to chat {self._chat_id}")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description', 'unknown')}")
                    return False
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            logger.error(f"Telegram HTTP {e.code}: {body}")
            return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_alert(self, alert) -> bool:
        """Send an Alert object. Returns True on success."""
        return self.send_message(alert.message)

    def test_connection(self) -> bool:
        """Test if the bot token and chat ID are valid."""
        url = f"{self._base_url}/getChat"
        payload = {"chat_id": self._chat_id}
        if self._thread_id:
            try:
                payload["message_thread_id"] = int(self._thread_id)
            except (ValueError, TypeError):
                pass
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("ok", False)
        except Exception as e:
            logger.error(f"Telegram test connection failed: {e}")
            return False


class MockNotifier:
    """Captures alerts instead of sending them. For testing."""

    def __init__(self) -> None:
        self.sent: list = []  # list of (alert, text)

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        self.sent.append(text)
        return True

    def send_alert(self, alert) -> bool:
        self.sent.append(alert)
        return True

    def test_connection(self) -> bool:
        return True

    @property
    def count(self) -> int:
        return len(self.sent)

    def clear(self) -> None:
        self.sent.clear()
