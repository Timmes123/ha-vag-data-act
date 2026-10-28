"""Sensor platform: vehicle values and health/diagnostic sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VagDataActConfigEntry
from .const import (
    LOGIN_STATUS_AUTH_FAILED,
    LOGIN_STATUS_CONSENT_REQUIRED,
    LOGIN_STATUS_OK,
    LOGIN_STATUS_PORTAL_ERROR,
    LOGIN_STATUS_UNKNOWN,
)
from .coordinator import VehicleData
from .entity import VagDataActEntity

# Exact charge states during which the remaining charging time is meaningful.
ACTIVE_CHARGE_STATES = frozenset({"CHARGE_STATE_CHARGING", "CHARGE_STATE_CONSERVATION_CHARGING"})


@dataclass(frozen=True, kw_only=True)
class SlotSensorDescription(SensorEntityDescription):
    """Sensor backed by one parser slot."""

    slot: str
    transform: Callable[[Any, VehicleData], Any] | None = None


def _remaining_charging(value: Any, data: VehicleData) -> Any:
    parsed = data.parsed
    state = parsed.get("charging_state") if parsed else None
    return value if state in ACTIVE_CHARGE_STATES else None


SLOT_SENSORS: tuple[SlotSensorDescription, ...] = (
    SlotSensorDescription(
        key="soc",
        slot="soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
    ),
    SlotSensorDescription(
        key="range",
        slot="range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SlotSensorDescription(
        key="odometer",
        slot="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SlotSensorDescription(
        key="target_soc_effective",
        slot="target_soc_effective",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
    ),
    SlotSensorDescription(
        key="target_soc_user",
        slot="target_soc_user",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
    ),
    SlotSensorDescription(
        key="bcam_threshold",
        slot="bcam_threshold",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
    ),
    SlotSensorDescription(key="charging_state", slot="charging_state"),
    SlotSensorDescription(key="charging_error_code", slot="charging_error_code"),
    SlotSensorDescription(key="charging_error_text", slot="charging_error_text"),
    SlotSensorDescription(
        key="charge_power",
        slot="charge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SlotSensorDescription(
        key="charge_rate",
        slot="charge_rate",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SlotSensorDescription(
        key="remaining_charging_time",
        slot="remaining_charging_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        transform=_remaining_charging,
    ),
    SlotSensorDescription(
        key="remaining_charging_time_bulk",
        slot="remaining_charging_time_bulk",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        transform=_remaining_charging,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="charge_bulk_threshold",
        slot="charge_bulk_threshold",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="charge_energy",
        slot="charge_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SlotSensorDescription(
        key="energy_content_current",
        slot="energy_content_current",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SlotSensorDescription(
        key="energy_content_max",
        slot="energy_content_max",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SlotSensorDescription(key="charge_mode", slot="charge_mode"),
    SlotSensorDescription(key="charge_type", slot="charge_type"),
    SlotSensorDescription(key="max_charge_current_ac", slot="max_charge_current_ac"),
    SlotSensorDescription(
        key="outdoor_temperature",
        slot="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SlotSensorDescription(
        key="battery_temperature_min",
        slot="battery_temperature_min",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SlotSensorDescription(
        key="battery_temperature_max",
        slot="battery_temperature_max",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SlotSensorDescription(key="climatisation_state", slot="climatisation_state"),
    SlotSensorDescription(
        key="remaining_climate_time",
        slot="remaining_climate_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    SlotSensorDescription(key="window_heating_state", slot="window_heating_state"),
    SlotSensorDescription(
        key="vehicle_time",
        slot="vehicle_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    # secondary / diagnostic values
    SlotSensorDescription(
        key="battery_level_hv",
        slot="battery_level_hv",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="charging_scenario", slot="charging_scenario", entity_category=EntityCategory.DIAGNOSTIC
    ),
    SlotSensorDescription(
        key="charge_mode_selection",
        slot="charge_mode_selection",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="auto_unlock_ac", slot="auto_unlock_ac", entity_category=EntityCategory.DIAGNOSTIC
    ),
    SlotSensorDescription(
        key="climatisation_target_temperature",
        slot="climatisation_target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="profile_vehicle_time",
        slot="profile_vehicle_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="timer_estimated_start",
        slot="timer_estimated_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SlotSensorDescription(
        key="timer_estimated_finish",
        slot="timer_estimated_finish",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class SlotSensor(VagDataActEntity, SensorEntity):
    """A sensor fed by one parser slot."""

    entity_description: SlotSensorDescription

    def __init__(self, coordinator, description: SlotSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        sv = self.slot(self.entity_description.slot)
        value = sv.value if sv else None
        if self.entity_description.transform is not None:
            value = self.entity_description.transform(value, self.data)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.slot_attributes(self.entity_description.slot)


@dataclass(frozen=True, kw_only=True)
class HealthSensorDescription(SensorEntityDescription):
    """Sensor computed from the coordinator state."""

    value_fn: Callable[[VehicleData], Any]
    attributes_fn: Callable[[VehicleData], dict[str, Any]] | None = None


def _ambiguities(data: VehicleData) -> dict[str, Any]:
    parsed = data.parsed
    if not parsed:
        return {"fields": []}
    return {
        "fields": [a.name for a in parsed.ambiguities],
        "details": [
            {"name": a.name, "field": a.field, "reason": a.reason, "candidates": a.candidates}
            for a in parsed.ambiguities
        ],
    }


def _unmapped(data: VehicleData) -> dict[str, Any]:
    parsed = data.parsed
    if not parsed:
        return {}
    return {
        "points": {p.key: {"field": p.field, "value": p.value} for p in parsed.unmapped},
        "report_metadata": parsed.metadata,
        "learned_keys": data.key_overrides,
    }


def _dataset_attrs(data: VehicleData) -> dict[str, Any]:
    return {
        "zip_name": data.dataset_name,
        "sha256": data.dataset_hash,
        "created_on": data.dataset_created_on,
        "datasets_listed": data.dataset_count,
        "points": data.parsed.point_count if data.parsed else None,
        "last_attempt": data.last_attempt,
        "last_error": data.last_error,
        "packages_processed_last_poll": data.packages_processed,
        "packages_pending": data.packages_pending,
        "packages_known": len(data.processed),
        "point_store_size": len(data.points),
        "data_request": data.request_metadata,
    }


HEALTH_SENSORS: tuple[HealthSensorDescription, ...] = (
    HealthSensorDescription(
        key="login_status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            LOGIN_STATUS_OK,
            LOGIN_STATUS_AUTH_FAILED,
            LOGIN_STATUS_CONSENT_REQUIRED,
            LOGIN_STATUS_PORTAL_ERROR,
            LOGIN_STATUS_UNKNOWN,
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.login_status,
        attributes_fn=lambda d: {"last_error": d.last_error, "last_attempt": d.last_attempt},
    ),
    HealthSensorDescription(
        key="last_successful_download",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_successful_download,
    ),
    HealthSensorDescription(
        key="last_vehicle_report",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_vehicle_report,
    ),
    HealthSensorDescription(
        key="data_age_minutes",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.data_age_minutes(),
    ),
    HealthSensorDescription(
        key="ambiguous_fields",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.parsed.ambiguities) if d.parsed else None,
        attributes_fn=_ambiguities,
    ),
    HealthSensorDescription(
        key="unmapped_points",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.parsed.unmapped) if d.parsed else None,
        attributes_fn=_unmapped,
    ),
    HealthSensorDescription(
        key="dataset",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.inner_name,
        attributes_fn=_dataset_attrs,
    ),
)


class HealthSensor(VagDataActEntity, SensorEntity):
    """Health / diagnostic sensor."""

    entity_description: HealthSensorDescription

    def __init__(self, coordinator, description: HealthSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.data)
        if isinstance(value, datetime) or value is None:
            return value
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attributes_fn
        return fn(self.data) if fn else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VagDataActConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [SlotSensor(coordinator, d) for d in SLOT_SENSORS]
    entities += [HealthSensor(coordinator, d) for d in HEALTH_SENSORS]
    async_add_entities(entities)
