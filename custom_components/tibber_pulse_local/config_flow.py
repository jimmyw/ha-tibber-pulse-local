"""Config flow for Tibber Pulse (local)."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol  # noqa: TID251  # probatio is too new for older cores

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import TibberPulseAuthError, TibberPulseClient, TibberPulseConnectionError
from .const import DOMAIN, LOGGER, ZEROCONF_HOST_PREFIX


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
    _discovered_suffix: str | None = None

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
        """Handle a bridge found over mDNS (its web server, "Tibber Bridge Web Server")."""
        hostname = (
            discovery_info.hostname.lower().removesuffix(".").removesuffix(".local")
        )
        if not hostname.startswith(ZEROCONF_HOST_PREFIX):
            return self.async_abort(reason="not_tibber_bridge")
        # The host name carries the last 8 hex digits of the device id, the unique id
        suffix = hostname.removeprefix(ZEROCONF_HOST_PREFIX)
        host = str(discovery_info.ip_address)
        for entry in self._async_current_entries(include_ignore=True):
            if entry.unique_id and entry.unique_id.endswith(suffix):
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_HOST: host}
                )
                return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(suffix)
        self._abort_if_unique_id_configured()
        self._host = host
        self._discovered_suffix = suffix
        self.context["title_placeholders"] = {"name": f"Tibber Bridge {suffix}"}
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
                    device_id or self._discovered_suffix, raise_on_progress=False
                )
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                return self.async_create_entry(
                    title=f"Tibber Bridge {device_id or self._discovered_suffix}",
                    data={CONF_HOST: self._host, **credentials},
                )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            description_placeholders={"host": self._host},
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
