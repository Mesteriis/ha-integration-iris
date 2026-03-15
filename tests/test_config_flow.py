from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.iris.config_flow import RECONFIGURE_SOURCE, IrisConfigFlow
from custom_components.iris.const import CONF_API_URL, CONF_INSTANCE_ID, DOMAIN
from homeassistant.const import CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import build_bootstrap, build_zeroconf_service_info


async def test_config_flow_user_step_validates_bootstrap_and_creates_entry(hass) -> None:
    bootstrap = build_bootstrap()
    with patch(
        "custom_components.iris.config_flow.IrisApiClient.async_get_bootstrap",
        new=AsyncMock(return_value=bootstrap),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_URL: "http://localhost:8000"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "IRIS Main"
    assert result["data"][CONF_API_URL] == "http://localhost:8000"
    assert result["data"][CONF_INSTANCE_ID] == "iris-main-001"


async def test_config_flow_zeroconf_creates_entry_after_confirmation(hass) -> None:
    with patch(
        "custom_components.iris.config_flow.IrisApiClient.async_get_bootstrap",
        new=AsyncMock(return_value=build_bootstrap()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "zeroconf"},
            data=build_zeroconf_service_info(),
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "zeroconf_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TOKEN: "stage3-token"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "IRIS Main"
    assert result["data"][CONF_API_URL] == "http://192.168.1.10:8000"
    assert result["data"][CONF_INSTANCE_ID] == "iris-main-001"
    assert result["data"][CONF_TOKEN] == "stage3-token"


async def test_zeroconf_rediscovers_existing_instance_and_updates_api_url(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        unique_id="iris-main-001",
        data={
            CONF_API_URL: "http://192.168.1.10:8000",
            CONF_INSTANCE_ID: "iris-main-001",
            CONF_TOKEN: "old-token",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "zeroconf"},
        data=build_zeroconf_service_info(host="192.168.1.25", api_port=8123),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_API_URL] == "http://192.168.1.25:8123"
    assert updated_entry.data[CONF_TOKEN] == "old-token"


async def test_reauth_flow_updates_token_for_existing_entry(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        unique_id="iris-main-001",
        data={
            CONF_API_URL: "http://localhost:8000",
            CONF_INSTANCE_ID: "iris-main-001",
            CONF_TOKEN: "expired-token",
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.iris.config_flow.IrisApiClient.async_get_bootstrap",
        new=AsyncMock(return_value=build_bootstrap()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": entry.entry_id, "unique_id": entry.unique_id},
            data=dict(entry.data),
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TOKEN: "fresh-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_TOKEN] == "fresh-token"
    assert updated_entry.data[CONF_API_URL] == "http://localhost:8000"


async def test_reconfigure_flow_updates_backend_url_for_existing_entry(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="IRIS Main",
        unique_id="iris-main-001",
        data={
            CONF_API_URL: "http://localhost:8000",
            CONF_INSTANCE_ID: "iris-main-001",
            CONF_TOKEN: "stage3-token",
        },
    )
    entry.add_to_hass(hass)

    flow = IrisConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "test-reconfigure"
    flow.context = {"source": RECONFIGURE_SOURCE, "entry_id": entry.entry_id, "unique_id": entry.unique_id}

    with patch(
        "custom_components.iris.config_flow.IrisApiClient.async_get_bootstrap",
        new=AsyncMock(return_value=build_bootstrap()),
    ):
        result = await flow.async_step_reconfigure()

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == RECONFIGURE_SOURCE

        result = await flow.async_step_reconfigure({CONF_API_URL: "http://192.168.1.55:9000"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_API_URL] == "http://192.168.1.55:9000"
    assert updated_entry.data[CONF_TOKEN] == "stage3-token"
