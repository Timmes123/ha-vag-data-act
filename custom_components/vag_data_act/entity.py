"""Shared entity base: values stay visible, age makes staleness visible."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_VIN, DOMAIN
from .coordinator import VagDataActCoordinator, VehicleData
from .parser import SlotValue


class VagDataActEntity(CoordinatorEntity[VagDataActCoordinator]):
    """Base entity bound to one VIN."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VagDataActCoordinator, key: str) -> None:
        super().__init__(coordinator)
        vin = coordinator.config_entry.data[CONF_VIN]
        self._attr_unique_id = f"{vin}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, vin)})

    @property
    def available(self) -> bool:
        # Never hide values behind "unavailable": stale data stays visible and the
        # data_age / login_status entities show the health.
        return True

    @property
    def data(self) -> VehicleData:
        return self.coordinator.data

    def slot(self, name: str) -> SlotValue | None:
        parsed = self.data.parsed
        return parsed.values.get(name) if parsed else None

    def slot_attributes(self, name: str) -> dict[str, Any]:
        sv = self.slot(name)
        attrs: dict[str, Any] = {
            "source_key": sv.key if sv else None,
            "source_field": sv.field if sv else None,
            "car_captured_at": self.data.last_vehicle_report,
            "age_minutes": self.data.data_age_minutes(),
        }
        if sv:
            attrs["status"] = sv.status
            attrs["raw_value"] = sv.raw
            if sv.candidates:
                attrs["candidates"] = dict(sv.candidates)
        return attrs
