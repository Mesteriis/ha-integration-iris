from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.iris.const import (
    CONF_API_URL,
    DOMAIN,
    SERVICE_EXECUTE_COMMAND,
    SERVICE_SYNC_PORTFOLIO,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


async def test_execute_command_service_returns_command_ack_response(hass) -> None:
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

    entry.runtime_data.command_bus.async_execute = AsyncMock(
        return_value={
            "accepted": True,
            "command": "portfolio.sync",
            "operation_id": "op_123",
            "instance_id": "iris-main-001",
        }
    )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXECUTE_COMMAND,
        {"command": "portfolio.sync"},
        blocking=True,
        return_response=True,
    )
    sync_response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SYNC_PORTFOLIO,
        {},
        blocking=True,
        return_response=True,
    )

    assert response["operation_id"] == "op_123"
    assert response["instance_id"] == "iris-main-001"
    assert sync_response["command"] == "portfolio.sync"
    entry.runtime_data.command_bus.async_execute.assert_any_await(command="portfolio.sync", payload={})
    assert entry.runtime_data.command_bus.async_execute.await_count == 2


async def test_catalog_button_entity_executes_bound_command(hass) -> None:
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
    button_entity_id = registry.async_get_entity_id(
        "button",
        DOMAIN,
        "iris-main-001:actions.portfolio_sync",
    )
    assert button_entity_id is not None

    entry.runtime_data.command_bus.async_execute = AsyncMock(
        return_value={"accepted": True, "command": "portfolio.sync", "operation_id": "op_123"}
    )

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": button_entity_id},
        blocking=True,
    )

    entry.runtime_data.command_bus.async_execute.assert_awaited_once_with(
        command="portfolio.sync",
        payload={},
    )


async def test_catalog_switch_and_select_entities_execute_bound_commands(hass) -> None:
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
    switch_entity_id = registry.async_get_entity_id(
        "switch",
        DOMAIN,
        "iris-main-001:settings.notifications_enabled",
    )
    select_entity_id = registry.async_get_entity_id(
        "select",
        DOMAIN,
        "iris-main-001:settings.default_timeframe",
    )
    assert switch_entity_id is not None
    assert select_entity_id is not None

    entry.runtime_data.command_bus.async_execute = AsyncMock(
        return_value={"accepted": True, "operation_id": "op_456"}
    )

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": switch_entity_id},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_entity_id, "option": "4h"},
        blocking=True,
    )

    entry.runtime_data.command_bus.async_execute.assert_any_await(
        command="settings.notifications_enabled.set",
        payload={"value": False},
    )
    entry.runtime_data.command_bus.async_execute.assert_any_await(
        command="settings.default_timeframe.set",
        payload={"value": "4h"},
    )
