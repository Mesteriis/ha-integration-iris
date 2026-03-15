from __future__ import annotations

from copy import deepcopy
from typing import Any

CATALOG_MODES = {"full", "local", "ha_addon"}
CATALOG_ENTITY_STATUSES = {"active", "deprecated", "hidden", "removed"}
CATALOG_ENTITY_PLATFORMS = {
    "sensor",
    "binary_sensor",
    "switch",
    "button",
    "select",
    "number",
    "event",
}
CATALOG_COLLECTION_KINDS = {"mapping", "list", "table", "timeline", "summary"}
CATALOG_COLLECTION_TRANSPORTS = {"websocket", "http"}
CATALOG_COMMAND_KINDS = {"action", "flow", "toggle", "selection", "refresh", "admin"}
CATALOG_WIDGET_KINDS = {"summary", "table", "timeline", "status", "actions", "chart_placeholder", "list"}


class IrisCatalogError(ValueError):
    """Raised when the backend catalog payload violates the protocol contract."""


def parse_catalog_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IrisCatalogError("IRIS catalog response must be a JSON object.")

    normalized = deepcopy(payload)
    normalized["catalog_version"] = _required_str(payload, "catalog_version")
    normalized["protocol_version"] = _required_int(payload, "protocol_version")
    normalized["mode"] = _enum_str(payload, "mode", CATALOG_MODES)
    normalized["entities"] = [
        _parse_entity_definition(entity, path=f"entities[{index}]")
        for index, entity in enumerate(_required_list(payload, "entities"))
    ]
    normalized["collections"] = [
        _parse_collection_definition(collection, path=f"collections[{index}]")
        for index, collection in enumerate(_required_list(payload, "collections"))
    ]
    normalized["commands"] = [
        _parse_command_definition(command, path=f"commands[{index}]")
        for index, command in enumerate(_optional_list(payload, "commands"))
    ]
    normalized["views"] = [
        _parse_view_definition(view, path=f"views[{index}]")
        for index, view in enumerate(_optional_list(payload, "views"))
    ]
    return normalized


def parse_dashboard_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IrisCatalogError("IRIS dashboard response must be a JSON object.")

    normalized = deepcopy(payload)
    normalized["version"] = _required_int(payload, "version")
    normalized["slug"] = _required_str(payload, "slug")
    normalized["title"] = _required_str(payload, "title")
    normalized["views"] = [
        _parse_view_definition(view, path=f"views[{index}]")
        for index, view in enumerate(_required_list(payload, "views", path="dashboard"))
    ]
    return normalized


def _parse_entity_definition(payload: Any, *, path: str) -> dict[str, Any]:
    definition = _required_dict(payload, path)
    normalized = deepcopy(definition)
    normalized["entity_key"] = _required_str(definition, "entity_key", path=path)
    normalized["platform"] = _enum_str(definition, "platform", CATALOG_ENTITY_PLATFORMS, path=path)
    normalized["name"] = _required_str(definition, "name", path=path)
    normalized["state_source"] = _required_str(definition, "state_source", path=path)
    normalized["command_key"] = _optional_str(definition, "command_key", path=path)
    normalized["icon"] = _optional_str(definition, "icon", path=path)
    normalized["category"] = _optional_str(definition, "category", path=path)
    normalized["default_enabled"] = _optional_bool(definition, "default_enabled", default=True, path=path)
    normalized["availability"] = _parse_availability(definition.get("availability"), path=f"{path}.availability")
    normalized["since_version"] = _required_str(definition, "since_version", path=path)
    normalized["deprecated_since"] = _optional_str(definition, "deprecated_since", path=path)
    normalized["replacement"] = _optional_str(definition, "replacement", path=path)
    normalized["entity_registry_enabled_default"] = _optional_bool(
        definition,
        "entity_registry_enabled_default",
        default=True,
        path=path,
    )
    normalized["device_class"] = _optional_str(definition, "device_class", path=path)
    normalized["unit_of_measurement"] = _optional_str(definition, "unit_of_measurement", path=path)
    normalized["translation_key"] = _optional_str(definition, "translation_key", path=path)
    return normalized


def _parse_collection_definition(payload: Any, *, path: str) -> dict[str, Any]:
    definition = _required_dict(payload, path)
    normalized = deepcopy(definition)
    normalized["collection_key"] = _required_str(definition, "collection_key", path=path)
    normalized["kind"] = _enum_str(definition, "kind", CATALOG_COLLECTION_KINDS, path=path)
    normalized["transport"] = _enum_str(definition, "transport", CATALOG_COLLECTION_TRANSPORTS, path=path)
    normalized["dashboard_only"] = _optional_bool(definition, "dashboard_only", default=False, path=path)
    normalized["since_version"] = _required_str(definition, "since_version", path=path)
    return normalized


def _parse_command_definition(payload: Any, *, path: str) -> dict[str, Any]:
    definition = _required_dict(payload, path)
    normalized = deepcopy(definition)
    normalized["command_key"] = _required_str(definition, "command_key", path=path)
    normalized["name"] = _required_str(definition, "name", path=path)
    normalized["kind"] = _enum_str(definition, "kind", CATALOG_COMMAND_KINDS, path=path)
    normalized["input_schema"] = _optional_dict(definition, "input_schema", path=path)
    normalized["returns"] = _optional_str(definition, "returns", path=path)
    availability = definition.get("availability")
    normalized["availability"] = (
        _parse_availability(availability, path=f"{path}.availability")
        if availability is not None
        else None
    )
    normalized["since_version"] = _required_str(definition, "since_version", path=path)
    normalized["deprecated_since"] = _optional_str(definition, "deprecated_since", path=path)
    normalized["replacement"] = _optional_str(definition, "replacement", path=path)
    return normalized


