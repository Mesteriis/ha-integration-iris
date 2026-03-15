from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from custom_components.iris.const import CONF_API_URL, DOMAIN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


def _extended_catalog() -> dict:
    catalog = deepcopy(build_catalog())
    catalog["entities"].extend(
        [
            {
                "entity_key": "events.last_decision",
                "platform": "event",
                "name": "Last Decision Event",
                "state_source": "events.last_decision",
                "icon": "mdi:flash",
                "availability": {"modes": ["full"], "requires_features": [], "status": "active"},
                "since_version": "2026.03.15",
                "event_types": ["decision_generated", "decision_updated"],
            },
        ]
    )
    return catalog


def _extended_snapshot() -> dict:
    snapshot = deepcopy(build_state_snapshot())
    snapshot["entities"].update(
        {
            "settings.default_timeframe": {
                "state": "4h",
                "attributes": {
                    "command_key": "settings.default_timeframe.set",
                    "options": ["15m", "1h", "4h", "1d"],
                },
            },
            "events.last_decision": {
                "state": "evt_001",
                "attributes": {
                    "event_type": "decision_generated",
                    "symbol": "BTCUSD",
                    "decision": "BUY",
                },
            },
        }
    )
    return snapshot


async def test_catalog_platforms_materialize_additional_adr_platforms(hass) -> None:
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
            new=AsyncMock(return_value=_extended_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=_extended_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    switch_entity_id = registry.async_get_entity_id(
        "switch",
        DOMAIN,
        "iris-main-001:settings.notifications_enabled",
    )
    button_entity_id = registry.async_get_entity_id(
        "button",
        DOMAIN,
        "iris-main-001:actions.portfolio_sync",
    )
    select_entity_id = registry.async_get_entity_id(
        "select",
        DOMAIN,
        "iris-main-001:settings.default_timeframe",
    )
    event_entity_id = registry.async_get_entity_id(
        "event",
        DOMAIN,
        "iris-main-001:events.last_decision",
    )

    assert switch_entity_id is not None
    assert button_entity_id is not None
    assert select_entity_id is not None
    assert event_entity_id is not None
    assert hass.states.get(switch_entity_id).state == "on"
    assert hass.states.get(select_entity_id).state == "4h"
    assert hass.states.get(select_entity_id).attributes["options"] == ["15m", "1h", "4h", "1d"]
    assert hass.states.get(event_entity_id).attributes["event_type"] == "decision_generated"


async def test_catalog_event_entity_tracks_runtime_store_updates(hass) -> None:
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
            new=AsyncMock(return_value=_extended_catalog()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=_extended_snapshot()),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    event_entity_id = registry.async_get_entity_id(
        "event",
        DOMAIN,
        "iris-main-001:events.last_decision",
    )
    assert event_entity_id is not None

    entry.runtime_data.store.apply_websocket_message(
        {
            "type": "entity_state_changed",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 5,
            "entity_key": "events.last_decision",
            "state": "evt_002",
            "attributes": {
                "event_type": "decision_updated",
                "symbol": "ETHUSD",
                "decision": "HOLD",
            },
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get(event_entity_id)
    assert state is not None
    assert state.attributes["event_type"] == "decision_updated"
    assert state.attributes["symbol"] == "ETHUSD"
