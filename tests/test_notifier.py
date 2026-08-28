"""Tests for TelegramNotifier and MockNotifier."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from synthetic_usage_awareness.notifier import MockNotifier, TelegramNotifier
from synthetic_usage_awareness.usage_tracker import Alert, AlertLevel

# ---------------------------------------------------------------------------
# MockNotifier
# ---------------------------------------------------------------------------


class TestMockNotifier:
    """Test the MockNotifier test helper."""

    def test_send_message_captures(self):
        mock = MockNotifier()
        mock.send_message("hello")
        assert mock.count == 1
        assert mock.sent == ["hello"]

    def test_send_alert_captures(self):
        mock = MockNotifier()
        alert = Alert(level=AlertLevel.SLEEP_8H, message="test", remaining=70.0, consumed=4.0)
        mock.send_alert(alert)
        assert mock.count == 1
        assert mock.sent[0] is alert

    def test_clear(self):
        mock = MockNotifier()
        mock.send_message("a")
        mock.send_message("b")
        assert mock.count == 2
        mock.clear()
        assert mock.count == 0

    def test_test_connection_returns_true(self):
        mock = MockNotifier()
        assert mock.test_connection() is True

    def test_multiple_sends(self):
        mock = MockNotifier()
        for i in range(10):
            mock.send_message(f"msg {i}")
        assert mock.count == 10
        assert mock.sent[5] == "msg 5"


# ---------------------------------------------------------------------------
# TelegramNotifier — mocked HTTP
# ---------------------------------------------------------------------------


class TestTelegramNotifier:
    """Test TelegramNotifier with mocked urllib."""

    def _mock_response(self, ok=True, description=""):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "ok": ok,
                "result": {} if ok else {},
                "description": description,
            }
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_success(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        assert notifier.send_message("test message") is True

        # Verify the request was constructed correctly
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_method() == "POST"
        body = json.loads(req.data.decode("utf-8"))
        assert body["chat_id"] == "-1001234567890"
        assert body["text"] == "test message"
        assert body["parse_mode"] == "Markdown"

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_with_thread_id(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890", thread_id="3649")
        notifier.send_message("test")

        body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert body["message_thread_id"] == 3649

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_without_thread_id(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890", thread_id="")
        notifier.send_message("test")

        body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert "message_thread_id" not in body

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_api_error(self, mock_urlopen):
        """API returns ok=false → send_message returns False."""
        mock_urlopen.return_value = self._mock_response(ok=False, description="chat not found")
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        assert notifier.send_message("test") is False

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_http_error(self, mock_urlopen):
        """HTTP error → send_message returns False."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.telegram.org/bot123/sendMessage",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )
        notifier = TelegramNotifier("bad:token", "-1001234567890")
        assert notifier.send_message("test") is False

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_message_network_error(self, mock_urlopen):
        """Network error → send_message returns False."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        assert notifier.send_message("test") is False

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_send_alert(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        alert = Alert(level=AlertLevel.SLEEP_8H, message="🌙 test", remaining=70.0, consumed=4.0)
        assert notifier.send_alert(alert) is True

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_invalid_thread_id_ignored(self, mock_urlopen):
        """Invalid thread_id is ignored gracefully."""
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890", thread_id="not_a_number")
        notifier.send_message("test")

        body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        assert "message_thread_id" not in body

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_test_connection_success(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(ok=True)
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        assert notifier.test_connection() is True

    @patch("synthetic_usage_awareness.notifier.urllib.request.urlopen")
    def test_test_connection_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("network error")
        notifier = TelegramNotifier("123:ABC", "-1001234567890")
        assert notifier.test_connection() is False