def _parse_view_definition(payload: Any, *, path: str) -> dict[str, Any]:
    view = _required_dict(payload, path)
    normalized = deepcopy(view)
    normalized["view_key"] = _required_str(view, "view_key", path=path)
    normalized["title"] = _required_str(view, "title", path=path)
    sections = _required_list(view, "sections", path=path)
    normalized["sections"] = [
        _parse_section_definition(section, path=f"{path}.sections[{index}]")
        for index, section in enumerate(sections)
    ]
    return normalized


def _parse_section_definition(payload: Any, *, path: str) -> dict[str, Any]:
    section = _required_dict(payload, path)
    normalized = deepcopy(section)
    normalized["section_key"] = _required_str(section, "section_key", path=path)
    normalized["title"] = _required_str(section, "title", path=path)
    widgets = _required_list(section, "widgets", path=path)
    normalized["widgets"] = [
        _parse_widget_definition(widget, path=f"{path}.widgets[{index}]")
        for index, widget in enumerate(widgets)
    ]
    return normalized


def _parse_widget_definition(payload: Any, *, path: str) -> dict[str, Any]:
    widget = _required_dict(payload, path)
    normalized = deepcopy(widget)
    normalized["widget_key"] = _required_str(widget, "widget_key", path=path)
    normalized["title"] = _required_str(widget, "title", path=path)
    normalized["kind"] = _enum_str(widget, "kind", CATALOG_WIDGET_KINDS, path=path)
    normalized["source"] = _required_str(widget, "source", path=path)
    normalized["entity_keys"] = _list_of_strings(widget.get("entity_keys", []), path=f"{path}.entity_keys")
    normalized["command_keys"] = _list_of_strings(widget.get("command_keys", []), path=f"{path}.command_keys")
    config = widget.get("config", {})
    if not isinstance(config, dict):
        raise IrisCatalogError(f"{path}.config must be an object.")
    normalized["config"] = deepcopy(config)
    return normalized


def _parse_availability(payload: Any, *, path: str) -> dict[str, Any]:
    availability = _required_dict(payload, path)
    normalized = deepcopy(availability)
    normalized["modes"] = _list_of_enum_strings(availability.get("modes"), allowed=CATALOG_MODES, path=f"{path}.modes")
    normalized["requires_features"] = _list_of_strings(
        availability.get("requires_features", []),
        path=f"{path}.requires_features",
    )
    normalized["status"] = _enum_value(availability.get("status", "active"), CATALOG_ENTITY_STATUSES, path=f"{path}.status")
    return normalized


def _required_dict(payload: Any, path: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IrisCatalogError(f"{path} must be an object.")
    return payload


def _required_list(payload: dict[str, Any], field: str, *, path: str = "catalog") -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise IrisCatalogError(f"{path}.{field} must be a list.")
    return value


def _optional_list(payload: dict[str, Any], field: str) -> list[Any]:
    value = payload.get(field, [])
    if not isinstance(value, list):
        raise IrisCatalogError(f"catalog.{field} must be a list.")
    return value


def _required_str(payload: dict[str, Any], field: str, *, path: str = "catalog") -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise IrisCatalogError(f"{path}.{field} must be a non-empty string.")
    return value


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int):
        raise IrisCatalogError(f"catalog.{field} must be an integer.")
    return value


def _optional_str(payload: dict[str, Any], field: str, *, path: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise IrisCatalogError(f"{path}.{field} must be a string or null.")
    return value


def _optional_bool(payload: dict[str, Any], field: str, *, default: bool, path: str) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise IrisCatalogError(f"{path}.{field} must be a boolean.")
    return value


def _optional_dict(payload: dict[str, Any], field: str, *, path: str) -> dict[str, Any] | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise IrisCatalogError(f"{path}.{field} must be an object or null.")
    return deepcopy(value)


def _enum_str(payload: dict[str, Any], field: str, allowed: set[str], *, path: str = "catalog") -> str:
    value = _required_str(payload, field, path=path)
    return _enum_value(value, allowed, path=f"{path}.{field}")


def _enum_value(value: Any, allowed: set[str], *, path: str) -> str:
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise IrisCatalogError(f"{path} must be one of: {allowed_values}.")
    return str(value)


def _list_of_strings(payload: Any, *, path: str) -> list[str]:
    if not isinstance(payload, list):
        raise IrisCatalogError(f"{path} must be a list.")
    values: list[str] = []
    for index, item in enumerate(payload):
        if not isinstance(item, str):
            raise IrisCatalogError(f"{path}[{index}] must be a string.")
        values.append(item)
    return values


def _list_of_enum_strings(payload: Any, *, allowed: set[str], path: str) -> list[str]:
    values = _list_of_strings(payload, path=path)
    return [_enum_value(value, allowed, path=f"{path}[{index}]") for index, value in enumerate(values)]
