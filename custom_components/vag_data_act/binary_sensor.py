"""Binary sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VagDataActConfigEntry
from .coordinator import VehicleData
from .entity import VagDataActEntity


@dataclass(frozen=True, kw_only=True)
class VagBinaryDescription(BinarySensorEntityDescription):
    slot: str | None = None
    value_fn: Callable[[VehicleData], bool | None] | None = None
    invert: bool = False


def _bcam_active(data: VehicleData) -> bool | None:
    """Battery care mode is limiting: effective target < user target and == threshold."""
    parsed = data.parsed
    if not parsed:
        return None
    user, eff, bcam = (
        parsed.get("target_soc_user"),
        parsed.get("target_soc_effective"),
        parsed.get("bcam_threshold"),
    )
    if user is None or eff is None or bcam is None:
        return None
    return eff < user and eff == bcam


DESCRIPTIONS: tuple[VagBinaryDescription, ...] = (
    VagBinaryDescription(
        key="locked", slot="locked", device_class=BinarySensorDeviceClass.LOCK, invert=True
    ),
    VagBinaryDescription(key="open", slot="open", device_class=BinarySensorDeviceClass.OPENING),
    VagBinaryDescription(
        key="parking_light_left",
        slot="parking_light_left",
        device_class=BinarySensorDeviceClass.LIGHT,
    ),
    VagBinaryDescription(
        key="parking_light_right",
        slot="parking_light_right",
        device_class=BinarySensorDeviceClass.LIGHT,
    ),
    VagBinaryDescription(key="battery_care_mode_active", value_fn=_bcam_active),
    VagBinaryDescription(
        key="dataset_changed",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.dataset_changed,
    ),
)


class VagBinarySensor(VagDataActEntity, BinarySensorEntity):
    entity_description: VagBinaryDescription

    def __init__(self, coordinator, description: VagBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        d = self.entity_description
        if d.value_fn is not None:
            return d.value_fn(self.data)
        sv = self.slot(d.slot) if d.slot else None
        if sv is None or sv.value is None:
            return None
        return (not sv.value) if d.invert else bool(sv.value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self.entity_description
        if d.slot:
            return self.slot_attributes(d.slot)
        if d.key == "battery_care_mode_active":
            return {
                "car_captured_at": self.data.last_vehicle_report,
                "age_minutes": self.data.data_age_minutes(),
                "rule": "effective target < user target and effective == bcam threshold",
            }
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VagDataActConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(VagBinarySensor(entry.runtime_data, d) for d in DESCRIPTIONS)
