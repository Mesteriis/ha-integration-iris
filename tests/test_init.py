from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from custom_components.iris.const import CONF_API_URL, DOMAIN, EVENT_DASHBOARD_UPDATED
from homeassistant.components.frontend import DATA_PANELS
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


async def test_setup_entry_populates_runtime_data_and_starts_websocket(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=build_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=build_state_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ) as async_start,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    runtime = entry.runtime_data
    assert runtime.store.bootstrap is not None
    assert runtime.store.bootstrap.instance.instance_id == "iris-main-001"
    assert runtime.store.websocket_connected is False
    assert runtime.store.entity_state("system.connection")["state"] is True
    assert runtime.store.tracked_collection_keys() == [
        "assets.snapshot",
        "integrations.snapshot",
        "portfolio.snapshot",
        "predictions.snapshot",
    ]
    assert runtime.dashboard.summary()["slug"] == "iris"
    assert runtime.dashboard.summary()["views_count"] == 7
    assert runtime.dashboard.summary()["lovelace_synced"] is True
    assert runtime.dashboard.summary()["lovelace_management_mode"] == "managed"
    assert runtime.dashboard.summary()["lovelace_dashboard_url_path"] == "lovelace-iris-iris-main-001"
    assert "lovelace-iris-iris-main-001" in hass.data[DATA_PANELS]
    lovelace_config = await hass.data["lovelace"]["dashboards"]["lovelace-iris-iris-main-001"].async_load(False)
    assert [view["title"] for view in lovelace_config["views"]] == [
        "Overview",
        "Assets",
        "Signals",
        "Predictions",
        "Portfolio",
        "Integrations",
        "System",
    ]
    assert lovelace_config["views"][0]["cards"][0]["type"] == "vertical-stack"
    assert lovelace_config["views"][1]["cards"][0]["cards"][1]["cards"][1]["type"] == "grid"
    async_start.assert_called_once()


async def test_dashboard_runtime_publishes_initial_and_refresh_events(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)
    dashboard_events: list[dict] = []
    remove_listener = hass.bus.async_listen(
        EVENT_DASHBOARD_UPDATED,
        lambda event: dashboard_events.append(event.data),
    )

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=build_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=build_state_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    refreshed_dashboard = deepcopy(build_dashboard())
    refreshed_dashboard["title"] = "IRIS Main Updated"
    refreshed_dashboard["views"] = [
        {
            "view_key": "overview",
            "title": "Overview",
            "sections": [
                {
                    "section_key": "system",
                    "title": "System",
                    "widgets": [
                        {"widget_key": "system_status", "title": "Connection", "kind": "status"},
                    ],
                }
            ],
        }
    ]
    entry.runtime_data.client.async_get_dashboard = AsyncMock(return_value=refreshed_dashboard)

    reconnect_requested = await entry.runtime_data.websocket._async_handle_message(
        {
            "type": "dashboard_changed",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 5,
        }
    )
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    remove_listener()

    assert reconnect_requested is True
    assert dashboard_events[0]["reason"] == "initial_load"
    assert dashboard_events[0]["slug"] == "iris"
    assert dashboard_events[1]["reason"] == "dashboard_changed"
    assert dashboard_events[1]["title"] == "IRIS Main Updated"
    assert dashboard_events[1]["views_count"] == 1
    assert dashboard_events[1]["sections_count"] == 1
    assert dashboard_events[1]["widgets_count"] == 1
    assert dashboard_events[1]["lovelace_synced"] is True
    assert entry.runtime_data.dashboard.summary()["title"] == "IRIS Main Updated"
    lovelace_config = await hass.data["lovelace"]["dashboards"]["lovelace-iris-iris-main-001"].async_load(False)
    assert lovelace_config["title"] == "IRIS Main Updated"
    assert lovelace_config["views"][0]["title"] == "Overview"


async def test_dashboard_runtime_live_refreshes_collection_widgets_from_store(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=build_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=build_state_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entry.runtime_data.store.apply_websocket_message(
        {
            "type": "collection_patch",
            "projection_epoch": "20260315T000000Z-stage5",
            "sequence": 5,
            "collection_key": "assets.snapshot",
            "op": "upsert",
            "path": "SOLUSD",
            "value": {
                "symbol": "SOLUSD",
                "decision": "BUY",
                "market_regime": "bull_trend",
                "confidence": 0.73,
                "pattern_state": "boosted",
            },
        }
    )
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()

    lovelace_config = await hass.data["lovelace"]["dashboards"]["lovelace-iris-iris-main-001"].async_load(False)
    assets_grid = lovelace_config["views"][1]["cards"][0]["cards"][1]["cards"][1]
    rendered_cards = assets_grid["cards"]
    assert any(card.get("title") == "SOLUSD" for card in rendered_cards)


async def test_dashboard_runtime_preserves_local_override_layout(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=build_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=build_state_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    dashboard_store = hass.data["lovelace"]["dashboards"]["lovelace-iris-iris-main-001"]
    local_override = {
        "title": "IRIS Custom",
        "views": [{"title": "Custom View", "path": "custom", "cards": [{"type": "markdown", "content": "local"}]}],
    }
    await dashboard_store.async_save(local_override)

    entry.runtime_data.store.apply_websocket_message(
        {
            "type": "collection_patch",
            "projection_epoch": "20260315T000000Z-stage5",
            "sequence": 5,
            "collection_key": "assets.snapshot",
            "op": "upsert",
            "path": "ADAUSD",
            "value": {
                "symbol": "ADAUSD",
                "decision": "HOLD",
                "market_regime": "distribution",
                "confidence": 0.44,
            },
        }
    )
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()

    lovelace_config = await dashboard_store.async_load(False)
    assert lovelace_config == local_override
    assert entry.runtime_data.dashboard.summary()["lovelace_management_mode"] == "local_override"
    assert entry.runtime_data.dashboard.summary()["lovelace_override_detected"] is True
    assert entry.runtime_data.dashboard.summary()["lovelace_synced"] is False
