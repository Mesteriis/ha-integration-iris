from __future__ import annotations

from ipaddress import ip_address

from custom_components.iris.bootstrap import IrisBootstrap, IrisCapabilities, IrisInstanceInfo
from homeassistant.components.zeroconf import ZeroconfServiceInfo


def build_bootstrap() -> IrisBootstrap:
    return IrisBootstrap(
        instance=IrisInstanceInfo(
            instance_id="iris-main-001",
            display_name="IRIS Main",
            version="2026.03.15",
            protocol_version=1,
            catalog_version="sha1:123456789abc",
            mode="full",
            minimum_ha_integration_version="0.1.0",
            recommended_ha_integration_version="0.1.0",
        ),
        capabilities=IrisCapabilities(
            dashboard=True,
            commands=True,
            collections=True,
            promoted_entities=False,
        ),
        catalog_url="http://localhost:8000/api/v1/ha/catalog",
        dashboard_url="http://localhost:8000/api/v1/ha/dashboard",
        ws_url="ws://localhost:8000/api/v1/ha/ws",
        state_url="http://localhost:8000/api/v1/ha/state",
    )


def build_catalog() -> dict:
    availability = {"modes": ["full", "local", "ha_addon"], "requires_features": [], "status": "active"}
    since_version = "2026.03.15"
    return {
        "catalog_version": "sha1:123456789abc",
        "protocol_version": 1,
        "mode": "full",
        "entities": [
            {
                "entity_key": "system.connection",
                "platform": "binary_sensor",
                "name": "IRIS Connection",
                "state_source": "system.connection",
                "icon": "mdi:lan-connect",
                "category": "diagnostic",
                "availability": availability,
                "since_version": since_version,
                "entity_registry_enabled_default": True,
            },
            {
                "entity_key": "system.mode",
                "platform": "sensor",
                "name": "IRIS Mode",
                "state_source": "system.mode",
                "icon": "mdi:server-network",
                "category": "diagnostic",
                "translation_key": "system_mode",
                "availability": availability,
                "since_version": since_version,
                "entity_registry_enabled_default": True,
            },
            {
                "entity_key": "market.summary.active_assets_count",
                "platform": "sensor",
                "name": "Active Assets",
                "state_source": "market.summary.active_assets_count",
                "icon": "mdi:chart-bubble",
                "unit_of_measurement": "assets",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "market.summary.hot_assets_count",
                "platform": "sensor",
                "name": "Hot Assets",
                "state_source": "market.summary.hot_assets_count",
                "icon": "mdi:fire",
                "unit_of_measurement": "assets",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "portfolio.summary.portfolio_value",
                "platform": "sensor",
                "name": "Portfolio Value",
                "state_source": "portfolio.summary.portfolio_value",
                "icon": "mdi:wallet",
                "unit_of_measurement": "USD",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "portfolio.summary.open_positions",
                "platform": "sensor",
                "name": "Open Positions",
                "state_source": "portfolio.summary.open_positions",
                "icon": "mdi:briefcase-outline",
                "unit_of_measurement": "positions",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "notifications.enabled",
                "platform": "binary_sensor",
                "name": "Notifications Enabled",
                "state_source": "notifications.enabled",
                "icon": "mdi:bell-ring-outline",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "settings.notifications_enabled",
                "platform": "switch",
                "name": "Notifications Enabled",
                "state_source": "settings.notifications_enabled",
                "command_key": "settings.notifications_enabled.set",
                "icon": "mdi:toggle-switch",
                "category": "config",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "settings.default_timeframe",
                "platform": "select",
                "name": "Default Timeframe",
                "state_source": "settings.default_timeframe",
                "command_key": "settings.default_timeframe.set",
                "icon": "mdi:timeline-clock-outline",
                "category": "config",
                "availability": availability,
                "since_version": since_version,
                "options": ["15m", "1h", "4h", "1d"],
            },
            {
                "entity_key": "actions.portfolio_sync",
                "platform": "button",
                "name": "Portfolio Sync",
                "state_source": "actions.portfolio_sync",
                "command_key": "portfolio.sync",
                "icon": "mdi:sync",
                "category": "config",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "entity_key": "actions.market_refresh",
                "platform": "button",
                "name": "Market Refresh",
                "state_source": "actions.market_refresh",
                "command_key": "market.refresh",
                "icon": "mdi:refresh-circle",
                "category": "config",
                "availability": availability,
                "since_version": since_version,
            },
        ],
        "collections": [
            {
                "collection_key": "assets.snapshot",
                "kind": "mapping",
                "transport": "websocket",
                "dashboard_only": False,
                "since_version": since_version,
            },
            {
                "collection_key": "portfolio.snapshot",
                "kind": "summary",
                "transport": "websocket",
                "dashboard_only": False,
                "since_version": since_version,
            },
        ],
        "commands": [
            {
                "command_key": "portfolio.sync",
                "name": "Portfolio Sync",
                "kind": "refresh",
                "returns": "operation",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "command_key": "market.refresh",
                "name": "Market Refresh",
                "kind": "refresh",
                "returns": "operation",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "command_key": "settings.notifications_enabled.set",
                "name": "Set Notifications Enabled",
                "kind": "toggle",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "boolean"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "returns": "operation",
                "availability": availability,
                "since_version": since_version,
            },
            {
                "command_key": "settings.default_timeframe.set",
                "name": "Set Default Timeframe",
                "kind": "selection",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string", "enum": ["15m", "1h", "4h", "1d"]}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "returns": "operation",
                "availability": availability,
                "since_version": since_version,
            },
        ],
        "views": [],
    }


