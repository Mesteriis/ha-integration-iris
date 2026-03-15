from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


def command_not_available_error(*, action: str, entity_key: str) -> HomeAssistantError:
    return HomeAssistantError(
        f"IRIS command bridge is not available yet, cannot {action} for catalog entity '{entity_key}'."
    )
