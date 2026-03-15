from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from custom_components.iris.const import CONF_API_URL, DOMAIN
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler, RegistryEntryHider
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


async def test_sensor_platform_materializes_catalog_driven_sensors(hass) -> None:
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
        if entity.config_entry_id == entry.entry_id and entity.domain == "sensor"
    ]

    assert len(materialized) == 5
    unique_ids = {entity.unique_id for entity in materialized}
    assert "iris-main-001:system.mode" in unique_ids
    assert "iris-main-001:market.summary.active_assets_count" in unique_ids
    assert "iris-main-001:market.summary.hot_assets_count" in unique_ids
    assert "iris-main-001:portfolio.summary.portfolio_value" in unique_ids
    assert "iris-main-001:portfolio.summary.open_positions" in unique_ids

    mode_entity_id = registry.async_get_entity_id("sensor", DOMAIN, "iris-main-001:system.mode")
    value_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:portfolio.summary.portfolio_value",
    )

    assert mode_entity_id is not None
    assert hass.states.get(mode_entity_id).state == "full"
    assert value_entity_id is not None
    assert hass.states.get(value_entity_id).state == "125000.0"
    assert hass.states.get(value_entity_id).attributes["unit_of_measurement"] == "USD"
    assert registry.async_get(mode_entity_id).translation_key == "system_mode"


async def test_catalog_changed_adds_new_sensor_without_config_entry_reload(hass) -> None:
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

    refreshed_catalog = deepcopy(build_catalog())
    refreshed_catalog["catalog_version"] = "sha1:updated"
    refreshed_catalog["entities"].append(
        {
            "entity_key": "portfolio.summary.available_capital",
            "platform": "sensor",
            "name": "Available Capital",
            "state_source": "portfolio.summary.available_capital",
            "icon": "mdi:cash-multiple",
            "unit_of_measurement": "USD",
        }
    )
    entry.runtime_data.store.entities["portfolio.summary.available_capital"] = {
        "state": 42000.0,
        "attributes": {"currency": "USD"},
    }
    entry.runtime_data.client.async_get_catalog = AsyncMock(return_value=refreshed_catalog)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        reconnect_requested = await entry.runtime_data.websocket._async_handle_message(
            {
                "type": "catalog_changed",
                "projection_epoch": "20260315T000000Z-stage3",
                "sequence": 5,
            }
        )
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:portfolio.summary.available_capital",
    )

    assert reconnect_requested is True
    schedule_reload.assert_not_called()
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "42000.0"


async def test_sensor_platform_respects_catalog_lifecycle_defaults(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)

    catalog = deepcopy(build_catalog())
    catalog["entities"].extend(
        [
            {
                "entity_key": "market.summary.experimental_score",
                "platform": "sensor",
                "name": "Experimental Score",
                "state_source": "market.summary.experimental_score",
                "icon": "mdi:flask-outline",
                "availability": {"modes": ["full"], "status": "hidden"},
            },
            {
                "entity_key": "portfolio.summary.internal_health",
                "platform": "sensor",
                "name": "Internal Health",
                "state_source": "portfolio.summary.internal_health",
                "icon": "mdi:heart-pulse",
                "availability": {"modes": ["full"], "requires_features": [], "status": "active"},
                "since_version": "2026.03.15",
                "entity_registry_enabled_default": False,
            },
            {
                "entity_key": "market.summary.legacy_confidence",
                "platform": "sensor",
                "name": "Legacy Confidence",
                "state_source": "market.summary.legacy_confidence",
                "icon": "mdi:archive-clock-outline",
                "availability": {"modes": ["full"], "requires_features": [], "status": "deprecated"},
                "since_version": "2026.03.15",
            },
        ]
    )
    snapshot = deepcopy(build_state_snapshot())
    snapshot["entities"]["market.summary.experimental_score"] = {"state": 0.87, "attributes": {}}
    snapshot["entities"]["portfolio.summary.internal_health"] = {"state": "ok", "attributes": {}}
    snapshot["entities"]["market.summary.legacy_confidence"] = {"state": 0.42, "attributes": {}}

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=catalog),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)

    hidden_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:market.summary.experimental_score",
    )
    disabled_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:portfolio.summary.internal_health",
    )
    deprecated_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:market.summary.legacy_confidence",
    )

    assert hidden_entity_id is not None
    assert disabled_entity_id is not None
    assert deprecated_entity_id is not None
    assert registry.async_get(hidden_entity_id).hidden_by is RegistryEntryHider.INTEGRATION
    assert registry.async_get(disabled_entity_id).disabled_by is RegistryEntryDisabler.INTEGRATION
    assert registry.async_get(deprecated_entity_id).disabled_by is RegistryEntryDisabler.INTEGRATION


