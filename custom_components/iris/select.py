from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IrisConfigEntry
from .entity_factory import (
    entity_category,
    entity_command_key,
    entity_enabled_default,
    entity_icon,
    entity_name,
    entity_state_source,
    entity_translation_key,
    entity_unique_id,
    entity_visible_default,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IrisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    del hass
    entry.async_on_unload(
        entry.runtime_data.entity_sync.register_platform(
            platform="select",
            add_entities=async_add_entities,
            factory=lambda definition: IrisCatalogSelectEntity(entry, definition),
        )
    )


class IrisCatalogSelectEntity(SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: IrisConfigEntry, definition: dict[str, Any]) -> None:
        self._command_bus = entry.runtime_data.command_bus
        self._store = entry.runtime_data.store
        self.entity_key = str(definition["entity_key"])
        self._attr_unique_id = entity_unique_id(entry, self.entity_key)
        self.async_update_definition(definition)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._store.add_listener(self._handle_store_update))

    @property
    def available(self) -> bool:
        return bool(self._store.entity_state(self._state_source))

    @property
    def current_option(self) -> str | None:
        state = self._store.entity_state(self._state_source).get("state")
        return state if isinstance(state, str) else None

    @property
    def options(self) -> list[str]:
        attributes = self._store.entity_state(self._state_source).get("attributes")
        if isinstance(attributes, dict):
            options = attributes.get("options")
            if isinstance(options, list) and all(isinstance(item, str) for item in options):
                return options
        definition_options = self._definition.get("options")
        if isinstance(definition_options, list) and all(isinstance(item, str) for item in definition_options):
            return definition_options
        return []

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = self._store.entity_state(self._state_source).get("attributes")
        if isinstance(attributes, dict):
            return attributes
        return {}

    async def async_select_option(self, option: str) -> None:
        if self._command_key is None:
            raise HomeAssistantError(f"IRIS select entity '{self.entity_key}' is missing command_key.")
        await self._command_bus.async_execute(command=self._command_key, payload={"value": option})

    @callback
    def async_update_definition(self, definition: dict[str, Any]) -> None:
        self._definition = definition
        self._command_key = entity_command_key(definition)
        self._state_source = entity_state_source(definition)
        self._attr_name = entity_name(definition)
        self._attr_icon = entity_icon(definition)
        self._attr_entity_category = entity_category(definition.get("category"))
        self._attr_entity_registry_enabled_default = entity_enabled_default(definition)
        self._attr_entity_registry_visible_default = entity_visible_default(definition)
        self._attr_translation_key = entity_translation_key(definition)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def _handle_store_update(self) -> None:
        self.async_write_ha_state()
