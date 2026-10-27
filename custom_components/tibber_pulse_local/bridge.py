"""The bridge connection and the latest reading of each meter behind it."""

from dataclasses import dataclass
from datetime import timedelta
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .client import Reading, TibberPulseClient
from .const import (
    AVAILABILITY_CHECK_SECONDS,
    LOGGER,
    STALE_INTERVALS,
    STALE_MIN_SECONDS,
    signal_new_meter,
    signal_update,
)

type TibberPulseConfigEntry = ConfigEntry[TibberPulseBridge]


@dataclass
class MeterState:
    """The latest reading from one meter."""

    euid: str
    data: dict[str, Any]
    received: float  # monotonic
    available: bool = True

    @property
    def stale_after(self) -> float:
        """Return seconds without a reading after which the meter is unavailable."""
        interval_ms = self.data.get("data_interval_ms")
        interval = interval_ms / 1000 if isinstance(interval_ms, int | float) else 0
        return max(STALE_MIN_SECONDS, STALE_INTERVALS * interval)


class TibberPulseBridge:
    """Runs the /ws stream for a config entry and fans readings out to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TibberPulseConfigEntry,
        host: str,
        password: str | None,
        api_token: str | None,
        bridge_id: str,
    ) -> None:
        """Initialize the bridge."""
        self.hass = hass
        self.entry = entry
        self.bridge_id = bridge_id
        self.meters: dict[str, MeterState] = {}
        self.status: dict[str, Any] | None = None
        self.client = TibberPulseClient(
            async_get_clientsession(hass),
            host,
            password,
            on_reading=self._on_reading,
            on_connection=self._on_connection,
            on_auth_failed=self._on_auth_failed,
            api_token=api_token,
        )
        self._unsub_check: CALLBACK_TYPE | None = None

    @property
    def connected(self) -> bool:
        """Return whether the stream is up."""
        return self.client.connected

    @callback
    def async_start(self) -> None:
        """Start streaming; stopped with the entry."""
        self.entry.async_create_background_task(
            self.hass, self.client.run(), f"tibber_pulse_local {self.bridge_id}"
        )
        self._unsub_check = async_track_time_interval(
            self.hass,
            self._check_availability,
            timedelta(seconds=AVAILABILITY_CHECK_SECONDS),
        )
        self.entry.async_on_unload(self._async_stop_check)

    @callback
    def _async_stop_check(self) -> None:
        if self._unsub_check:
            self._unsub_check()
            self._unsub_check = None

    def meter_available(self, euid: str) -> bool:
        """Return whether a meter has a recent reading over a live stream."""
        meter = self.meters.get(euid)
        return self.connected and meter is not None and meter.available

    @callback
    def _on_reading(self, reading: Reading) -> None:
        meter = self.meters.get(reading.euid)
        if meter is None:
            LOGGER.debug("First reading from meter %s", reading.euid)
            meter = self.meters[reading.euid] = MeterState(
                reading.euid, reading.data, time.monotonic()
            )
        else:
            meter.data = reading.data
            meter.received = time.monotonic()
            meter.available = True
        # The platform creates entities for fields it has not seen yet, then entities update
        async_dispatcher_send(
            self.hass, signal_new_meter(self.entry.entry_id), reading.euid
        )
        async_dispatcher_send(
            self.hass, signal_update(self.entry.entry_id, reading.euid)
        )

    @callback
    def _on_connection(self, connected: bool) -> None:
        LOGGER.debug("Stream %s", "up" if connected else "down")
        for euid in self.meters:
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id, euid))

    @callback
    def _on_auth_failed(self) -> None:
        self.entry.async_start_reauth(self.hass)

    @callback
    def _check_availability(self, _now: Any = None) -> None:
        now = time.monotonic()
        for meter in self.meters.values():
            available = now - meter.received <= meter.stale_after
            if available != meter.available:
                meter.available = available
                LOGGER.debug(
                    "Meter %s %s", meter.euid, "back" if available else "stale"
                )
                async_dispatcher_send(
                    self.hass, signal_update(self.entry.entry_id, meter.euid)
                )