async def test_sensor_platform_respects_entity_mode_availability(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        data={CONF_API_URL: "http://localhost:8000"},
    )
    entry.add_to_hass(hass)

    catalog = deepcopy(build_catalog())
    catalog["entities"].append(
        {
            "entity_key": "market.summary.local_only_metric",
            "platform": "sensor",
            "name": "Local Only Metric",
            "state_source": "market.summary.local_only_metric",
            "icon": "mdi:home-switch",
            "availability": {"modes": ["local"], "requires_features": [], "status": "active"},
            "since_version": "2026.03.15",
        }
    )
    snapshot = deepcopy(build_state_snapshot())
    snapshot["entities"]["market.summary.local_only_metric"] = {"state": 12, "attributes": {}}

    with (
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_bootstrap",
            new=AsyncMock(return_value=build_bootstrap()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_catalog",
            new=AsyncMock(return_value=catalog),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_dashboard",
            new=AsyncMock(return_value=build_dashboard()),
        ),
        patch(
            "custom_components.iris.client.IrisApiClient.async_get_state",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(
            "custom_components.iris.IrisWebSocketClient.async_start",
            autospec=True,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)

    assert (
        registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            "iris-main-001:market.summary.local_only_metric",
        )
        is None
    )


async def test_catalog_changed_updates_sensor_registry_metadata_without_reload(hass) -> None:
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

    refreshed_catalog = deepcopy(build_catalog())
    for entity in refreshed_catalog["entities"]:
        if entity.get("entity_key") == "market.summary.hot_assets_count":
            entity["name"] = "Hot Assets Legacy"
            entity["availability"] = {"modes": ["full"], "status": "hidden"}
            break
    entry.runtime_data.client.async_get_catalog = AsyncMock(return_value=refreshed_catalog)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        reconnect_requested = await entry.runtime_data.websocket._async_handle_message(
            {
                "type": "catalog_changed",
                "projection_epoch": "20260315T000000Z-stage3",
                "sequence": 5,
            }
        )
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:market.summary.hot_assets_count",
    )

    assert reconnect_requested is True
    schedule_reload.assert_not_called()
    assert entity_id is not None
    entry_state = registry.async_get(entity_id)
    assert entry_state.hidden_by is RegistryEntryHider.INTEGRATION
    assert entry_state.original_name == "Hot Assets Legacy"


async def test_catalog_refresh_preserves_user_overrides(hass) -> None:
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
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:market.summary.hot_assets_count",
    )
    assert entity_id is not None
    registry.async_update_entity(
        entity_id,
        name="My Hot Assets",
        disabled_by=RegistryEntryDisabler.USER,
    )

    refreshed_catalog = deepcopy(build_catalog())
    for entity in refreshed_catalog["entities"]:
        if entity.get("entity_key") == "market.summary.hot_assets_count":
            entity["name"] = "Hot Assets Backend Renamed"
            entity["icon"] = "mdi:fire-alert"
            break
    entry.runtime_data.client.async_get_catalog = AsyncMock(return_value=refreshed_catalog)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        reconnect_requested = await entry.runtime_data.websocket._async_handle_message(
            {
                "type": "catalog_changed",
                "projection_epoch": "20260315T000000Z-stage3",
                "sequence": 5,
            }
        )
        await hass.async_block_till_done()

    updated = registry.async_get(entity_id)

    assert reconnect_requested is True
    schedule_reload.assert_not_called()
    assert updated.name == "My Hot Assets"
    assert updated.disabled_by is RegistryEntryDisabler.USER
    assert updated.original_name == "Hot Assets Backend Renamed"


async def test_catalog_changed_with_removed_entity_retires_entity_in_place(hass) -> None:
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

    refreshed_catalog = deepcopy(build_catalog())
    for entity in refreshed_catalog["entities"]:
        if entity.get("entity_key") == "market.summary.hot_assets_count":
            entity["availability"] = {"modes": ["full"], "status": "removed"}
            break
    entry.runtime_data.client.async_get_catalog = AsyncMock(return_value=refreshed_catalog)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "iris-main-001:market.summary.hot_assets_count",
    )
    assert entity_id is not None

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        reconnect_requested = await entry.runtime_data.websocket._async_handle_message(
            {
                "type": "catalog_changed",
                "projection_epoch": "20260315T000000Z-stage3",
                "sequence": 5,
            }
        )
        await hass.async_block_till_done()

    assert reconnect_requested is True
    schedule_reload.assert_not_called()
    assert registry.async_get(entity_id) is None
    assert hass.states.get(entity_id) is None
