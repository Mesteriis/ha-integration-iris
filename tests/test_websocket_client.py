from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from aiohttp import WSMsgType
from custom_components.iris.client import IrisApiClient
from custom_components.iris.store import IrisRuntimeStore
from custom_components.iris.websocket_client import IrisWebSocketClient

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


class FakeWebSocketMessage:
    def __init__(self, message_type: WSMsgType, payload: dict | None = None) -> None:
        self.type = message_type
        self._payload = payload

    def json(self) -> dict | None:
        return self._payload


class FakeWebSocket:
    def __init__(self, incoming: list[FakeWebSocketMessage | Exception]) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive(self, timeout: float | None = None) -> FakeWebSocketMessage:
        del timeout
        if not self._incoming:
            return FakeWebSocketMessage(WSMsgType.CLOSE)
        item = self._incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class FakeWebSocketContext:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self._websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self._websocket

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


class FakeSession:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self._websocket = websocket
        self.connect_calls: list[dict] = []

    def ws_connect(self, url: str, **kwargs) -> FakeWebSocketContext:
        self.connect_calls.append({"url": url, **kwargs})
        return FakeWebSocketContext(self._websocket)


async def test_websocket_client_connect_once_performs_handshake_and_subscribe(hass) -> None:
    bootstrap = build_bootstrap()
    catalog = build_catalog()
    dashboard = build_dashboard()
    snapshot = build_state_snapshot()
    websocket = FakeWebSocket(
        [
            FakeWebSocketMessage(
                WSMsgType.TEXT,
                {"type": "welcome", "protocol_version": 1},
            ),
            FakeWebSocketMessage(WSMsgType.CLOSE),
        ]
    )
    session = FakeSession(websocket)
    client = IrisApiClient(hass, "http://localhost:8000", session=session)
    client.async_get_bootstrap = AsyncMock(return_value=bootstrap)
    client.async_get_catalog = AsyncMock(return_value=catalog)
    client.async_get_dashboard = AsyncMock(return_value=dashboard)
    client.async_get_state = AsyncMock(return_value=snapshot)
    store = IrisRuntimeStore()
    websocket_client = IrisWebSocketClient(hass, client, store)

    reconnect_requested = await websocket_client._async_connect_once()

    assert reconnect_requested is False
    assert session.connect_calls[0]["url"] == bootstrap.ws_url
    assert websocket.sent[0]["type"] == "hello"
    assert websocket.sent[1] == {
        "type": "subscribe",
        "entities": store.tracked_entity_keys(),
        "collections": store.tracked_collection_keys(),
        "operations": True,
        "catalog": True,
        "dashboard": True,
    }
    assert store.bootstrap is not None
    assert store.projection_epoch == snapshot["projection_epoch"]
    assert store.sequence == snapshot["sequence"]
    assert store.websocket_connected is False


async def test_websocket_client_resync_required_refreshes_state_and_requests_reconnect(hass) -> None:
    bootstrap = build_bootstrap()
    initial_snapshot = build_state_snapshot()
    refreshed_snapshot = deepcopy(initial_snapshot)
    refreshed_snapshot["sequence"] = 9
    refreshed_snapshot["entities"]["market.summary.active_assets_count"]["state"] = 7

    store = IrisRuntimeStore()
    store.apply_bootstrap(bootstrap)
    store.apply_state_snapshot(initial_snapshot)

    client = IrisApiClient(hass, "http://localhost:8000")
    client.async_get_state = AsyncMock(return_value=refreshed_snapshot)
    websocket_client = IrisWebSocketClient(hass, client, store)

    reconnect_requested = await websocket_client._async_handle_message(
        {
            "type": "resync_required",
            "reason": "queue_overflow",
            "state_url": "/api/v1/ha/state",
        }
    )

    assert reconnect_requested is True
    client.async_get_state.assert_awaited_once_with(bootstrap.state_url)
    assert store.sequence == 9
    assert store.entity_state("market.summary.active_assets_count")["state"] == 7
    assert store.last_error is None


async def test_websocket_client_execute_command_waits_for_matching_ack(hass) -> None:
    client = IrisApiClient(hass, "http://localhost:8000")
    store = IrisRuntimeStore()
    websocket = FakeWebSocket([])
    websocket_client = IrisWebSocketClient(hass, client, store)
    websocket_client._active_ws = websocket

    command_task = hass.async_create_task(
        websocket_client.async_execute_command(command="portfolio.sync", payload={})
    )
    await asyncio.sleep(0)

    request = websocket.sent[0]
    assert request["type"] == "command_execute"
    assert request["command"] == "portfolio.sync"

    reconnect_requested = await websocket_client._async_handle_message(
        {
            "type": "command_ack",
            "request_id": request["request_id"],
            "accepted": True,
            "operation_id": "op_123",
        }
    )
    result = await command_task

    assert reconnect_requested is False
    assert result["accepted"] is True
    assert result["operation_id"] == "op_123"


