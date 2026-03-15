from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
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
_DASHBOARD_SYNC_DEBOUNCE_SECONDS = 0.25


class IrisDashboardRuntime:
    def __init__(self, hass: HomeAssistant, entry_id: str, store: IrisRuntimeStore) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store = store
        self._last_published_fingerprint: tuple[Any, ...] | None = None
        self._last_render_hash: str | None = None
        self._remove_store_listener: Callable[[], None] | None = None
        self._scheduled_sync_task: asyncio.Task[None] | None = None
        self._scheduled_reason = "runtime_store_updated"
        self._scheduled_force = False
        self._summary = _dashboard_summary({})

    async def async_setup(self) -> None:
        self._remove_store_listener = self._store.add_listener(self._handle_store_update)
        await self._async_publish_and_sync(reason="initial_load", force=True)

    async def async_stop(self) -> None:
        if self._remove_store_listener is not None:
            self._remove_store_listener()
            self._remove_store_listener = None
        if self._scheduled_sync_task is not None:
            self._scheduled_sync_task.cancel()
            self._scheduled_sync_task = None

    @callback
    def handle_dashboard_refresh(self) -> None:
        self._schedule_sync(reason="dashboard_changed")

    def summary(self) -> dict[str, Any]:
        return deepcopy(self._summary)

    @callback
    def _handle_store_update(self) -> None:
        self._schedule_sync(reason="runtime_store_updated")

    @callback
    def _schedule_sync(self, *, reason: str, force: bool = False) -> None:
        self._scheduled_reason = reason
        self._scheduled_force = self._scheduled_force or force
        if self._scheduled_sync_task is not None:
            self._scheduled_sync_task.cancel()
        self._scheduled_sync_task = self._hass.async_create_background_task(
            self._async_run_scheduled_sync(),
            f"{DOMAIN}_dashboard_sync",
        )

    async def _async_run_scheduled_sync(self) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(_DASHBOARD_SYNC_DEBOUNCE_SECONDS)
            await self._async_publish_and_sync(
                reason=self._scheduled_reason,
                force=self._scheduled_force,
            )
        except asyncio.CancelledError:
            raise
        finally:
            if self._scheduled_sync_task is current_task:
                self._scheduled_force = False
                self._scheduled_sync_task = None

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
                summary["lovelace_management_mode"] = "managed"
                summary["lovelace_override_detected"] = False
                summary["lovelace_current_hash"] = None
            else:
                summary.update(sync_result)
                summary["lovelace_synced"] = sync_result["lovelace_management_mode"] == "managed"
                summary["lovelace_error"] = None
        elif summary["loaded"]:
            summary["lovelace_synced"] = False
            summary["lovelace_error"] = "dashboard_capability_disabled"
            summary["lovelace_management_mode"] = "disabled"
            summary["lovelace_override_detected"] = False
            summary["lovelace_current_hash"] = None

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
        save_result = await _async_save_dashboard_config(
            self._hass,
            metadata=metadata,
            config=config,
            expected_previous_hash=self._last_render_hash,
            new_render_hash=render_hash,
        )
        if save_result["lovelace_management_mode"] == "managed":
            self._last_render_hash = render_hash
        return {
            "lovelace_dashboard_url_path": self._dashboard_url_path,
            "lovelace_render_hash": render_hash,
            "lovelace_current_hash": save_result["lovelace_current_hash"],
            "lovelace_management_mode": save_result["lovelace_management_mode"],
            "lovelace_override_detected": save_result["lovelace_override_detected"],
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
        config = widget.get("config", {})
        return _render_collection_widget_card(
            title=str(widget.get("title") or "Widget"),
            kind=str(widget.get("kind") or ""),
            source=source,
            data=_resolve_collection_data(self._store.collections.get(source), config=config),
            config=config if isinstance(config, dict) else {},
        )

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
    expected_previous_hash: str | None,
    new_render_hash: str,
) -> dict[str, Any]:
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
    current_hash = _dashboard_hash(current_config) if isinstance(current_config, dict) else None
    if current_config is not None and current_hash not in {expected_previous_hash, new_render_hash}:
        return {
            "lovelace_current_hash": current_hash,
            "lovelace_management_mode": "local_override",
            "lovelace_override_detected": True,
        }
    if current_config == config:
        return {
            "lovelace_current_hash": current_hash or new_render_hash,
            "lovelace_management_mode": "managed",
            "lovelace_override_detected": False,
        }
    await config_store.async_save(config)
    return {
        "lovelace_current_hash": new_render_hash,
        "lovelace_management_mode": "managed",
        "lovelace_override_detected": False,
    }


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
            "lovelace_current_hash": None,
            "lovelace_management_mode": "managed",
            "lovelace_override_detected": False,
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
        "lovelace_current_hash": None,
        "lovelace_management_mode": "managed",
        "lovelace_override_detected": False,
    }


