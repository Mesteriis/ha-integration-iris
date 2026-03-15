from __future__ import annotations

from dataclasses import dataclass

from .bootstrap import IrisBootstrap
from .const import INTEGRATION_VERSION, SUPPORTED_PROTOCOL_VERSION


class IrisCompatibilityError(ValueError):
    """Raised when the backend bootstrap is incompatible with this integration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True, frozen=True)
class IrisCompatibilityReport:
    recommended_upgrade: bool


def validate_bootstrap_compatibility(bootstrap: IrisBootstrap) -> IrisCompatibilityReport:
    if bootstrap.instance.protocol_version != SUPPORTED_PROTOCOL_VERSION:
        raise IrisCompatibilityError(
            "unsupported_protocol",
            (
                f"IRIS protocol v{bootstrap.instance.protocol_version} is not supported by "
                f"integration protocol v{SUPPORTED_PROTOCOL_VERSION}."
            ),
        )
    if _parse_version(INTEGRATION_VERSION) < _parse_version(bootstrap.instance.minimum_ha_integration_version):
        raise IrisCompatibilityError(
            "integration_too_old",
            (
                "This IRIS backend requires a newer Home Assistant integration version "
                f"(minimum {bootstrap.instance.minimum_ha_integration_version})."
            ),
        )
    return IrisCompatibilityReport(
        recommended_upgrade=_parse_version(INTEGRATION_VERSION)
        < _parse_version(bootstrap.instance.recommended_ha_integration_version)
    )


def _parse_version(raw: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in raw.split("."))
    if not parts:
        raise IrisCompatibilityError("invalid_version", f"Invalid version string: {raw}")
    return parts
