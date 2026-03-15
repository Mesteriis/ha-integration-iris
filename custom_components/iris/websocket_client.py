from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientWebSocketResponse, WSMsgType
from homeassistant.core import HomeAssistant

from .client import IrisApiClient, IrisAuthenticationError, IrisConnectionError, IrisProtocolError
from .const import (
    COMMAND_ACK_TIMEOUT,
    DEFAULT_RECONNECT_MAX_DELAY,
    DEFAULT_RECONNECT_MIN_DELAY,
    DOMAIN,
    INTEGRATION_VERSION,
    SUPPORTED_PROTOCOL_VERSION,
    WEBSOCKET_HANDSHAKE_TIMEOUT,
    WEBSOCKET_RECEIVE_TIMEOUT,
)
from .store import IrisRuntimeStore
from .versioning import IrisCompatibilityError, validate_bootstrap_compatibility


class IrisWebSocketClient:
    def __init__(
        self,
        hass: HomeAssistant,
        client: IrisApiClient,
        store: IrisRuntimeStore,
        *,
        on_catalog_refreshed: Callable[[], None] | None = None,
        on_dashboard_refreshed: Callable[[], None] | None = None,
    ) -> None:
        self._hass = hass
        self._client = client
        self._store = store
        self._on_catalog_refreshed = on_catalog_refreshed
        self._on_dashboard_refreshed = on_dashboard_refreshed
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._active_ws: ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._pending_command_acks: dict[str, asyncio.Future[dict[str, Any]]] = {}

    def async_start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = self._hass.async_create_background_task(
            self._run_forever(),
            f"{DOMAIN}_websocket_runtime",
        )

    async def async_stop(self) -> None:
        self._stop_event.set()
        if self._active_ws is not None:
            await self._active_ws.close()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._active_ws = None
        self._fail_pending_command_acks(IrisConnectionError("IRIS websocket session stopped."))
        self._store.set_connection_state(False)

    async def async_execute_command(self, *, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = f"req_{uuid4().hex}"
        future: asyncio.Future[dict[str, Any]] = self._hass.loop.create_future()
        self._pending_command_acks[request_id] = future
        try:
            websocket = self._active_ws
            if websocket is None:
                raise IrisConnectionError("IRIS websocket is not connected.")
            await self._async_send_json(
                websocket,
                {
                    "type": "command_execute",
                    "command": command,
                    "payload": payload,
                    "request_id": request_id,
                },
            )
            return await asyncio.wait_for(future, timeout=COMMAND_ACK_TIMEOUT)
        except TimeoutError as exc:
            raise IrisProtocolError(f"IRIS command acknowledgement timed out for '{command}'.") from exc
        finally:
            self._pending_command_acks.pop(request_id, None)

    async def _run_forever(self) -> None:
        delay = DEFAULT_RECONNECT_MIN_DELAY
        while not self._stop_event.is_set():
            reconnect_immediately = False
            try:
                reconnect_immediately = await self._async_connect_once()
                delay = DEFAULT_RECONNECT_MIN_DELAY
            except IrisAuthenticationError as exc:
                self._store.set_connection_state(False, error=str(exc))
                return
            except (IrisCompatibilityError, IrisConnectionError, IrisProtocolError, ClientError, OSError) as exc:
                self._store.set_connection_state(False, error=str(exc))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                self._store.set_connection_state(False, error=str(exc))
            if self._stop_event.is_set():
                return
            if reconnect_immediately:
                continue
            await asyncio.sleep(delay)
            delay = min(delay * 2, DEFAULT_RECONNECT_MAX_DELAY)

    async def _async_connect_once(self) -> bool:
        current_catalog_version = self._store.bootstrap.instance.catalog_version if self._store.bootstrap else None
        bootstrap = await self._client.async_get_bootstrap()
        validate_bootstrap_compatibility(bootstrap)
        self._store.apply_bootstrap(bootstrap)
        if (
            not self._store.catalog
            or bootstrap.instance.catalog_version != current_catalog_version
        ):
            self._store.apply_catalog(await self._client.async_get_catalog(bootstrap.catalog_url))
        if not self._store.dashboard:
            self._store.apply_dashboard(await self._client.async_get_dashboard(bootstrap.dashboard_url))
        self._store.apply_state_snapshot(await self._client.async_get_state(bootstrap.state_url))

        async with self._client.session.ws_connect(
            bootstrap.ws_url,
            headers=self._client.headers,
            heartbeat=30,
            timeout=WEBSOCKET_HANDSHAKE_TIMEOUT,
        ) as websocket:
            self._active_ws = websocket
            await self._async_send_hello(websocket)
            await self._async_expect_welcome(websocket)
            await self._async_send_subscribe(websocket)
            self._store.set_connection_state(True)
            return await self._async_receive_loop(websocket)

    async def _async_send_hello(self, websocket: ClientWebSocketResponse) -> None:
        await self._async_send_json(
            websocket,
            {
                "type": "hello",
                "protocol_version": SUPPORTED_PROTOCOL_VERSION,
                "client": {"name": DOMAIN, "version": INTEGRATION_VERSION},
                "instance_id": self._store.bootstrap.instance.instance_id if self._store.bootstrap else None,
            }
        )

    async def _async_expect_welcome(self, websocket: ClientWebSocketResponse) -> None:
        message = await websocket.receive(timeout=WEBSOCKET_HANDSHAKE_TIMEOUT)
        if message.type != WSMsgType.TEXT:
            raise IrisProtocolError("IRIS websocket handshake did not return a JSON welcome message.")
        raw = message.json()
        if not isinstance(raw, dict) or raw.get("type") != "welcome":
            raise IrisProtocolError("IRIS websocket handshake did not return a welcome message.")
        protocol_version = raw.get("protocol_version")
        if protocol_version != SUPPORTED_PROTOCOL_VERSION:
            raise IrisCompatibilityError(
                "unsupported_protocol",
                f"Unexpected IRIS websocket protocol version: {protocol_version}",
            )

    async def _async_send_subscribe(self, websocket: ClientWebSocketResponse) -> None:
        await self._async_send_json(
            websocket,
            {
                "type": "subscribe",
                "entities": self._store.tracked_entity_keys(),
                "collections": self._store.tracked_collection_keys(),
                "operations": True,
                "catalog": True,
                "dashboard": True,
            }
        )

    async def _async_receive_loop(self, websocket: ClientWebSocketResponse) -> bool:
        reconnect_requested = False
        while not self._stop_event.is_set():
            try:
                message = await websocket.receive(timeout=WEBSOCKET_RECEIVE_TIMEOUT)
            except TimeoutError:
                await self._async_send_json(websocket, {"type": "ping", "timestamp": _utc_now_iso()})
                continue

            if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING}:
                break
            if message.type == WSMsgType.ERROR:
                raise IrisConnectionError("IRIS websocket transport reported an error.")
            if message.type != WSMsgType.TEXT:
                continue
            payload = message.json()
            if not isinstance(payload, dict):
                raise IrisProtocolError("IRIS websocket payload must be a JSON object.")
            should_reconnect = await self._async_handle_message(payload)
            if should_reconnect:
                reconnect_requested = True
                break
        self._store.set_connection_state(False)
        self._active_ws = None
        self._fail_pending_command_acks(IrisConnectionError("IRIS websocket disconnected."))
        return reconnect_requested

    async def _async_handle_message(self, payload: dict[str, Any]) -> bool:
        message_type = str(payload.get("type") or "")
        if message_type == "pong":
            return False
        if message_type == "command_ack":
            self._resolve_command_ack(payload)
            return False
        if message_type == "event_emitted":
            self._fire_domain_event(payload)
            return False

        actions = self._store.apply_websocket_message(payload)
        if "refresh_catalog" in actions and self._store.bootstrap is not None:
            self._store.apply_catalog(await self._client.async_get_catalog(self._store.bootstrap.catalog_url))
            if self._on_catalog_refreshed is not None:
                self._on_catalog_refreshed()
            return True
        if "refresh_dashboard" in actions and self._store.bootstrap is not None:
            self._store.apply_dashboard(await self._client.async_get_dashboard(self._store.bootstrap.dashboard_url))
            if self._on_dashboard_refreshed is not None:
                self._on_dashboard_refreshed()
            return True
        if "full_resync" in actions and self._store.bootstrap is not None:
            self._store.apply_state_snapshot(await self._client.async_get_state(self._store.bootstrap.state_url))
            return True
        return False

    def _fire_domain_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type") or "unknown")
        self._hass.bus.async_fire(f"{DOMAIN}.event", payload)
        self._hass.bus.async_fire(f"{DOMAIN}.{event_type}", payload)

    async def _async_send_json(self, websocket: ClientWebSocketResponse, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await websocket.send_json(payload)

    def _resolve_command_ack(self, payload: dict[str, Any]) -> None:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            raise IrisProtocolError("IRIS command acknowledgement is missing request_id.")
        future = self._pending_command_acks.pop(request_id, None)
        if future is None:
            return
        if not future.done():
            future.set_result(payload)

    def _fail_pending_command_acks(self, exc: Exception) -> None:
        pending = list(self._pending_command_acks.values())
        self._pending_command_acks.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
