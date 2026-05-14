"""Ngrok tunnel management for the local log server."""

from __future__ import annotations

import importlib
from typing import Any, Optional


class NgrokError(RuntimeError):
    """Raised when ngrok tunnel operations fail."""


class NgrokManager:
    """Manage a single ngrok tunnel for the log server."""

    def __init__(
        self,
        log_server_port: int,
        auth_token: Optional[str] = None,
        domain: Optional[str] = None,
        ngrok_module: Optional[Any] = None,
        **forward_options: Any,
    ) -> None:
        self.log_server_port = log_server_port
        self.auth_token = auth_token
        self.domain = domain
        self.forward_options = forward_options
        self._ngrok = ngrok_module
        self._listener: Optional[Any] = None
        self._public_url: Optional[str] = None

    def open_tunnel(self) -> str:
        """Open the ngrok tunnel if needed and return its public URL."""
        if self._public_url is not None:
            return self._public_url

        options = dict(self.forward_options)
        if self.auth_token:
            options["authtoken"] = self.auth_token
        else:
            options.setdefault("authtoken_from_env", True)

        if self.domain:
            options["domain"] = self.domain

        try:
            ngrok = self._get_ngrok()
            self._listener = ngrok.forward(self.log_server_port, **options)
            self._public_url = self._listener.url()
        except Exception as exc:
            raise NgrokError("Failed to open ngrok tunnel") from exc

        return self._public_url

    def close_tunnel(self) -> None:
        """Close the active tunnel, if any."""
        if self._public_url is None and self._listener is None:
            return

        public_url = self._public_url
        try:
            ngrok = self._get_ngrok()
            if public_url is not None:
                ngrok.disconnect(public_url)
            else:
                ngrok.disconnect()
        except Exception as exc:
            raise NgrokError("Failed to close ngrok tunnel") from exc

        self._listener = None
        self._public_url = None

    def _get_ngrok(self) -> Any:
        if self._ngrok is None:
            self._ngrok = importlib.import_module("ngrok")
        return self._ngrok


_default_manager: Optional[NgrokManager] = None


def open_tunnel(
    log_server_port: int,
    auth_token: Optional[str] = None,
    domain: Optional[str] = None,
    **forward_options: Any,
    ) -> str:
    """Open the default ngrok tunnel and return its public URL."""
    global _default_manager
    if _default_manager is None:
        _default_manager = NgrokManager(
            log_server_port=log_server_port,
            auth_token=auth_token,
            domain=domain,
            **forward_options,
        )
    return _default_manager.open_tunnel()


def close_tunnel() -> None:
    """Close the default ngrok tunnel, if it exists."""
    global _default_manager
    if _default_manager is None:
        return
    _default_manager.close_tunnel()
    _default_manager = None