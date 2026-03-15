from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client import IrisApiClient, IrisAuthenticationError, IrisConnectionError, IrisProtocolError
from .command_bus import IrisCommandBus
from .const import CONF_API_URL, DOMAIN
from .dashboard import IrisDashboardRuntime
from .entity_registry_sync import IrisEntityRegistrySync
from .services import async_register_services
from .store import IrisRuntimeStore
from .versioning import IrisCompatibilityError, validate_bootstrap_compatibility
from .websocket_client import IrisWebSocketClient

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.EVENT,
]


@dataclass(slots=True)
class IrisRuntimeData:
    client: IrisApiClient
    store: IrisRuntimeStore
    dashboard: IrisDashboardRuntime
    entity_sync: IrisEntityRegistrySync
    websocket: IrisWebSocketClient
    command_bus: IrisCommandBus


try:
    IrisConfigEntry = ConfigEntry[IrisRuntimeData]
except TypeError:  # pragma: no cover - Home Assistant < generic ConfigEntry support
    IrisConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    del config
    hass.data.setdefault(DOMAIN, {})
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IrisConfigEntry) -> bool:
    client = IrisApiClient(
        hass,
        entry.data[CONF_API_URL],
        auth_token=entry.data.get(CONF_TOKEN),
    )
    store = IrisRuntimeStore()
    try:
        bootstrap = await client.async_get_bootstrap()
        validate_bootstrap_compatibility(bootstrap)
        catalog = await client.async_get_catalog(bootstrap.catalog_url)
        dashboard = await client.async_get_dashboard(bootstrap.dashboard_url)
        state = await client.async_get_state(bootstrap.state_url)
    except IrisAuthenticationError as exc:
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except (IrisConnectionError, IrisProtocolError) as exc:
        raise ConfigEntryNotReady(str(exc)) from exc
    except IrisCompatibilityError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    store.apply_bootstrap(bootstrap)
    store.apply_catalog(catalog)
    store.apply_dashboard(dashboard)
    store.apply_state_snapshot(state)

    entity_sync = IrisEntityRegistrySync(hass, entry)
    dashboard_runtime = IrisDashboardRuntime(hass, entry.entry_id, store)
    websocket = IrisWebSocketClient(
        hass,
        client,
        store,
        on_catalog_refreshed=lambda: _handle_catalog_refresh(hass, entry.entry_id, entity_sync),
        on_dashboard_refreshed=dashboard_runtime.handle_dashboard_refresh,
    )
    command_bus = IrisCommandBus(websocket, store)

    entry.runtime_data = IrisRuntimeData(
        client=client,
        store=store,
        dashboard=dashboard_runtime,
        entity_sync=entity_sync,
        websocket=websocket,
        command_bus=command_bus,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await dashboard_runtime.async_setup()
    websocket.async_start()
    entry.async_on_unload(websocket.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IrisConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _handle_catalog_refresh(hass: HomeAssistant, entry_id: str, entity_sync: IrisEntityRegistrySync) -> None:
    if entity_sync.handle_catalog_refresh():
        hass.config_entries.async_schedule_reload(entry_id)
