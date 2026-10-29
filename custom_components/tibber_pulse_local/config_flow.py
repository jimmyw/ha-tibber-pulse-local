"""Config flow for Tibber Pulse (local)."""

from collections.abc import Mapping
import re
from typing import Any

import voluptuous as vol  # noqa: TID251  # probatio is too new for older cores

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_MODEL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import TibberPulseAuthError, TibberPulseClient, TibberPulseConnectionError
from .const import (
    BRIDGE_MODEL,
    DOMAIN,
    LOGGER,
    ZEROCONF_PRODUCTS,
    ZEROCONF_PULSE_MODELS,
    ZEROCONF_PULSE_TYPE,
)


# The web password or an API token: exactly one of them
CREDENTIALS_SCHEMA = vol.Schema(
    {vol.Optional(CONF_PASSWORD): str, vol.Optional(CONF_API_TOKEN): str}
)


def _user_schema(host: str | None = None) -> vol.Schema:
    return vol.Schema(
        {vol.Required(CONF_HOST, default=host or vol.UNDEFINED): str}
    ).extend(CREDENTIALS_SCHEMA.schema)


def _credentials(user_input: dict[str, Any]) -> dict[str, str] | None:
    """Return the one credential entered, as entry data; None for none or both."""
    entered = {
        key: value.strip()
        for key in (CONF_PASSWORD, CONF_API_TOKEN)
        if (value := user_input.get(key, "")).strip()
    }
    return entered if len(entered) == 1 else None


class TibberPulseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Tibber bridge by host, and its web password or an API token."""

    VERSION = 1

    _host: str | None = None
    _discovered_id: str | None = None
    _model: str = BRIDGE_MODEL

    async def _async_try(
        self, host: str, credentials: dict[str, str] | None
    ) -> tuple[str | None, dict[str, str]]:
        """Return the bridge's device id (None when it does not tell) and errors."""
        if credentials is None:
            return None, {"base": "credentials"}
        client = TibberPulseClient(
            async_get_clientsession(self.hass),
            host,
            credentials.get(CONF_PASSWORD),
            on_reading=lambda _: None,
            api_token=credentials.get(CONF_API_TOKEN),
        )
        try:
            await client.async_validate()
            return await client.async_get_device_id(), {}
        except TibberPulseAuthError:
            return None, {"base": "invalid_auth"}
        except TibberPulseConnectionError:
            return None, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error validating %s", host)
            return None, {"base": "unknown"}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            credentials = _credentials(user_input)
            device_id, errors = await self._async_try(host, credentials)
            if not errors:
                await self.async_set_unique_id(device_id or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=f"Tibber Bridge {device_id or host}",
                    data={CONF_HOST: host, **credentials},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(self._host), user_input
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a bridge found over mDNS, by its stream service or its web server."""
        host = str(discovery_info.ip_address)
        self.context[CONF_HOST] = host
        if discovery_info.type == ZEROCONF_PULSE_TYPE:
            return await self._async_step_zeroconf_pulse(discovery_info, host)
        # Newer firmware advertises both: its stream service tells the device id
        for flow in self._async_in_progress(include_uninitialized=True):
            if (
                flow["context"].get(CONF_HOST) == host
                and flow["context"].get("zeroconf_type") == ZEROCONF_PULSE_TYPE
            ):
                return self.async_abort(reason="already_in_progress")
        service = discovery_info.name.lower()
        product = next(
            (p for p in ZEROCONF_PRODUCTS if service.startswith(p.service_prefix)),
            ZEROCONF_PRODUCTS[0],
        )
        self._model = product.model
        hostname = (
            discovery_info.hostname.lower().removesuffix(".").removesuffix(".local")
        )
        # The default host name carries the last 8 hex digits of the device id, the
        # unique id. The host name is a setting, though: a renamed bridge is known by
        # its address until it tells its device id.
        suffix = hostname.removeprefix(product.host_prefix)
        if hostname.startswith(product.host_prefix) and re.fullmatch(
            "[0-9a-f]{8}", suffix
        ):
            for entry in self._async_current_entries(include_ignore=True):
                if entry.unique_id and entry.unique_id.endswith(suffix):
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_HOST: host, CONF_MODEL: self._model},
                    )
                    return self.async_abort(reason="already_configured")
            self._discovered_id = suffix
        else:
            self._async_abort_entries_match({CONF_HOST: host})
            self._discovered_id = host
        await self.async_set_unique_id(self._discovered_id)
        self._abort_if_unique_id_configured()
        return await self._async_discovered(host)

    async def _async_step_zeroconf_pulse(
        self, discovery_info: ZeroconfServiceInfo, host: str
    ) -> ConfigFlowResult:
        """Handle a bridge found by its stream service, which tells its device id."""
        device_id = str(discovery_info.properties.get("id") or "").lower()
        if not re.fullmatch("[0-9a-f]+", device_id):
            return self.async_abort(reason="not_tibber_bridge")
        self.context["zeroconf_type"] = ZEROCONF_PULSE_TYPE
        self._model = ZEROCONF_PULSE_MODELS.get(
            str(discovery_info.properties.get("model")), BRIDGE_MODEL
        )
        # Entries discovered before keep the id they were found by: the host name's
        # last 8 hex digits, or the address of a renamed bridge
        for entry in self._async_current_entries(include_ignore=True):
            if entry.unique_id in (device_id, device_id[-8:], host):
                self.hass.config_entries.async_update_entry(
                    entry,
                    unique_id=device_id,
                    data={**entry.data, CONF_HOST: host, CONF_MODEL: self._model},
                )
                return self.async_abort(reason="already_configured")
        # The same bridge found by its web server first
        for flow in self._async_in_progress(include_uninitialized=True):
            if flow["context"].get(CONF_HOST) == host:
                self.hass.config_entries.flow.async_abort(flow["flow_id"])
        self._discovered_id = device_id
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host, CONF_MODEL: self._model}
        )
        return await self._async_discovered(host)

    async def _async_discovered(self, host: str) -> ConfigFlowResult:
        self._host = host
        self.context["title_placeholders"] = {
            "name": f"{self._model} {self._discovered_id}"
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password or an API token of a discovered bridge."""
        assert self._host is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = _credentials(user_input)
            device_id, errors = await self._async_try(self._host, credentials)
            if not errors:
                # Replace the placeholder unique id with the full device id
                await self.async_set_unique_id(
                    device_id or self._discovered_id, raise_on_progress=False
                )
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: self._host, CONF_MODEL: self._model}
                )
                return self.async_create_entry(
                    title=f"{self._model} {device_id or self._discovered_id}",
                    data={
                        CONF_HOST: self._host,
                        CONF_MODEL: self._model,
                        **credentials,
                    },
                )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            description_placeholders={"host": self._host, "model": self._model},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a password or API token the bridge no longer accepts."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password or API token, either may replace the other."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = _credentials(user_input)
            _, errors = await self._async_try(entry.data[CONF_HOST], credentials)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={CONF_HOST: entry.data[CONF_HOST], **credentials}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
