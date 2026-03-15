from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin


class IrisBootstrapError(ValueError):
    """Raised when the backend bootstrap payload is invalid."""


@dataclass(slots=True, frozen=True)
class IrisInstanceInfo:
    instance_id: str
    display_name: str
    version: str
    protocol_version: int
    catalog_version: str
    mode: str
    minimum_ha_integration_version: str
    recommended_ha_integration_version: str


@dataclass(slots=True, frozen=True)
class IrisCapabilities:
    dashboard: bool
    commands: bool
    collections: bool
    promoted_entities: bool


@dataclass(slots=True, frozen=True)
class IrisBootstrap:
    instance: IrisInstanceInfo
    capabilities: IrisCapabilities
    catalog_url: str
    dashboard_url: str
    ws_url: str
    state_url: str


def parse_bootstrap_payload(payload: dict[str, Any], *, base_url: str) -> IrisBootstrap:
    try:
        instance_payload = _as_dict(payload["instance"], field_name="instance")
        capabilities_payload = _as_dict(payload["capabilities"], field_name="capabilities")
    except KeyError as exc:
        raise IrisBootstrapError(f"Missing required bootstrap field: {exc.args[0]}") from exc

    instance = IrisInstanceInfo(
        instance_id=_as_str(instance_payload.get("instance_id"), field_name="instance.instance_id"),
        display_name=_as_str(instance_payload.get("display_name"), field_name="instance.display_name"),
        version=_as_str(instance_payload.get("version"), field_name="instance.version"),
        protocol_version=_as_int(instance_payload.get("protocol_version"), field_name="instance.protocol_version"),
        catalog_version=_as_str(instance_payload.get("catalog_version"), field_name="instance.catalog_version"),
        mode=_as_str(instance_payload.get("mode"), field_name="instance.mode"),
        minimum_ha_integration_version=_as_str(
            instance_payload.get("minimum_ha_integration_version"),
            field_name="instance.minimum_ha_integration_version",
        ),
        recommended_ha_integration_version=_as_str(
            instance_payload.get("recommended_ha_integration_version"),
            field_name="instance.recommended_ha_integration_version",
        ),
    )
    capabilities = IrisCapabilities(
        dashboard=_as_bool(capabilities_payload.get("dashboard"), field_name="capabilities.dashboard"),
        commands=_as_bool(capabilities_payload.get("commands"), field_name="capabilities.commands"),
        collections=_as_bool(capabilities_payload.get("collections"), field_name="capabilities.collections"),
        promoted_entities=_as_bool(
            capabilities_payload.get("promoted_entities", False),
            field_name="capabilities.promoted_entities",
        ),
    )
    return IrisBootstrap(
        instance=instance,
        capabilities=capabilities,
        catalog_url=_resolve_relative_url(payload.get("catalog_url"), base_url=base_url, field_name="catalog_url"),
        dashboard_url=_resolve_relative_url(
            payload.get("dashboard_url"),
            base_url=base_url,
            field_name="dashboard_url",
        ),
        ws_url=_resolve_relative_url(payload.get("ws_url"), base_url=base_url, field_name="ws_url"),
        state_url=_resolve_relative_url(payload.get("state_url"), base_url=base_url, field_name="state_url"),
    )


def _as_dict(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IrisBootstrapError(f"Bootstrap field '{field_name}' must be an object.")
    return value


def _as_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IrisBootstrapError(f"Bootstrap field '{field_name}' must be a non-empty string.")
    return value


def _as_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int):
        raise IrisBootstrapError(f"Bootstrap field '{field_name}' must be an integer.")
    return value


def _as_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise IrisBootstrapError(f"Bootstrap field '{field_name}' must be a boolean.")
    return value


def _resolve_relative_url(value: Any, *, base_url: str, field_name: str) -> str:
    return urljoin(base_url, _as_str(value, field_name=field_name))
