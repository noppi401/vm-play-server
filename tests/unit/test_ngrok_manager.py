from unittest.mock import Mock

import pytest

from aivenv.tunnel.ngrok_manager import NgrokError, NgrokManager


def test_open_tunnel_forwards_log_server_port_and_returns_public_url():
    listener = Mock()
    listener.url.return_value = "https://example.ngrok.app"
    ngrok = Mock()
    ngrok.forward.return_value = listener

    manager = NgrokManager(log_server_port=8765, auth_token="secret-token", ngrok_module=ngrok)

    assert manager.open_tunnel() == "https://example.ngrok.app"
    ngrok.forward.assert_called_once_with(8765, authtoken="secret-token")


def test_open_tunnel_is_idempotent():
    listener = Mock()
    listener.url.return_value = "https://example.ngrok.app"
    ngrok = Mock()
    ngrok.forward.return_value = listener
    manager = NgrokManager(log_server_port=8765, ngrok_module=ngrok)

    assert manager.open_tunnel() == "https://example.ngrok.app"
    assert manager.open_tunnel() == "https://example.ngrok.app"
    ngrok.forward.assert_called_once_with(8765, authtoken_from_env=True)


def test_close_tunnel_disconnects_public_url_once_and_is_idempotent():
    listener = Mock()
    listener.url.return_value = "https://example.ngrok.app"
    ngrok = Mock()
    ngrok.forward.return_value = listener
    manager = NgrokManager(log_server_port=8765, ngrok_module=ngrok)

    manager.open_tunnel()
    manager.close_tunnel()
    manager.close_tunnel()

    ngrok.disconnect.assert_called_once_with("https://example.ngrok.app")


def test_open_tunnel_wraps_sdk_exceptions_without_token_in_message():
    ngrok = Mock()
    ngrok.forward.side_effect = RuntimeError("boom secret-token")
    manager = NgrokManager(log_server_port=8765, auth_token="secret-token", ngrok_module=ngrok)

    with pytest.raises(NgrokError) as exc_info:
        manager.open_tunnel()

    assert "secret-token" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_close_tunnel_wraps_sdk_exceptions_without_token_in_message():
    listener = Mock()
    listener.url.return_value = "https://example.ngrok.app"
    ngrok = Mock()
    ngrok.forward.return_value = listener
    ngrok.disconnect.side_effect = RuntimeError("boom secret-token")
    manager = NgrokManager(log_server_port=8765, auth_token="secret-token", ngrok_module=ngrok)

    manager.open_tunnel()

    with pytest.raises(NgrokError) as exc_info:
        manager.close_tunnel()

    assert "secret-token" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)