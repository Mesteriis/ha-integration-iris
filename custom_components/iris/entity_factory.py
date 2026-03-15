from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.entity import EntityCategory

if TYPE_CHECKING:
    from . import IrisConfigEntry

ENTITY_STATUSES = {"active", "deprecated", "hidden", "removed"}


def catalog_entity_definitions(entry: IrisConfigEntry, *, platform: str) -> list[dict[str, Any]]:
    current_mode = entry.runtime_data.store.bootstrap.instance.mode if entry.runtime_data.store.bootstrap else None
    entities = entry.runtime_data.store.catalog.get("entities", [])
    if not isinstance(entities, list):
        return []
    materialized: list[dict[str, Any]] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        if item.get("platform") != platform:
            continue
        if not isinstance(item.get("entity_key"), str):
            continue
        if current_mode is not None and not entity_mode_supported(item, current_mode=current_mode):
            continue
        if entity_status(item) == "removed":
            continue
        materialized.append(item)
    return materialized


def entity_unique_id(entry: IrisConfigEntry, entity_key: str) -> str:
    store = entry.runtime_data.store
    instance_id = store.bootstrap.instance.instance_id if store.bootstrap else entry.entry_id
    return f"{instance_id}:{entity_key}"


def entity_state_source(definition: dict[str, Any]) -> str:
    return str(definition.get("state_source") or definition["entity_key"])


def entity_command_key(definition: dict[str, Any]) -> str | None:
    value = definition.get("command_key")
    if isinstance(value, str) and value:
        return value
    entity_key = definition.get("entity_key")
    if isinstance(entity_key, str) and entity_key:
        return entity_key
    return None


def entity_name(definition: dict[str, Any]) -> str:
    return str(definition.get("name") or definition["entity_key"])


def entity_icon(definition: dict[str, Any]) -> str | None:
    return definition["icon"] if isinstance(definition.get("icon"), str) else None


def entity_unit(definition: dict[str, Any]) -> str | None:
    value = definition.get("unit_of_measurement")
    return value if isinstance(value, str) else None


def entity_device_class(definition: dict[str, Any]) -> str | None:
    value = definition.get("device_class")
    return value if isinstance(value, str) else None


def entity_enabled_default(definition: dict[str, Any]) -> bool:
    value = definition.get("entity_registry_enabled_default")
    if isinstance(value, bool):
        return value
    value = definition.get("default_enabled")
    if isinstance(value, bool):
        return value
    return entity_status(definition) != "deprecated"


def entity_visible_default(definition: dict[str, Any]) -> bool:
    return entity_status(definition) != "hidden"


def entity_status(definition: dict[str, Any]) -> str:
    availability = definition.get("availability")
    if isinstance(availability, dict):
        raw_status = availability.get("status")
        if raw_status in ENTITY_STATUSES:
            return str(raw_status)
    raw_status = definition.get("status")
    if raw_status in ENTITY_STATUSES:
        return str(raw_status)
    return "active"


def entity_translation_key(definition: dict[str, Any]) -> str | None:
    value = definition.get("translation_key")
    return value if isinstance(value, str) else None


def entity_mode_supported(definition: dict[str, Any], *, current_mode: str) -> bool:
    availability = definition.get("availability")
    if not isinstance(availability, dict):
        return True
    modes = availability.get("modes")
    if not isinstance(modes, list) or not modes:
        return True
    return current_mode in modes


def entity_category(raw: Any) -> EntityCategory | None:
    if raw == "diagnostic":
        return EntityCategory.DIAGNOSTIC
    if raw == "config":
        return EntityCategory.CONFIG
    return None
