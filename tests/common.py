from __future__ import annotations

import json
from copy import deepcopy
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from custom_components.iris.bootstrap import IrisBootstrap, parse_bootstrap_payload
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

_FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "contract"


def build_bootstrap() -> IrisBootstrap:
    return parse_bootstrap_payload(_load_fixture("bootstrap.json"), base_url="http://localhost:8000/")


def build_catalog() -> dict[str, Any]:
    return _load_fixture("catalog.json")


def build_dashboard() -> dict[str, Any]:
    return _load_fixture("dashboard.json")


def build_state_snapshot() -> dict[str, Any]:
    return _load_fixture("state.json")


def build_zeroconf_service_info(*, host: str = "192.168.1.10", api_port: int = 8000) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=api_port,
        hostname="iris-main.local.",
        type="_iris._tcp.local.",
        name="IRIS Main._iris._tcp.local.",
        properties={
            "instance_id": "iris-main-001",
            "display_name": "IRIS Main",
            "api_port": str(api_port),
            "protocol_version": "1",
            "requires_auth": "true",
        },
    )


def _load_fixture(name: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURES_ROOT / name).read_text(encoding="utf-8"))
    return deepcopy(payload)
