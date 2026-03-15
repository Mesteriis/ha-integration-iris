from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import IrisApiClient, IrisAuthenticationError, IrisConnectionError, IrisProtocolError
from .const import CONF_API_URL, CONF_INSTANCE_ID, DOMAIN
from .versioning import IrisCompatibilityError, validate_bootstrap_compatibility

RECONFIGURE_SOURCE = "reconfigure"


@dataclass(slots=True, frozen=True)
class IrisDiscoveryContext:
    api_url: str
    instance_id: str
    display_name: str
    requires_auth: bool


class IrisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: IrisDiscoveryContext | None = None
        self._reauth_entry: ConfigEntry | None = None
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            result = await self._async_create_entry_from_input(
                api_url=user_input[CONF_API_URL],
                auth_token=user_input.get(CONF_TOKEN, ""),
            )
            if result["errors"]:
                errors = result["errors"]
            else:
                return result["flow"]

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_user_schema(default_api_url="http://localhost:8000"),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        try:
            discovery = _parse_discovery_info(discovery_info)
        except ValueError:
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(discovery.instance_id)
        self._abort_if_unique_id_configured(
            updates={
                CONF_API_URL: discovery.api_url,
                CONF_INSTANCE_ID: discovery.instance_id,
            }
        )

        self._discovery = discovery
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._discovery is None:
            return self.async_abort(reason="invalid_discovery")

        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_create_entry_from_input(
                api_url=self._discovery.api_url,
                auth_token=user_input.get(CONF_TOKEN, ""),
                expected_instance_id=self._discovery.instance_id,
            )
            if result["errors"]:
                errors = result["errors"]
            else:
                return result["flow"]

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_TOKEN, default=""): str}),
            description_placeholders={
                "name": self._discovery.display_name,
                "host": self._discovery.api_url,
            },
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        self._reauth_entry = self._resolve_existing_entry(entry_data)
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown_entry")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown_entry")

        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_update_existing_entry(
                entry=self._reauth_entry,
                api_url=self._reauth_entry.data[CONF_API_URL],
                auth_token=user_input.get(CONF_TOKEN, ""),
                reason="reauth_successful",
            )
            if result["errors"]:
                errors = result["errors"]
            else:
                return result["flow"]

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._reconfigure_entry is None:
            self._reconfigure_entry = self._resolve_existing_entry()
        if self._reconfigure_entry is None:
            return self.async_abort(reason="unknown_entry")

        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_update_existing_entry(
                entry=self._reconfigure_entry,
                api_url=user_input[CONF_API_URL],
                auth_token=self._reconfigure_entry.data.get(CONF_TOKEN, ""),
                reason="reconfigure_successful",
            )
            if result["errors"]:
                errors = result["errors"]
            else:
                return result["flow"]

        return self.async_show_form(
            step_id=RECONFIGURE_SOURCE,
            data_schema=self._build_user_schema(
                default_api_url=self._reconfigure_entry.data[CONF_API_URL],
                include_token=False,
            ),
            description_placeholders={"name": self._reconfigure_entry.title},
            errors=errors,
        )

    async def _async_create_entry_from_input(
        self,
        *,
        api_url: str,
        auth_token: str,
        expected_instance_id: str | None = None,
    ) -> dict[str, Any]:
        errors, bootstrap = await self._async_validate_input(api_url=api_url, auth_token=auth_token)
        if errors:
            return {"errors": errors}

        if expected_instance_id is not None and bootstrap.instance.instance_id != expected_instance_id:
            return {"errors": {"base": "wrong_account"}}

        await self.async_set_unique_id(bootstrap.instance.instance_id)
        self._abort_if_unique_id_configured()
        return {
            "errors": {},
            "flow": self.async_create_entry(
                title=bootstrap.instance.display_name,
                data={
                    CONF_API_URL: _normalize_api_url(api_url),
                    CONF_INSTANCE_ID: bootstrap.instance.instance_id,
                    CONF_TOKEN: _normalize_token(auth_token),
                },
            ),
        }

    async def _async_update_existing_entry(
        self,
        *,
        entry: ConfigEntry,
        api_url: str,
        auth_token: str,
        reason: str,
    ) -> dict[str, Any]:
        errors, bootstrap = await self._async_validate_input(api_url=api_url, auth_token=auth_token)
        if errors:
            return {"errors": errors}

        current_instance_id = _entry_instance_id(entry)
        if current_instance_id is not None and bootstrap.instance.instance_id != current_instance_id:
            return {"errors": {"base": "wrong_account"}}

        updated_data = {
            **dict(entry.data),
            CONF_API_URL: _normalize_api_url(api_url),
            CONF_INSTANCE_ID: bootstrap.instance.instance_id,
            CONF_TOKEN: _normalize_token(auth_token),
        }
        return {
            "errors": {},
            "flow": self.async_update_reload_and_abort(
                entry,
                data=updated_data,
                reason=reason,
            ),
        }

    async def _async_validate_input(
        self,
        *,
        api_url: str,
        auth_token: str,
    ) -> tuple[dict[str, str], Any | None]:
        normalized_api_url = _normalize_api_url(api_url)
        try:
            client = IrisApiClient(self.hass, normalized_api_url, auth_token=_normalize_token(auth_token) or None)
            bootstrap = await client.async_get_bootstrap()
            validate_bootstrap_compatibility(bootstrap)
        except IrisCompatibilityError as exc:
            return {"base": exc.code}, None
        except IrisProtocolError:
            return {"base": "invalid_bootstrap"}, None
        except IrisAuthenticationError:
            return {"base": "invalid_auth"}, None
        except IrisConnectionError:
            return {"base": "cannot_connect"}, None
        return {}, bootstrap

    def _resolve_existing_entry(self, entry_data: Mapping[str, Any] | None = None) -> ConfigEntry | None:
        entry_id = self.context.get("entry_id")
        if isinstance(entry_id, str):
            return self.hass.config_entries.async_get_entry(entry_id)

        unique_id = self.context.get("unique_id")
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if unique_id is not None and entry.unique_id == unique_id:
                return entry

        if entry_data is None:
            return None

        instance_id = entry_data.get(CONF_INSTANCE_ID)
        api_url = entry_data.get(CONF_API_URL)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if instance_id is not None and _entry_instance_id(entry) == instance_id:
                return entry
            if api_url is not None and entry.data.get(CONF_API_URL) == api_url:
                return entry
        return None

    @staticmethod
    def _build_user_schema(*, default_api_url: str, include_token: bool = True) -> vol.Schema:
        fields: dict[Any, Any] = {
            vol.Required(CONF_API_URL, default=default_api_url): str,
        }
        if include_token:
            fields[vol.Optional(CONF_TOKEN, default="")] = str
        return vol.Schema(fields)


