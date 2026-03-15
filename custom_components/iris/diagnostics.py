from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import IrisConfigEntry
from .const import CONF_API_URL


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: IrisConfigEntry,
) -> dict[str, Any]:
    del hass
    runtime = entry.runtime_data
    return {
        "api_url": entry.data.get(CONF_API_URL),
        "bootstrap": runtime.store.summary(),
        "capabilities": asdict(runtime.store.bootstrap.capabilities) if runtime.store.bootstrap else None,
        "tracked_entities": runtime.store.tracked_entity_keys(),
        "tracked_collections": runtime.store.tracked_collection_keys(),
        "dashboard": runtime.dashboard.summary(),
        "catalog_loaded": bool(runtime.store.catalog),
        "operations_count": len(runtime.store.operations),
    }
