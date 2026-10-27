"""The Tibber Pulse (local) integration: meter readings from a Tibber bridge's /ws stream."""

from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .bridge import TibberPulseBridge, TibberPulseConfigEntry
from .client import TibberPulseAuthError, TibberPulseConnectionError
from .const import BRIDGE_MODEL, DOMAIN, MANUFACTURER

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TibberPulseConfigEntry) -> bool:
    """Set up a bridge from a config entry."""
    bridge = TibberPulseBridge(
        hass,
        entry,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PASSWORD),
        entry.data.get(CONF_API_TOKEN),
        entry.unique_id or entry.entry_id,
    )
    try:
        await bridge.client.async_validate()
        bridge.status = await bridge.client.async_get_status()
    except TibberPulseAuthError as err:
        raise ConfigEntryAuthFailed(
            "The bridge refused the password or API token"
        ) from err
    except TibberPulseConnectionError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to {entry.data[CONF_HOST]}: {err}"
        ) from err

    firmware = (bridge.status or {}).get("firmware") or {}
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, bridge.bridge_id)},
        manufacturer=MANUFACTURER,
        model=BRIDGE_MODEL,
        name=entry.title,
        sw_version=firmware.get("esp"),
        configuration_url=bridge.client.base_url,
    )

    entry.runtime_data = bridge
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    bridge.async_start()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TibberPulseConfigEntry
) -> bool:
    """Unload a config entry; its background task ends with it."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
