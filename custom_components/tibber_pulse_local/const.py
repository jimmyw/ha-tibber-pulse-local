"""Constants for the Tibber Pulse (local) integration."""

from dataclasses import dataclass
import logging

DOMAIN = "tibber_pulse_local"
LOGGER = logging.getLogger(__package__)

MANUFACTURER = "Tibber"
BRIDGE_MODEL = "Tibber Bridge"
P1_MODEL = "Pulse P1"


@dataclass(frozen=True, slots=True)
class ZeroconfProduct:
    """A product found by the name of the web server it advertises over mDNS."""

    service_prefix: str  # Of the lower-case service instance name
    host_prefix: str  # Of the default host name, before 8 hex digits of the device id
    model: str


# The meter stream's own service, found whatever the host or service name. Its TXT record
# carries the device id ("id") and the product ("model": "bridge" or "p1").
ZEROCONF_PULSE_TYPE = "_tibber-pulse._tcp.local."
ZEROCONF_PULSE_MODELS = {"bridge": BRIDGE_MODEL, "p1": P1_MODEL}

# Firmware without that service is found by its web server. Same firmware, built for each
# product: the manifest matches both service names.
ZEROCONF_PRODUCTS = (
    ZeroconfProduct("tibber bridge", "bridge", BRIDGE_MODEL),
    ZeroconfProduct("pulse p1", "pulse", P1_MODEL),
)

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
