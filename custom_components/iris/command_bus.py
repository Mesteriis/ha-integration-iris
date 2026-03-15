from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .store import IrisRuntimeStore
from .websocket_client import IrisWebSocketClient


class IrisCommandBus:
    def __init__(
        self,
        websocket: IrisWebSocketClient,
        store: IrisRuntimeStore,
    ) -> None:
        self._websocket = websocket
        self._store = store

    async def async_execute(self, *, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_payload = dict(payload or {})
        if self._command_definition(command) is None:
            raise HomeAssistantError(f"IRIS command '{command}' is not present in the current catalog.")
        ack = await self._websocket.async_execute_command(command=command, payload=normalized_payload)
        if not ack.get("accepted"):
            error = ack.get("error") if isinstance(ack.get("error"), dict) else {}
            code = str(error.get("code") or "command_failed")
            message = str(error.get("message") or f"IRIS command '{command}' was rejected.")
            raise HomeAssistantError(f"{message} [{code}]")
        operation_id = ack.get("operation_id")
        self._store.apply_command_ack(command=command, operation_id=operation_id if isinstance(operation_id, str) else None)
        instance_id = self._store.bootstrap.instance.instance_id if self._store.bootstrap else None
        response = {
            "accepted": True,
            "command": command,
            "operation_id": operation_id,
        }
        if instance_id is not None:
            response["instance_id"] = instance_id
        return response

    def _command_definition(self, command: str) -> dict[str, Any] | None:
        commands = self._store.catalog.get("commands", [])
        if not isinstance(commands, list):
            return None
        for item in commands:
            if not isinstance(item, dict):
                continue
            if item.get("command_key") == command:
                return item
        return None
