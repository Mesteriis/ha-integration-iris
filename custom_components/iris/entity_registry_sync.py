from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntryHider

from .entity_factory import (
    catalog_entity_definitions,
    entity_category,
    entity_device_class,
    entity_icon,
    entity_name,
    entity_translation_key,
    entity_unique_id,
    entity_unit,
    entity_visible_default,
)

if TYPE_CHECKING:
    from . import IrisConfigEntry


class IrisCatalogManagedEntity(Protocol):
    entity_id: str | None
    entity_key: str
    platform: Any

    def async_update_definition(self, definition: dict[str, Any]) -> None:
        """Apply the latest backend entity definition."""


EntityFactory = Callable[[dict[str, Any]], IrisCatalogManagedEntity]


@dataclass(slots=True)
class PlatformRegistration:
    add_entities: AddEntitiesCallback
    factory: EntityFactory
    entities: dict[str, IrisCatalogManagedEntity] = field(default_factory=dict)
    known_entity_keys: set[str] = field(default_factory=set)


class IrisEntityRegistrySync:
    def __init__(self, hass: HomeAssistant, entry: IrisConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._platforms: dict[str, PlatformRegistration] = {}

    @callback
    def register_platform(
        self,
        *,
        platform: str,
        add_entities: AddEntitiesCallback,
        factory: EntityFactory,
    ) -> Callable[[], None]:
        registration = PlatformRegistration(add_entities=add_entities, factory=factory)
        self._platforms[platform] = registration
        self._sync_platform(platform)

        def _remove() -> None:
            self._platforms.pop(platform, None)

        return _remove

    @callback
    def handle_catalog_refresh(self) -> bool:
        reload_required = False
        for platform in list(self._platforms):
            reload_required |= self._sync_platform(platform)
        return reload_required

    @callback
    def _sync_platform(self, platform: str) -> bool:
        registration = self._platforms.get(platform)
        if registration is None:
            return False

        definitions = {
            str(definition["entity_key"]): definition
            for definition in catalog_entity_definitions(self._entry, platform=platform)
        }
        new_entities: list[IrisCatalogManagedEntity] = []
        registry = er.async_get(self._hass)
        current_keys = set(definitions)

        for entity_key, definition in definitions.items():
            existing = registration.entities.get(entity_key)
            if existing is None:
                entity = registration.factory(definition)
                registration.entities[entity_key] = entity
                new_entities.append(entity)
                continue

            existing.async_update_definition(definition)
            if existing.entity_id is not None:
                registry.async_update_entity(
                    existing.entity_id,
                    entity_category=entity_category(definition.get("category")),
                    hidden_by=_registry_hidden_by(definition),
                    original_device_class=entity_device_class(definition),
                    original_icon=entity_icon(definition),
                    original_name=entity_name(definition),
                    translation_key=entity_translation_key(definition),
                    unit_of_measurement=entity_unit(definition),
                )

        if new_entities:
            registration.add_entities(new_entities)

        removed_keys = self._removed_entity_keys(
            platform=platform,
            current_keys=current_keys,
            registry=registry,
            known_keys=registration.known_entity_keys,
        )
        registration.known_entity_keys = current_keys
        if removed_keys:
            self._schedule_entity_retirement(
                platform=platform,
                removed_keys=removed_keys,
                registration=registration,
                registry=registry,
            )
        return False

    def _removed_entity_keys(
        self,
        *,
        platform: str,
        current_keys: set[str],
        registry: er.EntityRegistry,
        known_keys: set[str],
    ) -> set[str]:
        removed_keys = set(known_keys) - current_keys
        instance_id = self._entry.runtime_data.store.bootstrap.instance.instance_id if self._entry.runtime_data.store.bootstrap else None
        if instance_id is None:
            return removed_keys
        prefix = f"{instance_id}:"
        for entry in registry.entities.values():
            if entry.config_entry_id != self._entry.entry_id or entry.domain != platform:
                continue
            if not entry.unique_id.startswith(prefix):
                continue
            entity_key = entry.unique_id.removeprefix(prefix)
            if entity_key not in current_keys:
                removed_keys.add(entity_key)
        return removed_keys

    def _schedule_entity_retirement(
        self,
        *,
        platform: str,
        removed_keys: set[str],
        registration: PlatformRegistration,
        registry: er.EntityRegistry,
    ) -> None:
        for entity_key in removed_keys:
            loaded = registration.entities.pop(entity_key, None)
            unique_id = entity_unique_id(self._entry, entity_key)
            entity_id = registry.async_get_entity_id(platform, self._entry.domain, unique_id)
            self._hass.async_create_task(
                self._async_retire_entity(loaded_entity=loaded, entity_id=entity_id, registry=registry)
            )

    async def _async_retire_entity(
        self,
        *,
        loaded_entity: IrisCatalogManagedEntity | None,
        entity_id: str | None,
        registry: er.EntityRegistry,
    ) -> None:
        resolved_entity_id = entity_id
        if resolved_entity_id is None and loaded_entity is not None:
            resolved_entity_id = loaded_entity.entity_id
        if resolved_entity_id is not None and registry.async_get(resolved_entity_id) is not None:
            registry.async_remove(resolved_entity_id)
        if (
            loaded_entity is not None
            and loaded_entity.entity_id is not None
            and loaded_entity.platform is not None
            and loaded_entity.entity_id in loaded_entity.platform.entities
        ):
            await loaded_entity.platform.async_remove_entity(loaded_entity.entity_id)


def _registry_hidden_by(definition: dict[str, Any]) -> RegistryEntryHider | None:
    if not entity_visible_default(definition):
        return RegistryEntryHider.INTEGRATION
    return None
