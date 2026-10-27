"""Smoke test: set up a config entry with a mocked portal and check key entities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vag_data_act.api import Dataset, DatasetInfo
from custom_components.vag_data_act.const import DOMAIN

FIXTURE = (
    Path(__file__).parent
    / "fixtures/raw/20261027200113_VSSZZZKRXSA000001/VSSZZZKRXSA000001_20261027200113.json"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_setup_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tavascan",
        unique_id="VSSZZZKRXSA000001",
        data={
            "email": "me@example.com",
            "password": "pw",
            "brand": "CUPRA",
            "country": "de",
            "language": "de",
            "vin": "VSSZZZKRXSA000001",
            "nickname": "Tavascan",
        },
        options={"scan_interval": 15},
    )
    entry.add_to_hass(hass)
    content = FIXTURE.read_bytes()
    with (
        patch("custom_components.vag_data_act.api.PortalClient.async_login"),
        patch(
            "custom_components.vag_data_act.api.PortalClient.async_get_identifier",
            return_value="ID-1",
        ),
        patch(
            "custom_components.vag_data_act.api.PortalClient.async_list_datasets",
            return_value=[
                DatasetInfo(
                    "20261027200113_VSSZZZKRXSA000001.zip",
                    datetime(2026, 10, 27, 20, 1, 13, tzinfo=UTC),
                    1,
                )
            ],
        ),
        patch(
            "custom_components.vag_data_act.api.PortalClient.async_download_dataset",
            return_value=Dataset(
                "20261027200113_VSSZZZKRXSA000001.zip", "inner.json", content, "a" * 64, 1
            ),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.tavascan_state_of_charge").state == "23"
    assert hass.states.get("sensor.tavascan_odometer").state == "10044"
    assert hass.states.get("sensor.tavascan_login_status").state == "ok"
    assert hass.states.get("sensor.tavascan_remaining_charging_time").state == "unknown"
    assert hass.states.get("sensor.tavascan_climatisation_state").state == "unknown"
    assert hass.states.get("sensor.tavascan_ambiguous_fields").state == "2"
    assert hass.states.get("binary_sensor.tavascan_battery_care_mode_active").state == "on"
    assert hass.states.get("binary_sensor.tavascan_locked").state == "off"
    soc = hass.states.get("sensor.tavascan_state_of_charge")
    assert soc.attributes["source_key"] == "506cb83e-f99f-3af3-bbeb-0429b69a78d9"
    assert (
        hass.states.get("sensor.tavascan_last_vehicle_report").state == "2026-10-27T17:46:51+00:00"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
