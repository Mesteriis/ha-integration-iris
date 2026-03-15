from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.iris.const import CONF_API_URL, DOMAIN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


async def test_binary_sensor_platform_materializes_catalog_driven_entities(hass) -> None:
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

    registry = er.async_get(hass)
    materialized = [
        entity
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id and entity.domain == "binary_sensor"
    ]

    assert len(materialized) == 2
    unique_ids = {entity.unique_id for entity in materialized}
    assert "iris-main-001:system.connection" in unique_ids
    assert "iris-main-001:notifications.enabled" in unique_ids

    connection_entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, "iris-main-001:system.connection")
    notifications_entity_id = registry.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        "iris-main-001:notifications.enabled",
    )

    assert connection_entity_id is not None
    assert notifications_entity_id is not None
    assert hass.states.get(connection_entity_id).state == "on"
    assert hass.states.get(notifications_entity_id).state == "on"


async def test_binary_sensor_entities_follow_runtime_store_updates(hass) -> None:
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

    registry = er.async_get(hass)
    notifications_entity_id = registry.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        "iris-main-001:notifications.enabled",
    )
    assert notifications_entity_id is not None

    entry.runtime_data.store.apply_websocket_message(
        {
            "type": "entity_state_changed",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 5,
            "entity_key": "notifications.enabled",
            "state": False,
            "attributes": {},
        }
    )
    await hass.async_block_till_done()

    assert hass.states.get(notifications_entity_id).state == "off"