def build_dashboard() -> dict:
    return {
        "version": 1,
        "slug": "iris",
        "title": "IRIS Main",
        "views": [
            {
                "view_key": "overview",
                "title": "Overview",
                "sections": [
                    {
                        "section_key": "system",
                        "title": "System",
                        "widgets": [
                            {
                                "widget_key": "system_status",
                                "title": "Connection",
                                "kind": "status",
                                "source": "system.connection",
                                "entity_keys": ["system.connection", "system.mode"],
                            },
                            {
                                "widget_key": "market_summary",
                                "title": "Market Summary",
                                "kind": "summary",
                                "source": "market.summary",
                                "entity_keys": [
                                    "market.summary.active_assets_count",
                                    "market.summary.hot_assets_count",
                                ],
                            },
                        ],
                    },
                    {
                        "section_key": "actions",
                        "title": "Actions",
                        "widgets": [
                            {
                                "widget_key": "market_actions",
                                "title": "Market Actions",
                                "kind": "actions",
                                "source": "market.actions",
                                "command_keys": ["portfolio.sync", "market.refresh"],
                            }
                        ],
                    },
                ],
            },
            {
                "view_key": "assets",
                "title": "Assets",
                "sections": [
                    {
                        "section_key": "assets_snapshot",
                        "title": "Tracked Assets",
                        "widgets": [
                            {
                                "widget_key": "assets_table",
                                "title": "Assets Snapshot",
                                "kind": "table",
                                "source": "assets.snapshot",
                            }
                        ],
                    }
                ],
            },
            {
                "view_key": "portfolio",
                "title": "Portfolio",
                "sections": [
                    {
                        "section_key": "portfolio",
                        "title": "Portfolio",
                        "widgets": [
                            {
                                "widget_key": "portfolio_summary",
                                "title": "Portfolio",
                                "kind": "summary",
                                "source": "portfolio.snapshot",
                                "entity_keys": [
                                    "portfolio.summary.portfolio_value",
                                    "portfolio.summary.open_positions",
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "view_key": "integrations",
                "title": "Integrations",
                "sections": [
                    {
                        "section_key": "integrations",
                        "title": "Integrations",
                        "widgets": [
                            {
                                "widget_key": "integrations_snapshot",
                                "title": "Integrations Snapshot",
                                "kind": "list",
                                "source": "integrations.snapshot",
                            }
                        ],
                    }
                ],
            },
            {
                "view_key": "system",
                "title": "System",
                "sections": [
                    {
                        "section_key": "runtime",
                        "title": "Runtime",
                        "widgets": [
                            {
                                "widget_key": "system_runtime",
                                "title": "Runtime Status",
                                "kind": "status",
                                "source": "system.connection",
                                "entity_keys": [
                                    "system.connection",
                                    "system.mode",
                                    "notifications.enabled",
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }


def build_state_snapshot() -> dict:
    return {
        "projection_epoch": "20260315T000000Z-stage3",
        "sequence": 4,
        "entities": {
            "system.connection": {"state": "connected", "attributes": {}},
            "system.mode": {"state": "full", "attributes": {}},
            "market.summary.active_assets_count": {"state": 4, "attributes": {}},
            "market.summary.hot_assets_count": {"state": 1, "attributes": {}},
            "portfolio.summary.portfolio_value": {"state": 125000.0, "attributes": {"currency": "USD"}},
            "portfolio.summary.open_positions": {"state": 2, "attributes": {}},
            "notifications.enabled": {"state": True, "attributes": {}},
            "settings.notifications_enabled": {
                "state": True,
                "attributes": {"command_key": "settings.notifications_enabled.set"},
            },
            "settings.default_timeframe": {
                "state": "15m",
                "attributes": {
                    "command_key": "settings.default_timeframe.set",
                    "options": ["15m", "1h", "4h", "1d"],
                },
            },
            "actions.portfolio_sync": {"state": "available", "attributes": {"command_key": "portfolio.sync"}},
            "actions.market_refresh": {"state": "available", "attributes": {"command_key": "market.refresh"}},
        },
        "collections": {
            "assets.snapshot": {"BTCUSD": {"market_regime": "bull_trend"}},
            "portfolio.snapshot": {"positions": []},
        },
    }


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
