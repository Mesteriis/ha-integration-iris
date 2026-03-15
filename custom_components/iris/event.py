from __future__ import annotations

import json
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IrisConfigEntry
from .entity_factory import (
    entity_category,
    entity_device_class,
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
            platform="event",
            add_entities=async_add_entities,
            factory=lambda definition: IrisCatalogEventEntity(entry, definition),
        )
    )


class IrisCatalogEventEntity(EventEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: IrisConfigEntry, definition: dict[str, Any]) -> None:
        self._store = entry.runtime_data.store
        self.entity_key = str(definition["entity_key"])
        self._attr_unique_id = entity_unique_id(entry, self.entity_key)
        self._last_marker: str | None = None
        self.async_update_definition(definition)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._store.add_listener(self._handle_store_update))
        self._handle_store_update()

    @property
    def available(self) -> bool:
        return bool(self._store.entity_state(self._state_source))

    @callback
    def async_update_definition(self, definition: dict[str, Any]) -> None:
        self._definition = definition
        self._state_source = entity_state_source(definition)
        self._attr_name = entity_name(definition)
        self._attr_icon = entity_icon(definition)
        self._attr_entity_category = entity_category(definition.get("category"))
        self._attr_device_class = entity_device_class(definition)
        self._attr_entity_registry_enabled_default = entity_enabled_default(definition)
        self._attr_entity_registry_visible_default = entity_visible_default(definition)
        self._attr_translation_key = entity_translation_key(definition)
        self._attr_event_types = _definition_event_types(definition)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def _handle_store_update(self) -> None:
        state = self._store.entity_state(self._state_source)
        if not state:
            return
        attributes = state.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        marker = json.dumps(
            {"state": state.get("state"), "attributes": attributes},
            sort_keys=True,
            default=str,
        )
        if marker == self._last_marker:
            return
        self._last_marker = marker
        event_type = attributes.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raw_state = state.get("state")
            event_type = raw_state if isinstance(raw_state, str) and raw_state else "updated"
        if event_type not in self._attr_event_types:
            self._attr_event_types = [*self._attr_event_types, event_type]
        event_attributes = {
            key: value
            for key, value in attributes.items()
            if key not in {"event_type", "event_types"}
        }
        self._trigger_event(event_type, event_attributes or None)
        self.async_write_ha_state()


def _definition_event_types(definition: dict[str, Any]) -> list[str]:
    raw = definition.get("event_types")
    if isinstance(raw, list) and all(isinstance(item, str) and item for item in raw):
        return list(raw)
    return ["updated"]