def _parse_discovery_info(discovery_info: ZeroconfServiceInfo) -> IrisDiscoveryContext:
    instance_id = _property_as_str(discovery_info.properties, "instance_id")
    if not instance_id:
        raise ValueError("Discovery payload must include instance_id.")

    api_port = _property_as_int(discovery_info.properties, "api_port") or discovery_info.port
    if api_port is None:
        raise ValueError("Discovery payload must include api_port.")

    display_name = _property_as_str(discovery_info.properties, "display_name") or discovery_info.name.split(".")[0]
    return IrisDiscoveryContext(
        api_url=f"http://{discovery_info.host}:{api_port}",
        instance_id=instance_id,
        display_name=display_name,
        requires_auth=_property_as_bool(discovery_info.properties, "requires_auth"),
    )


def _property_as_str(properties: Mapping[str, Any], key: str) -> str | None:
    raw = properties.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    if isinstance(raw, str):
        return raw
    return str(raw)


def _property_as_int(properties: Mapping[str, Any], key: str) -> int | None:
    raw = _property_as_str(properties, key)
    if raw is None or raw == "":
        return None
    return int(raw)


def _property_as_bool(properties: Mapping[str, Any], key: str) -> bool:
    raw = _property_as_str(properties, key)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_api_url(api_url: str) -> str:
    return api_url.rstrip("/")


def _normalize_token(token: str | None) -> str:
    return (token or "").strip()


def _entry_instance_id(entry: ConfigEntry) -> str | None:
    return entry.unique_id or entry.data.get(CONF_INSTANCE_ID)
