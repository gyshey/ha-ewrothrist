"""Sensors for the EW Rothrist Smart Meter integration.

The load profile arrives with a few hours of lag, so these sensors are
informational companions to the long-term statistics import (which is what
the Energy dashboard uses).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EwrConfigEntry
from .const import DOMAIN
from .coordinator import EwrCoordinator, EwrData


@dataclass(frozen=True, kw_only=True)
class EwrSensorDescription(SensorEntityDescription):
    """Sensor description with value extractor."""

    value_fn: Callable[[EwrData], float | datetime | None]


SENSORS: tuple[EwrSensorDescription, ...] = (
    EwrSensorDescription(
        key="last_power",
        translation_key="last_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=2,
        value_fn=lambda d: d.last_slot_kw,
    ),
    EwrSensorDescription(
        key="data_until",
        translation_key="data_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_slot_time,
    ),
    EwrSensorDescription(
        key="energy_today",
        translation_key="energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d: d.energy_today_kwh,
    ),
    EwrSensorDescription(
        key="energy_yesterday",
        translation_key="energy_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d: d.energy_yesterday_kwh,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EwrConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EwrSensor(coordinator, desc) for desc in SENSORS)


class EwrSensor(CoordinatorEntity[EwrCoordinator], SensorEntity):
    """A read-only value derived from the latest portal fetch."""

    _attr_has_entity_name = True
    entity_description: EwrSensorDescription

    def __init__(
        self, coordinator: EwrCoordinator, description: EwrSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.meter}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.meter)},
            name="EW Rothrist Smart Meter",
            manufacturer="EW Rothrist AG",
            model=coordinator.meter,
            configuration_url="https://www.ewrothrist.ch/de/services/lastgang.php",
        )

    @property
    def native_value(self) -> float | datetime | None:
        return self.entity_description.value_fn(self.coordinator.data)
