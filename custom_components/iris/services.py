from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_INSTANCE_ID,
    DOMAIN,
    SERVICE_EXECUTE_COMMAND,
    SERVICE_REFRESH_MARKET,
    SERVICE_SYNC_PORTFOLIO,
)

_EXECUTE_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("command"): cv.string,
        vol.Optional("payload", default={}): dict,
        vol.Optional(CONF_INSTANCE_ID): cv.string,
    }
)
_FIXED_COMMAND_SCHEMA = vol.Schema({vol.Optional(CONF_INSTANCE_ID): cv.string})


async def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_EXECUTE_COMMAND):
        return

    async def _handle_execute(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_runtime_entry(hass, instance_id=call.data.get(CONF_INSTANCE_ID))
        payload = call.data.get("payload", {})
        if not isinstance(payload, dict):
            raise HomeAssistantError("IRIS command payload must be an object.")
        return await entry.runtime_data.command_bus.async_execute(
            command=str(call.data["command"]),
            payload=payload,
        )

    async def _handle_sync_portfolio(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_runtime_entry(hass, instance_id=call.data.get(CONF_INSTANCE_ID))
        return await entry.runtime_data.command_bus.async_execute(command="portfolio.sync", payload={})

    async def _handle_refresh_market(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_runtime_entry(hass, instance_id=call.data.get(CONF_INSTANCE_ID))
        return await entry.runtime_data.command_bus.async_execute(command="market.refresh", payload={})

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_COMMAND,
        _handle_execute,
        schema=_EXECUTE_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_PORTFOLIO,
        _handle_sync_portfolio,
        schema=_FIXED_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_MARKET,
        _handle_refresh_market,
        schema=_FIXED_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _resolve_runtime_entry(hass: HomeAssistant, *, instance_id: str | None) -> ConfigEntry:
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if instance_id:
        for entry in entries:
            bootstrap = getattr(entry.runtime_data.store, "bootstrap", None)
            if bootstrap is not None and bootstrap.instance.instance_id == instance_id:
                return entry
        raise HomeAssistantError(f"IRIS instance '{instance_id}' is not loaded.")
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise HomeAssistantError("No loaded IRIS instance is available for service execution.")
    raise HomeAssistantError("Multiple IRIS instances are loaded; provide instance_id.")
