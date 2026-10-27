"""Tests for the meter sensors, availability and reconnects."""

import copy
from datetime import timedelta
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tibber_pulse_local.const import DOMAIN
from custom_components.tibber_pulse_local.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.util.dt as dt_util

from .conftest import (  # noqa: TID251
    DEVICE_ID,
    EUID,
    READING,
    STREAM_TOKEN,
    FakeBridge,
    setup_entry,
    wait_for,
)


def _entity_id(hass: HomeAssistant, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{EUID}_{key}")


async def test_entities_for_reported_fields(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """Only the fields the meter fills in get sensors, with converted units."""
    await setup_entry(hass, config_entry)

    energy = hass.states.get(_entity_id(hass, "energy_import"))
    assert energy is not None
    assert float(energy.state) == 2282.95
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"
    assert float(hass.states.get(_entity_id(hass, "energy_export")).state) == 2.53
    assert float(hass.states.get(_entity_id(hass, "voltage_l1")).state) == 231.0
    assert float(hass.states.get(_entity_id(hass, "current_l3")).state) == 0.0

    # The Addax reports no power, frequency or reactive values: no entities for them
    for key in (
        "power",
        "power_import",
        "power_l1",
        "frequency",
        "reactive_energy_import",
    ):
        assert _entity_id(hass, key) is None

    devices = dr.async_get(hass)
    meter = devices.async_get_device_by_identifier(
        (DOMAIN, EUID), config_entry.entry_id
    )
    assert meter is not None
    assert meter.name == "Unknown P1 66AA"
    bridge_device = devices.async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), config_entry.entry_id
    )
    assert bridge_device is not None
    assert meter.via_device_id == bridge_device.id
    assert bridge_device.sw_version == "1856-0a3bd598"


async def test_fields_appearing_later(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """A field the meter starts to report gets its sensor then."""
    await setup_entry(hass, config_entry)
    assert _entity_id(hass, "power") is None

    reading = copy.deepcopy(READING)
    reading.update(p_import_w=1500.0, p_export_w=0.0, frequency_hz=50.01)
    await bridge.push(reading)
    await hass.async_block_till_done()

    assert float(hass.states.get(_entity_id(hass, "power")).state) == 1500.0
    assert float(hass.states.get(_entity_id(hass, "power_import")).state) == 1500.0
    assert float(hass.states.get(_entity_id(hass, "frequency")).state) == 50.01


async def test_values_follow_readings(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """Each pushed reading updates the sensors; a field turning null is unavailable."""
    await setup_entry(hass, config_entry)
    reading = copy.deepcopy(READING)
    reading.update(e_import_wh=2283000, voltage_v=[None, 0.0, 0.0])
    await bridge.push(reading)
    await hass.async_block_till_done()
    assert float(hass.states.get(_entity_id(hass, "energy_import")).state) == 2283.0
    assert hass.states.get(_entity_id(hass, "voltage_l1")).state == STATE_UNAVAILABLE


async def test_stale_meter_unavailable(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """No reading for three intervals (min 60 s) makes the meter unavailable."""
    await setup_entry(hass, config_entry)
    entity_id = _entity_id(hass, "energy_import")
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    meter = config_entry.runtime_data.meters[EUID]
    with patch(
        "custom_components.tibber_pulse_local.bridge.time.monotonic",
        return_value=meter.received + 61,
    ):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
        await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await bridge.push(READING)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_reconnect_after_kick(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """Closed by the bridge, the client goes unavailable and reconnects."""
    await setup_entry(hass, config_entry)
    entity_id = _entity_id(hass, "energy_import")
    connections = bridge.connections

    bridge.readings = []
    await bridge.kick()
    await wait_for(lambda: not config_entry.runtime_data.connected)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await wait_for(
        lambda: bridge.connections > connections and config_entry.runtime_data.connected
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_password_refused_while_running(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """A password the bridge stops accepting starts a re-auth flow."""
    await setup_entry(hass, config_entry)
    bridge.password = "NEW1-PASS"
    await bridge.kick()
    await wait_for(
        lambda: any(
            flow["context"]["source"] == SOURCE_REAUTH
            for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        )
    )


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """An unreachable bridge retries setup later."""
    await bridge.server.close()
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """Unloading stops the stream."""
    await setup_entry(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    await wait_for(lambda: all(ws.closed for ws in bridge.sockets))


async def test_diagnostics(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """Diagnostics carry the readings but not the password or address."""
    await setup_entry(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["entry"]["password"] == "**REDACTED**"
    assert diagnostics["entry"]["host"] == "**REDACTED**"
    assert diagnostics["connected"] is True
    assert diagnostics["meters"][EUID]["reading"]["e_import_wh"] == 2282950


async def test_stream_token(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A stream token streams readings, without the pages only the password opens."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=bridge.host,
        data={CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN},
    )
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.status is None
    assert float(hass.states.get(_entity_id(hass, "voltage_l1")).state) == 231.0
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"]["api_token"] == "**REDACTED**"


async def test_token_removed_while_running(
    hass: HomeAssistant, bridge: FakeBridge
) -> None:
    """A token removed on the bridge starts a re-auth flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=bridge.host,
        data={CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN},
    )
    await setup_entry(hass, entry)
    del bridge.tokens[STREAM_TOKEN]
    await bridge.kick()
    await wait_for(
        lambda: any(
            flow["context"]["source"] == SOURCE_REAUTH
            for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        )
    )
