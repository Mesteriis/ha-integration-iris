from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bootstrap import IrisBootstrap, IrisBootstrapError, parse_bootstrap_payload
from .catalog import IrisCatalogError, parse_catalog_payload, parse_dashboard_payload
from .const import HA_BOOTSTRAP_PATH, HA_CATALOG_PATH, HA_DASHBOARD_PATH, HA_STATE_PATH, REQUEST_TIMEOUT


class IrisClientError(RuntimeError):
    """Base HTTP client error for the IRIS integration."""


class IrisConnectionError(IrisClientError):
    """Raised when the integration cannot reach the IRIS backend."""


class IrisAuthenticationError(IrisClientError):
    """Raised when the backend rejects the integration credentials."""


class IrisProtocolError(IrisClientError):
    """Raised when the backend responds with an invalid protocol payload."""


class IrisApiClient:
    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        *,
        auth_token: str | None = None,
        session: ClientSession | None = None,
    ) -> None:
        self._hass = hass
        self._base_url = api_url.rstrip("/")
        self._auth_token = auth_token
        self._session = session

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def session(self) -> ClientSession:
        return self._session or async_get_clientsession(self._hass)

    @property
    def headers(self) -> dict[str, str]:
        if not self._auth_token:
            return {}
        return {"Authorization": f"Bearer {self._auth_token}"}

    async def async_get_bootstrap(self) -> IrisBootstrap:
        payload = await self._async_get_json(self._resolve_url(HA_BOOTSTRAP_PATH))
        try:
            return parse_bootstrap_payload(payload, base_url=f"{self._base_url}/")
        except IrisBootstrapError as exc:
            raise IrisProtocolError(str(exc)) from exc

    async def async_get_catalog(self, url: str | None = None) -> dict[str, Any]:
        payload = await self._async_get_json(url or self._resolve_url(HA_CATALOG_PATH))
        try:
            return parse_catalog_payload(payload)
        except IrisCatalogError as exc:
            raise IrisProtocolError(str(exc)) from exc

    async def async_get_dashboard(self, url: str | None = None) -> dict[str, Any]:
        payload = await self._async_get_json(url or self._resolve_url(HA_DASHBOARD_PATH))
        try:
            return parse_dashboard_payload(payload)
        except IrisCatalogError as exc:
            raise IrisProtocolError(str(exc)) from exc

    async def async_get_state(self, url: str | None = None) -> dict[str, Any]:
        payload = await self._async_get_json(url or self._resolve_url(HA_STATE_PATH))
        if not isinstance(payload, dict):
            raise IrisProtocolError("IRIS state response must be a JSON object.")
        return payload

    async def _async_get_json(self, url: str) -> Any:
        try:
            async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as response:
                if response.status in {401, 403}:
                    raise IrisAuthenticationError(f"IRIS rejected credentials for {url}.")
                response.raise_for_status()
                return await response.json()
        except IrisClientError:
            raise
        except (ClientError, TimeoutError, ValueError) as exc:
            raise IrisConnectionError(f"Unable to fetch IRIS resource {url}: {exc}") from exc

    def _resolve_url(self, path: str) -> str:
        return urljoin(f"{self._base_url}/", path)
