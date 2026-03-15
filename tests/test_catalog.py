from __future__ import annotations

import pytest
from custom_components.iris.catalog import IrisCatalogError, parse_catalog_payload, parse_dashboard_payload

from .common import build_catalog, build_dashboard


def test_parse_catalog_payload_accepts_backend_shaped_catalog() -> None:
    catalog = build_catalog()

    parsed = parse_catalog_payload(catalog)

    assert parsed["catalog_version"] == "sha1:123456789abc"
    assert parsed["entities"][1]["translation_key"] == "system_mode"
    assert parsed["collections"][0]["transport"] == "websocket"


def test_parse_catalog_payload_rejects_invalid_entity_definition() -> None:
    catalog = build_catalog()
    del catalog["entities"][0]["since_version"]

    with pytest.raises(IrisCatalogError, match="since_version"):
        parse_catalog_payload(catalog)


def test_parse_dashboard_payload_accepts_backend_shaped_dashboard() -> None:
    dashboard = build_dashboard()

    parsed = parse_dashboard_payload(dashboard)

    assert parsed["slug"] == "iris"
    assert parsed["views"][0]["sections"][0]["widgets"][0]["widget_key"] == "system_status"
