from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .bootstrap import IrisBootstrap

StoreListener = Callable[[], None]

STATE_BEARING_MESSAGE_TYPES = frozenset(
    {
        "entity_state_changed",
        "state_patch",
        "collection_snapshot",
        "collection_patch",
        "catalog_changed",
        "dashboard_changed",
        "operation_update",
        "system_health",
    }
)


@dataclass(slots=True)
class IrisRuntimeStore:
    bootstrap: IrisBootstrap | None = None
    catalog: dict[str, Any] = field(default_factory=dict)
    dashboard: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    collections: dict[str, Any] = field(default_factory=dict)
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    websocket_connected: bool = False
    last_error: str | None = None
    last_system_health: dict[str, Any] | None = None
    projection_epoch: str | None = None
    sequence: int | None = None
    _listeners: list[StoreListener] = field(default_factory=list, init=False, repr=False)

    def add_listener(self, listener: StoreListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove_listener

    def apply_bootstrap(self, bootstrap: IrisBootstrap) -> None:
        self.bootstrap = bootstrap
        self._notify()

    def apply_catalog(self, catalog: dict[str, Any]) -> None:
        self.catalog = deepcopy(catalog)
        self._notify()

    def apply_dashboard(self, dashboard: dict[str, Any]) -> None:
        self.dashboard = deepcopy(dashboard)
        self._notify()

    def apply_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        projection_epoch = snapshot.get("projection_epoch")
        sequence = snapshot.get("sequence")
        entities = snapshot.get("entities", {})
        collections = snapshot.get("collections", {})
        if isinstance(projection_epoch, str):
            self.projection_epoch = projection_epoch
        if isinstance(sequence, int):
            self.sequence = sequence
        self.entities = deepcopy(entities) if isinstance(entities, dict) else {}
        self.collections = deepcopy(collections) if isinstance(collections, dict) else {}
        self.last_error = None
        self._notify()

    def set_connection_state(self, connected: bool, *, error: str | None = None) -> None:
        if self.websocket_connected == connected and self.last_error == error:
            return
        self.websocket_connected = connected
        self.last_error = error
        self._notify()

    def apply_command_ack(self, *, command: str, operation_id: str | None) -> None:
        if not operation_id:
            return
        current = deepcopy(self.operations.get(operation_id, {}))
        current.update(
            {
                "type": "operation_update",
                "operation_id": operation_id,
                "command": command,
                "status": current.get("status") or "accepted",
            }
        )
        self.operations[operation_id] = current
        self._notify()

    def apply_websocket_message(self, payload: dict[str, Any]) -> set[str]:
        actions: set[str] = set()
        message_type = str(payload.get("type") or "")
        if message_type in STATE_BEARING_MESSAGE_TYPES:
            actions |= self._track_projection(payload)
        if message_type == "entity_state_changed":
            entity_key = str(payload.get("entity_key") or "")
            if entity_key:
                self.entities[entity_key] = {
                    "state": payload.get("state"),
                    "attributes": payload.get("attributes", {}),
                }
        elif message_type == "state_patch":
            path = str(payload.get("path") or "")
            if path:
                current = deepcopy(self.entities.get(path, {}))
                current["state"] = payload.get("value")
                current.setdefault("attributes", {})
                self.entities[path] = current
        elif message_type == "collection_snapshot":
            collection_key = str(payload.get("collection_key") or "")
            if collection_key:
                self.collections[collection_key] = deepcopy(payload.get("data"))
        elif message_type == "collection_patch":
            self._apply_collection_patch(payload)
        elif message_type == "operation_update":
            operation_id = str(payload.get("operation_id") or "")
            if operation_id:
                self.operations[operation_id] = deepcopy(payload)
        elif message_type == "system_health":
            self.last_system_health = deepcopy(payload)
        elif message_type == "catalog_changed":
            actions.add("refresh_catalog")
        elif message_type == "dashboard_changed":
            actions.add("refresh_dashboard")
        elif message_type == "resync_required":
            self.last_error = str(payload.get("reason") or "resync_required")
            actions.add("full_resync")
        if message_type != "event_emitted":
            self._notify()
        return actions

    def tracked_entity_keys(self) -> list[str]:
        entities = self.catalog.get("entities", [])
        if not isinstance(entities, list):
            return []
        keys = [
            str(item.get("entity_key"))
            for item in entities
            if isinstance(item, dict) and isinstance(item.get("entity_key"), str)
        ]
        return sorted(set(keys))

    def tracked_collection_keys(self) -> list[str]:
        collections = self.catalog.get("collections", [])
        if not isinstance(collections, list):
            return []
        keys = [
            str(item.get("collection_key"))
            for item in collections
            if isinstance(item, dict) and isinstance(item.get("collection_key"), str)
        ]
        return sorted(set(keys))

    def entity_state(self, entity_key: str) -> dict[str, Any]:
        state = self.entities.get(entity_key)
        if isinstance(state, dict):
            return state
        return {}

    def summary(self) -> dict[str, Any]:
        return {
            "instance_id": self.bootstrap.instance.instance_id if self.bootstrap else None,
            "display_name": self.bootstrap.instance.display_name if self.bootstrap else None,
            "backend_version": self.bootstrap.instance.version if self.bootstrap else None,
            "protocol_version": self.bootstrap.instance.protocol_version if self.bootstrap else None,
            "catalog_version": self.bootstrap.instance.catalog_version if self.bootstrap else None,
            "mode": self.bootstrap.instance.mode if self.bootstrap else None,
            "websocket_connected": self.websocket_connected,
            "last_error": self.last_error,
            "projection_epoch": self.projection_epoch,
            "sequence": self.sequence,
        }

    def _track_projection(self, payload: dict[str, Any]) -> set[str]:
        projection_epoch = payload.get("projection_epoch")
        sequence = payload.get("sequence")
        if not isinstance(projection_epoch, str) or not isinstance(sequence, int):
            return {"full_resync"}
        if self.projection_epoch is None or self.sequence is None:
            self.projection_epoch = projection_epoch
            self.sequence = sequence
            return set()
        if projection_epoch != self.projection_epoch or sequence != self.sequence + 1:
            self.last_error = "projection_gap"
            return {"full_resync"}
        self.projection_epoch = projection_epoch
        self.sequence = sequence
        return set()

    def _apply_collection_patch(self, payload: dict[str, Any]) -> None:
        collection_key = str(payload.get("collection_key") or "")
        if not collection_key:
            return
        operation = str(payload.get("op") or "")
        path = str(payload.get("path") or "")
        current = deepcopy(self.collections.get(collection_key))
        if operation == "replace":
            self.collections[collection_key] = deepcopy(payload.get("value"))
            return
        if not isinstance(current, dict):
            current = {}
        if operation == "remove":
            current.pop(path, None)
        else:
            current[path] = deepcopy(payload.get("value"))
        self.collections[collection_key] = current

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
