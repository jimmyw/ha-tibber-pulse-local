"""Diagnostics for Tibber Pulse (local)."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .bridge import TibberPulseConfigEntry

TO_REDACT = {
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_PASSWORD,
    "meter_id",
    "ip",
    "ssid",
    "bssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TibberPulseConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = entry.runtime_data
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "connected": bridge.connected,
        "status": async_redact_data(bridge.status or {}, TO_REDACT),
        "meters": {
            euid: {
                "available": meter.available,
                "reading": async_redact_data(meter.data, TO_REDACT),
            }
            for euid, meter in bridge.meters.items()
        },
    }
