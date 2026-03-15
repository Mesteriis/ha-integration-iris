from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace.const import (
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    DEFAULT_ICON,
    MODE_STORAGE,
    ConfigNotFound,
)
from homeassistant.components.lovelace.const import (
    DOMAIN as LOVELACE_DOMAIN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify

from .const import DOMAIN, EVENT_DASHBOARD_UPDATED
from .store import IrisRuntimeStore

_LOGGER = logging.getLogger(__name__)
_DASHBOARD_ICON = "mdi:view-dashboard-outline"


class IrisDashboardRuntime:
    def __init__(self, hass: HomeAssistant, entry_id: str, store: IrisRuntimeStore) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store = store
        self._last_published_fingerprint: tuple[Any, ...] | None = None
        self._last_render_hash: str | None = None
        self._summary = _dashboard_summary({})

    async def async_setup(self) -> None:
        await self._async_publish_and_sync(reason="initial_load", force=True)

    @callback
    def handle_dashboard_refresh(self) -> None:
        self._hass.async_create_task(self._async_publish_and_sync(reason="dashboard_changed"))

    def summary(self) -> dict[str, Any]:
        return deepcopy(self._summary)

    async def _async_publish_and_sync(self, *, reason: str, force: bool = False) -> None:
        summary = _dashboard_summary(self._store.dashboard)
        if summary["loaded"] and self._dashboard_capability_enabled:
            try:
                sync_result = await self._async_sync_lovelace_dashboard()
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                _LOGGER.warning("Failed to synchronize IRIS Lovelace dashboard: %s", exc)
                summary["lovelace_synced"] = False
                summary["lovelace_error"] = str(exc)
                summary["lovelace_render_hash"] = self._last_render_hash
            else:
                summary.update(sync_result)
                summary["lovelace_synced"] = True
                summary["lovelace_error"] = None
                self._last_render_hash = sync_result["lovelace_render_hash"]
        elif summary["loaded"]:
            summary["lovelace_synced"] = False
            summary["lovelace_error"] = "dashboard_capability_disabled"

        self._summary = summary
        if not summary["loaded"]:
            return

        fingerprint = (
            summary["schema_hash"],
            summary.get("lovelace_render_hash"),
            summary.get("lovelace_dashboard_url_path"),
            summary.get("lovelace_synced"),
            summary.get("lovelace_error"),
        )
        if not force and fingerprint == self._last_published_fingerprint:
            return

        self._last_published_fingerprint = fingerprint
        self._hass.bus.async_fire(
            EVENT_DASHBOARD_UPDATED,
            {
                "entry_id": self._entry_id,
                "reason": reason,
                **summary,
            },
        )

    @property
    def _dashboard_capability_enabled(self) -> bool:
        bootstrap = self._store.bootstrap
        return bool(bootstrap and bootstrap.capabilities.dashboard)

    async def _async_sync_lovelace_dashboard(self) -> dict[str, Any]:
        if not await _async_ensure_lovelace(self._hass):
            raise RuntimeError("Unable to initialize Home Assistant Lovelace support.")

        metadata = await _async_upsert_dashboard_metadata(
            self._hass,
            url_path=self._dashboard_url_path,
            title=self._dashboard_title,
            icon=_DASHBOARD_ICON,
        )
        config = self._render_lovelace_config()
        render_hash = _dashboard_hash(config)
        await _async_save_dashboard_config(
            self._hass,
            metadata=metadata,
            config=config,
        )
        return {
            "lovelace_dashboard_url_path": self._dashboard_url_path,
            "lovelace_render_hash": render_hash,
        }

    @property
    def _dashboard_slug(self) -> str:
        raw_slug = self._store.dashboard.get("slug")
        if isinstance(raw_slug, str) and raw_slug:
            return raw_slug
        return "iris"

    @property
    def _dashboard_title(self) -> str:
        raw_title = self._store.dashboard.get("title")
        if isinstance(raw_title, str) and raw_title:
            return raw_title
        return "IRIS"

    @property
    def _dashboard_url_path(self) -> str:
        bootstrap = self._store.bootstrap
        instance_id = bootstrap.instance.instance_id if bootstrap else self._entry_id
        return f"lovelace-{_url_slug(self._dashboard_slug)}-{_url_slug(instance_id)}"

    def _render_lovelace_config(self) -> dict[str, Any]:
        views_payload = self._store.dashboard.get("views", [])
        views: list[dict[str, Any]] = []
        for view in views_payload:
            if not isinstance(view, dict):
                continue
            cards = self._render_view_cards(view)
            if not cards:
                cards = [_markdown_card(title=view.get("title"), content="_No widgets configured yet._")]
            views.append(
                {
                    "title": view["title"],
                    "path": _url_slug(str(view["view_key"])),
                    "cards": cards,
                }
            )
        return {
            "title": self._dashboard_title,
            "views": views,
        }

    def _render_view_cards(self, view: dict[str, Any]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for section in view.get("sections", []):
            if not isinstance(section, dict):
                continue
            section_cards: list[dict[str, Any]] = [
                _markdown_card(title=None, content=f"## {section['title']}")
            ]
            for widget in section.get("widgets", []):
                if not isinstance(widget, dict):
                    continue
                section_cards.append(self._render_widget_card(widget))
            cards.append({"type": "vertical-stack", "cards": section_cards})
        return cards

    def _render_widget_card(self, widget: dict[str, Any]) -> dict[str, Any]:
        kind = str(widget.get("kind") or "")
        if kind in {"summary", "status"}:
            return self._render_entities_widget(widget)
        if kind == "actions":
            return self._render_actions_widget(widget)
        return self._render_collection_widget(widget)

    def _render_entities_widget(self, widget: dict[str, Any]) -> dict[str, Any]:
        entity_ids = self._resolve_entity_ids(widget.get("entity_keys", []))
        if not entity_ids:
            return _markdown_card(
                title=str(widget.get("title") or "Widget"),
                content=f"_No mapped entities found for `{widget.get('source')}`._",
            )
        return {
            "type": "entities",
            "title": str(widget.get("title") or "Widget"),
            "show_header_toggle": False,
            "entities": entity_ids,
        }

    def _render_actions_widget(self, widget: dict[str, Any]) -> dict[str, Any]:
        command_keys = widget.get("command_keys", [])
        if not isinstance(command_keys, list) or not command_keys:
            return _markdown_card(
                title=str(widget.get("title") or "Actions"),
                content="_No commands are bound to this actions widget._",
            )

        action_cards: list[dict[str, Any]] = []
        for command_key in command_keys:
            if not isinstance(command_key, str):
                continue
            entity_id = self._resolve_command_entity_id(command_key)
            if entity_id is not None:
                action_cards.append({"type": "button", "entity": entity_id, "name": self._command_name(command_key)})
                continue
            service_data: dict[str, Any] = {"command": command_key}
            bootstrap = self._store.bootstrap
            if bootstrap is not None:
                service_data["instance_id"] = bootstrap.instance.instance_id
            action_cards.append(
                {
                    "type": "button",
                    "name": self._command_name(command_key),
                    "icon": "mdi:play-circle-outline",
                    "tap_action": {
                        "action": "call-service",
                        "service": f"{DOMAIN}.execute_command",
                        "service_data": service_data,
                    },
                }
            )

        return {
            "type": "vertical-stack",
            "cards": [
                _markdown_card(title=None, content=f"### {widget.get('title') or 'Actions'}"),
                {
                    "type": "grid",
                    "columns": 2,
                    "square": False,
                    "cards": action_cards,
                },
            ],
        }

    def _render_collection_widget(self, widget: dict[str, Any]) -> dict[str, Any]:
        source = str(widget.get("source") or "")
        content = _format_collection_widget(
            title=str(widget.get("title") or "Widget"),
            kind=str(widget.get("kind") or ""),
            source=source,
            data=self._store.collections.get(source),
        )
        return _markdown_card(title=str(widget.get("title") or "Widget"), content=content)

    def _resolve_entity_ids(self, entity_keys: Any) -> list[str]:
        if not isinstance(entity_keys, list):
            return []
        catalog_definitions = self._catalog_entity_definitions
        registry = er.async_get(self._hass)
        resolved: list[str] = []
        for entity_key in entity_keys:
            if not isinstance(entity_key, str):
                continue
            definition = catalog_definitions.get(entity_key)
            if definition is None:
                continue
            entity_id = registry.async_get_entity_id(
                str(definition["platform"]),
                DOMAIN,
                self._entity_unique_id(entity_key),
            )
            if entity_id is not None:
                resolved.append(entity_id)
        return resolved

    def _resolve_command_entity_id(self, command_key: str) -> str | None:
        registry = er.async_get(self._hass)
        for definition in self._catalog_entity_definitions.values():
            if definition.get("command_key") != command_key:
                continue
            entity_key = str(definition["entity_key"])
            entity_id = registry.async_get_entity_id(
                str(definition["platform"]),
                DOMAIN,
                self._entity_unique_id(entity_key),
            )
            if entity_id is not None:
                return entity_id
        return None

    @property
    def _catalog_entity_definitions(self) -> dict[str, dict[str, Any]]:
        entities = self._store.catalog.get("entities", [])
        if not isinstance(entities, list):
            return {}
        return {
            str(definition["entity_key"]): definition
            for definition in entities
            if isinstance(definition, dict) and isinstance(definition.get("entity_key"), str)
        }

    def _command_name(self, command_key: str) -> str:
        commands = self._store.catalog.get("commands", [])
        if isinstance(commands, list):
            for command in commands:
                if isinstance(command, dict) and command.get("command_key") == command_key:
                    name = command.get("name")
                    if isinstance(name, str) and name:
                        return name
        return command_key

    def _entity_unique_id(self, entity_key: str) -> str:
        bootstrap = self._store.bootstrap
        instance_id = bootstrap.instance.instance_id if bootstrap else self._entry_id
        return f"{instance_id}:{entity_key}"


async def _async_ensure_lovelace(hass: HomeAssistant) -> bool:
    current = hass.data.get(LOVELACE_DOMAIN)
    if isinstance(current, dict) and isinstance(current.get("dashboards"), dict):
        return True
    return await async_setup_component(hass, LOVELACE_DOMAIN, {LOVELACE_DOMAIN: {"mode": MODE_STORAGE}})


async def _async_upsert_dashboard_metadata(
    hass: HomeAssistant,
    *,
    url_path: str,
    title: str,
    icon: str,
) -> dict[str, Any]:
    collection = lovelace_dashboard.DashboardsCollection(hass)
    await collection.async_load()
    runtime_dashboards = hass.data.get(LOVELACE_DOMAIN, {}).get("dashboards", {})
    runtime_dashboard = runtime_dashboards.get(url_path) if isinstance(runtime_dashboards, dict) else None
    runtime_metadata = getattr(runtime_dashboard, "config", None)
    existing = next(
        (item for item in collection.data.values() if isinstance(item, dict) and item.get(CONF_URL_PATH) == url_path),
        None,
    )
    if existing is None and isinstance(runtime_metadata, dict) and runtime_metadata.get(CONF_URL_PATH) == url_path:
        metadata = {
            **runtime_metadata,
            CONF_TITLE: title,
            CONF_ICON: icon,
            CONF_REQUIRE_ADMIN: False,
            CONF_SHOW_IN_SIDEBAR: True,
        }
    elif existing is None:
        metadata = await collection.async_create_item(
            {
                CONF_URL_PATH: url_path,
                CONF_TITLE: title,
                CONF_ICON: icon,
                CONF_REQUIRE_ADMIN: False,
                CONF_SHOW_IN_SIDEBAR: True,
                "mode": MODE_STORAGE,
            }
        )
    else:
        metadata = await collection.async_update_item(
            str(existing["id"]),
            {
                CONF_TITLE: title,
                CONF_ICON: icon,
                CONF_REQUIRE_ADMIN: False,
                CONF_SHOW_IN_SIDEBAR: True,
            },
        )
    _register_lovelace_panel(hass, metadata)
    return metadata


async def _async_save_dashboard_config(
    hass: HomeAssistant,
    *,
    metadata: dict[str, Any],
    config: dict[str, Any],
) -> None:
    dashboards = hass.data[LOVELACE_DOMAIN]["dashboards"]
    url_path = str(metadata[CONF_URL_PATH])
    config_store = dashboards.get(url_path)
    if config_store is None:
        config_store = lovelace_dashboard.LovelaceStorage(hass, metadata)
        dashboards[url_path] = config_store
    else:
        config_store.config = metadata

    current_config: dict[str, Any] | None
    try:
        current_config = await config_store.async_load(False)
    except ConfigNotFound:
        current_config = None
    if current_config == config:
        return
    await config_store.async_save(config)


@callback
def _register_lovelace_panel(hass: HomeAssistant, metadata: dict[str, Any]) -> None:
    url_path = str(metadata[CONF_URL_PATH])
    update = url_path in hass.data.get(DATA_PANELS, {})
    kwargs: dict[str, Any] = {
        "frontend_url_path": url_path,
        "require_admin": bool(metadata.get(CONF_REQUIRE_ADMIN, False)),
        "config": {"mode": MODE_STORAGE},
        "update": update,
    }
    if metadata.get(CONF_SHOW_IN_SIDEBAR, True):
        kwargs["sidebar_title"] = metadata[CONF_TITLE]
        kwargs["sidebar_icon"] = metadata.get(CONF_ICON, DEFAULT_ICON)
    frontend.async_register_built_in_panel(hass, LOVELACE_DOMAIN, **kwargs)


def _dashboard_summary(dashboard: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dashboard, dict) or not dashboard:
        return {
            "loaded": False,
            "slug": None,
            "title": None,
            "version": None,
            "view_keys": [],
            "views_count": 0,
            "sections_count": 0,
            "widgets_count": 0,
            "schema_hash": None,
            "lovelace_dashboard_url_path": None,
            "lovelace_render_hash": None,
            "lovelace_synced": False,
            "lovelace_error": None,
        }

    views = dashboard.get("views", [])
    if not isinstance(views, list):
        views = []
    view_keys: list[str] = []
    sections_count = 0
    widgets_count = 0
    for view in views:
        if not isinstance(view, dict):
            continue
        view_key = view.get("view_key")
        if isinstance(view_key, str):
            view_keys.append(view_key)
        sections = view.get("sections", [])
        if not isinstance(sections, list):
            continue
        sections_count += len([section for section in sections if isinstance(section, dict)])
        for section in sections:
            if not isinstance(section, dict):
                continue
            widgets = section.get("widgets", [])
            if not isinstance(widgets, list):
                continue
            widgets_count += len([widget for widget in widgets if isinstance(widget, dict)])

    return {
        "loaded": True,
        "slug": dashboard.get("slug") if isinstance(dashboard.get("slug"), str) else None,
        "title": dashboard.get("title") if isinstance(dashboard.get("title"), str) else None,
        "version": dashboard.get("version") if isinstance(dashboard.get("version"), int) else None,
        "view_keys": view_keys,
        "views_count": len(view_keys),
        "sections_count": sections_count,
        "widgets_count": widgets_count,
        "schema_hash": _dashboard_hash(dashboard),
        "lovelace_dashboard_url_path": None,
        "lovelace_render_hash": None,
        "lovelace_synced": False,
        "lovelace_error": None,
    }


def _dashboard_hash(dashboard: dict[str, Any]) -> str:
    payload = json.dumps(dashboard, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha1:{hashlib.sha1(payload).hexdigest()[:12]}"


def _markdown_card(*, title: str | None, content: str) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "markdown", "content": content}
    if title:
        card["title"] = title
    return card


def _format_collection_widget(*, title: str, kind: str, source: str, data: Any) -> str:
    if kind == "chart_placeholder":
        return f"_{title}_ is advertised by IRIS as `{source}`, but chart rendering is not wired yet."
    if data in (None, {}, []):
        return f"_No data available for `{source}` yet._"
    if kind == "table":
        return _format_table_markdown(data)
    if kind in {"list", "timeline"}:
        return _format_list_markdown(data)
    return _format_summary_markdown(data)


def _format_table_markdown(data: Any) -> str:
    if isinstance(data, dict) and data and all(isinstance(value, dict) for value in data.values()):
        keys = list(data.keys())[:8]
        columns = sorted({column for key in keys for column in data[key]})[:4]
        header = "| Key | " + " | ".join(columns) + " |"
        separator = "| --- | " + " | ".join(["---"] * len(columns)) + " |"
        rows = [
            "| "
            + key
            + " | "
            + " | ".join(_compact_markdown_value(data[key].get(column)) for column in columns)
            + " |"
            for key in keys
        ]
        return "\n".join([header, separator, *rows])
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        columns = sorted({column for item in data[:8] for column in item})[:4]
        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join(["---"] * len(columns)) + " |"
        rows = [
            "| " + " | ".join(_compact_markdown_value(item.get(column)) for column in columns) + " |"
            for item in data[:8]
        ]
        return "\n".join([header, separator, *rows])
    return _format_list_markdown(data)


def _format_list_markdown(data: Any) -> str:
    if isinstance(data, dict):
        items = list(data.items())[:8]
        return "\n".join(f"- **{key}**: {_compact_markdown_value(value)}" for key, value in items)
    if isinstance(data, list):
        return "\n".join(f"- {_compact_markdown_value(item)}" for item in data[:8])
    return f"- {_compact_markdown_value(data)}"


def _format_summary_markdown(data: Any) -> str:
    if isinstance(data, dict):
        return "\n".join(f"- **{key}**: {_compact_markdown_value(value)}" for key, value in list(data.items())[:8])
    return _compact_markdown_value(data)


def _compact_markdown_value(value: Any) -> str:
    if isinstance(value, str | int | float | bool) or value is None:
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _url_slug(value: str) -> str:
    return slugify(value).replace("_", "-")
