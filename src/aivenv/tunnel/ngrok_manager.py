"""Ngrok tunnel management for the local log server."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NgrokError(RuntimeError):
    """Raised when ngrok tunnel operations fail."""


class NgrokManager:
    """Manage a single ngrok tunnel for the log server."""

    _NGROK_API_BASE = "https://api.ngrok.com"

    def __init__(
        self,
        log_server_port: int,
        auth_token: Optional[str] = None,
        domain: Optional[str] = None,
        api_key: Optional[str] = None,
        ngrok_module: Optional[Any] = None,
        **forward_options: Any,
    ) -> None:
        self.log_server_port = log_server_port
        self.auth_token = auth_token
        self.domain = domain
        self.api_key = api_key
        self.forward_options = forward_options
        self._ngrok = ngrok_module
        self._listener: Optional[Any] = None
        self._ngrok_session: Optional[Any] = None
        self._public_url: Optional[str] = None

    async def open_tunnel(self) -> str:
        """Delete any existing endpoints, open a new tunnel, and return its public URL."""
        if self._public_url is not None:
            return self._public_url

        if self.api_key:
            stopped = await asyncio.get_event_loop().run_in_executor(None, self._delete_all_endpoints)
            if stopped:
                await asyncio.sleep(3)

        ngrok = self._get_ngrok()
        try:
            listener = await self._forward(ngrok)
        except Exception as exc:
            raise NgrokError("Failed to open ngrok tunnel") from exc

        try:
            self._listener = listener
            self._public_url = self._listener.url()
        except Exception as exc:
            raise NgrokError("Failed to open ngrok tunnel") from exc

        return self._public_url

    async def _forward(self, ngrok: Any) -> Any:
        loop = asyncio.get_running_loop()

        def _stop_callback() -> None:
            asyncio.run_coroutine_threadsafe(self._close_session(), loop)

        builder = ngrok.SessionBuilder()

        if self.auth_token:
            builder = builder.authtoken(self.auth_token)
        else:
            builder = builder.authtoken_from_env()

        builder = builder.handle_stop_command(_stop_callback)

        session = builder.connect()
        if hasattr(session, "__await__"):
            session = await session
        self._ngrok_session = session

        ep = session.http_endpoint()
        if self.domain:
            ep = ep.domain(self.domain)

        listener = ep.listen_and_forward(f"http://127.0.0.1:{self.log_server_port}")
        if hasattr(listener, "__await__"):
            listener = await listener
        return listener

    async def _close_session(self) -> None:
        session = self._ngrok_session
        if session is not None:
            self._ngrok_session = None
            self._listener = None
            self._public_url = None
            with contextlib.suppress(Exception):
                result = session.close()
                if hasattr(result, "__await__"):
                    await result

    async def close_tunnel(self) -> None:
        """Close the active listener and session."""
        if self._public_url is None and self._listener is None:
            return

        for obj in (self._listener, self._ngrok_session):
            if obj is None:
                continue
            with contextlib.suppress(Exception):
                close = getattr(obj, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result

        self._listener = None
        self._ngrok_session = None
        self._public_url = None

    def _get_ngrok(self) -> Any:
        if self._ngrok is None:
            self._ngrok = importlib.import_module("ngrok")
        return self._ngrok

    def _ngrok_api_request(self, path: str, method: str = "GET", body: bytes | None = None) -> Any:
        if method == "POST" and body is None:
            body = b"{}"
        req = urllib.request.Request(
            f"{self._NGROK_API_BASE}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Ngrok-Version": "2",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {error_body}") from exc

    def _delete_all_endpoints(self) -> bool:
        """Stop all active ngrok tunnel sessions via the API. Returns True if any were stopped."""
        try:
            data = self._ngrok_api_request("/endpoints")
        except Exception as exc:
            logger.warning("ngrok API: failed to list endpoints: %s", exc)
            return False

        endpoints = (data or {}).get("endpoints", [])
        logger.info("ngrok API: found %d endpoint(s)", len(endpoints))
        stopped_any = False
        for ep in endpoints:
            ep_url = ep.get("public_url", ep.get("id"))
            ts_id = (ep.get("tunnel_session") or {}).get("id")
            if ts_id:
                try:
                    self._ngrok_api_request(f"/tunnel_sessions/{ts_id}/stop", method="POST")
                    logger.info("ngrok API: stopped tunnel session for %s", ep_url)
                    stopped_any = True
                except Exception as exc:
                    logger.warning("ngrok API: failed to stop tunnel session for %s: %s", ep_url, exc)
        return stopped_any