async def test_websocket_client_catalog_changed_refreshes_catalog_and_triggers_reload(hass) -> None:
    bootstrap = build_bootstrap()
    initial_catalog = build_catalog()
    refreshed_catalog = deepcopy(initial_catalog)
    refreshed_catalog["catalog_version"] = "sha1:updated"
    refreshed_catalog["entities"].append(
        {
            "entity_key": "market.summary.new_metric",
            "platform": "sensor",
            "name": "New Metric",
            "state_source": "market.summary.new_metric",
        }
    )

    store = IrisRuntimeStore()
    store.apply_bootstrap(bootstrap)
    store.apply_catalog(initial_catalog)

    client = IrisApiClient(hass, "http://localhost:8000")
    client.async_get_catalog = AsyncMock(return_value=refreshed_catalog)
    reload_calls: list[str] = []
    websocket_client = IrisWebSocketClient(
        hass,
        client,
        store,
        on_catalog_refreshed=lambda: reload_calls.append("reload"),
    )

    reconnect_requested = await websocket_client._async_handle_message(
        {
            "type": "catalog_changed",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 5,
        }
    )

    assert reconnect_requested is True
    client.async_get_catalog.assert_awaited_once_with(bootstrap.catalog_url)
    assert reload_calls == ["reload"]
    assert any(
        entity.get("entity_key") == "market.summary.new_metric"
        for entity in store.catalog.get("entities", [])
        if isinstance(entity, dict)
    )


async def test_websocket_client_dashboard_changed_refreshes_dashboard(hass) -> None:
    bootstrap = build_bootstrap()
    initial_dashboard = build_dashboard()
    refreshed_dashboard = deepcopy(initial_dashboard)
    refreshed_dashboard["title"] = "IRIS Main Updated"

    store = IrisRuntimeStore()
    store.apply_bootstrap(bootstrap)
    store.apply_dashboard(initial_dashboard)

    client = IrisApiClient(hass, "http://localhost:8000")
    client.async_get_dashboard = AsyncMock(return_value=refreshed_dashboard)
    dashboard_refresh_calls: list[str] = []
    websocket_client = IrisWebSocketClient(
        hass,
        client,
        store,
        on_dashboard_refreshed=lambda: dashboard_refresh_calls.append("refresh"),
    )

    reconnect_requested = await websocket_client._async_handle_message(
        {
            "type": "dashboard_changed",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 5,
        }
    )

    assert reconnect_requested is True
    client.async_get_dashboard.assert_awaited_once_with(bootstrap.dashboard_url)
    assert dashboard_refresh_calls == ["refresh"]
    assert store.dashboard["title"] == "IRIS Main Updated"


async def test_websocket_client_fires_domain_events_from_event_envelope(hass) -> None:
    all_events: list[dict] = []
    typed_events: list[dict] = []

    remove_all = hass.bus.async_listen("iris.event", lambda event: all_events.append(event.data))
    remove_typed = hass.bus.async_listen("iris.decision_generated", lambda event: typed_events.append(event.data))

    client = IrisApiClient(hass, "http://localhost:8000")
    store = IrisRuntimeStore()
    websocket_client = IrisWebSocketClient(hass, client, store)

    reconnect_requested = await websocket_client._async_handle_message(
        {
            "type": "event_emitted",
            "event_type": "decision_generated",
            "event_id": "evt-001",
            "source": "decision_engine",
            "payload": {"decision": "BUY"},
            "timestamp": "2026-03-15T12:00:00Z",
        }
    )
    await hass.async_block_till_done()

    remove_all()
    remove_typed()

    assert reconnect_requested is False
    assert all_events[0]["event_type"] == "decision_generated"
    assert typed_events[0]["payload"]["decision"] == "BUY"


async def test_websocket_client_run_forever_skips_backoff_after_immediate_reconnect(hass) -> None:
    client = IrisApiClient(hass, "http://localhost:8000")
    store = IrisRuntimeStore()
    websocket_client = IrisWebSocketClient(hass, client, store)

    attempts = 0

    async def _fake_connect_once() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return True
        websocket_client._stop_event.set()
        return False

    sleep_mock = AsyncMock()
    with (
        patch.object(websocket_client, "_async_connect_once", side_effect=_fake_connect_once),
        patch("custom_components.iris.websocket_client.asyncio.sleep", new=sleep_mock),
    ):
        await websocket_client._run_forever()

    assert attempts == 2
    sleep_mock.assert_not_awaited()
