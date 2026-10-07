"""Sensors for the meters behind a Tibber bridge."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bridge import TibberPulseBridge, TibberPulseConfigEntry
from .const import DOMAIN, MANUFACTURER, signal_new_meter, signal_update

# Readings are pushed; nothing to poll, and every entity of a meter updates together
PARALLEL_UPDATES = 0


def _field(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda data: data.get(key)


def _phase(key: str, phase: int) -> Callable[[dict[str, Any]], Any]:
    def value(data: dict[str, Any]) -> Any:
        values = data.get(key)
        if isinstance(values, list) and len(values) > phase:
            return values[phase]
        return None

    return value


def _scaled(key: str, factor: float) -> Callable[[dict[str, Any]], Any]:
    def value(data: dict[str, Any]) -> Any:
        raw = data.get(key)
        return raw * factor if isinstance(raw, int | float) else None

    return value


def _net_power(data: dict[str, Any]) -> float | None:
    imported = data.get("p_import_w")
    exported = data.get("p_export_w")
    if imported is None and exported is None:
        return None
    return (imported or 0.0) - (exported or 0.0)


@dataclass(frozen=True, kw_only=True)
class TibberPulseSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor fed from a meter reading."""

    value_fn: Callable[[dict[str, Any]], Any]


def _phases(
    key: str,
    field: str,
    device_class: SensorDeviceClass,
    unit: str,
) -> list[TibberPulseSensorEntityDescription]:
    return [
        TibberPulseSensorEntityDescription(
            key=f"{key}_l{phase + 1}",
            translation_key=f"{key}_phase",
            translation_placeholders={"phase": f"L{phase + 1}"},
            device_class=device_class,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=unit,
            value_fn=_phase(field, phase),
        )
        for phase in range(3)
    ]


SENSORS: tuple[TibberPulseSensorEntityDescription, ...] = (
    TibberPulseSensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=_net_power,
    ),
    TibberPulseSensorEntityDescription(
        key="power_import",
        translation_key="power_import",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=_field("p_import_w"),
    ),
    TibberPulseSensorEntityDescription(
        key="power_export",
        translation_key="power_export",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=_field("p_export_w"),
    ),
    *_phases("power", "p_phase_w", SensorDeviceClass.POWER, UnitOfPower.WATT),
    *_phases(
        "voltage", "voltage_v", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT
    ),
    *_phases(
        "current", "current_a", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE
    ),
    TibberPulseSensorEntityDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        value_fn=_field("frequency_hz"),
    ),
    TibberPulseSensorEntityDescription(
        key="reactive_power_import",
        translation_key="reactive_power_import",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        value_fn=_field("q_import_var"),
        entity_registry_enabled_default=False,
    ),
    TibberPulseSensorEntityDescription(
        key="reactive_power_export",
        translation_key="reactive_power_export",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        value_fn=_field("q_export_var"),
        entity_registry_enabled_default=False,
    ),
    TibberPulseSensorEntityDescription(
        key="energy_import",
        translation_key="energy_import",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_scaled("e_import_wh", 0.001),
    ),
    TibberPulseSensorEntityDescription(
        key="energy_export",
        translation_key="energy_export",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_scaled("e_export_wh", 0.001),
    ),
    TibberPulseSensorEntityDescription(
        key="reactive_energy_import",
        translation_key="reactive_energy_import",
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        suggested_display_precision=2,
        value_fn=_scaled("eq_import_varh", 0.001),
        entity_registry_enabled_default=False,
    ),
    TibberPulseSensorEntityDescription(
        key="reactive_energy_export",
        translation_key="reactive_energy_export",
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        suggested_display_precision=2,
        value_fn=_scaled("eq_export_varh", 0.001),
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberPulseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors as meters report: only for the fields each meter fills in."""
    bridge = entry.runtime_data
    created: dict[str, set[str]] = {}

    @callback
    def _async_meter(euid: str) -> None:
        meter = bridge.meters.get(euid)
        if meter is None:
            return
        keys = created.setdefault(euid, set())
        new = [
            description
            for description in SENSORS
            if description.key not in keys
            and description.value_fn(meter.data) is not None
        ]
        if not new:
            return
        keys.update(description.key for description in new)
        async_add_entities(
            TibberPulseSensor(bridge, euid, description) for description in new
        )

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_meter(entry.entry_id), _async_meter)
    )
    for euid in bridge.meters:
        _async_meter(euid)


def meter_device_info(bridge: TibberPulseBridge, euid: str) -> DeviceInfo:
    """Return the device of a meter, from what its latest reading says about it."""
    data = bridge.meters[euid].data
    meter_type = data.get("meter_type")
    model = meter_type or data.get("model")
    tail = euid[-4:].upper()
    name = f"{meter_type} {tail}" if meter_type else f"Meter {tail}"
    if euid == "0" * 16:
        name = f"{meter_type} (P1)" if meter_type else "P1 meter"
    return DeviceInfo(
        identifiers={(DOMAIN, euid)},
        name=name,
        manufacturer=data.get("meter_brand") or MANUFACTURER,
        model=model,
        serial_number=data.get("meter_id"),
        via_device=(DOMAIN, bridge.bridge_id),
    )


class TibberPulseSensor(SensorEntity):
    """A value from a meter's latest reading."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: TibberPulseSensorEntityDescription

    def __init__(
        self,
        bridge: TibberPulseBridge,
        euid: str,
        description: TibberPulseSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._bridge = bridge
        self._euid = euid
        self._attr_unique_id = f"{euid}_{description.key}"
        self._attr_device_info = meter_device_info(bridge, euid)

    @property
    def available(self) -> bool:
        """Return whether the meter reports this value right now."""
        return (
            self._bridge.meter_available(self._euid) and self.native_value is not None
        )

    @property
    def native_value(self) -> Any:
        """Return the value from the latest reading."""
        meter = self._bridge.meters.get(self._euid)
        return self.entity_description.value_fn(meter.data) if meter else None

    async def async_added_to_hass(self) -> None:
        """Follow the meter's readings."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._bridge.entry.entry_id, self._euid),
                self.async_write_ha_state,
            )
        )