def _dashboard_hash(dashboard: dict[str, Any]) -> str:
    payload = json.dumps(dashboard, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha1:{hashlib.sha1(payload).hexdigest()[:12]}"


def _markdown_card(*, title: str | None, content: str) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "markdown", "content": content}
    if title:
        card["title"] = title
    return card


def _render_collection_widget_card(
    *,
    title: str,
    kind: str,
    source: str,
    data: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    if kind == "chart_placeholder":
        return _markdown_card(
            title=title,
            content=f"_{title}_ is advertised by IRIS as `{source}`, but chart rendering is not wired yet.",
        )
    if data in (None, {}, []):
        return _markdown_card(title=title, content=f"_No data available for `{source}` yet._")

    item_cards = _collection_item_cards(kind=kind, data=data, config=config)
    if not item_cards:
        return _markdown_card(
            title=title,
            content=f"_No collection items could be rendered for `{source}` yet._",
        )

    if kind in {"list", "timeline"}:
        return {
            "type": "vertical-stack",
            "cards": [_markdown_card(title=None, content=f"### {title}"), *item_cards],
        }

    columns = max(1, min(_as_positive_int(config.get("grid_columns"), default=2), 3))
    return {
        "type": "vertical-stack",
        "cards": [
            _markdown_card(title=None, content=f"### {title}"),
            {
                "type": "grid",
                "columns": columns,
                "square": False,
                "cards": item_cards,
            },
        ],
    }


def _resolve_collection_data(data: Any, *, config: dict[str, Any]) -> Any:
    path = config.get("path")
    if isinstance(path, str) and path and isinstance(data, dict):
        return deepcopy(data.get(path))
    return deepcopy(data)


def _collection_item_cards(*, kind: str, data: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _collection_rows(data, config=config)
    cards: list[dict[str, Any]] = []
    for label, payload in rows:
        fields = _collection_fields(payload, config=config)
        lines = [f"**{_titleize(field)}**: {_compact_markdown_value(payload.get(field))}" for field in fields]
        if not lines:
            lines = [_compact_markdown_value(payload)]
        cards.append(_markdown_card(title=label, content="\n".join(lines)))
    if kind == "summary" and not cards:
        return [_markdown_card(title=None, content=_compact_markdown_value(data))]
    return cards


def _collection_rows(data: Any, *, config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    max_items = _as_positive_int(config.get("max_items"), default=6)
    if isinstance(data, dict):
        if data and all(isinstance(value, dict) for value in data.values()):
            rows: list[tuple[str, dict[str, Any]]] = []
            for key, value in list(data.items())[:max_items]:
                payload = deepcopy(value)
                payload.setdefault("symbol", key)
                rows.append((str(key), payload))
            return rows
        return [("Summary", dict(data))]
    if isinstance(data, list):
        rows = []
        for index, item in enumerate(data[:max_items], start=1):
            if isinstance(item, dict):
                label = (
                    item.get("symbol")
                    or item.get("name")
                    or item.get("prediction_event")
                    or f"Item {index}"
                )
                rows.append((str(label), deepcopy(item)))
            else:
                rows.append((f"Item {index}", {"value": item}))
        return rows
    return [("Value", {"value": data})]


def _collection_fields(payload: Any, *, config: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        return ["value"]
    configured = config.get("columns") or config.get("fields")
    if isinstance(configured, list):
        fields = [str(field) for field in configured if isinstance(field, str) and field in payload]
        if fields:
            return fields
    return list(payload)[:4]


def _as_positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _compact_markdown_value(value: Any) -> str:
    if isinstance(value, str | int | float | bool) or value is None:
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _titleize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _url_slug(value: str) -> str:
    return slugify(value).replace("_", "-")
