"""Constants for the Tibber Pulse (local) integration."""

import logging

DOMAIN = "tibber_pulse_local"
LOGGER = logging.getLogger(__package__)

MANUFACTURER = "Tibber"
BRIDGE_MODEL = "Tibber Bridge"
# The bridge's mDNS host name is "Bridge" plus the last 8 hex digits of its device id
ZEROCONF_HOST_PREFIX = "bridge"

# A meter is unavailable when no reading came for this many reading intervals,
# and never sooner than STALE_MIN_SECONDS
STALE_INTERVALS = 3
STALE_MIN_SECONDS = 60
# How often availability is re-evaluated between readings
AVAILABILITY_CHECK_SECONDS = 30


def signal_new_meter(entry_id: str) -> str:
    """Dispatcher signal: a reading came from a meter, possibly with new fields."""
    return f"{DOMAIN}_{entry_id}_meter"


def signal_update(entry_id: str, euid: str) -> str:
    """Dispatcher signal: a meter's reading or availability changed."""
    return f"{DOMAIN}_{entry_id}_update_{euid}"
