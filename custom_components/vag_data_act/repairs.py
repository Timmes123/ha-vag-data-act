"""Repairs: consent_required is fixable by confirming after the portal visit."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ISSUE_CONSENT_REQUIRED


class ConsentRepairFlow(RepairsFlow):
    """Ask the user to confirm the portal consent, then refresh."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry is not None and hasattr(entry, "runtime_data"):
                await entry.runtime_data.async_request_refresh()
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    if issue_id.startswith(ISSUE_CONSENT_REQUIRED) and data and "entry_id" in data:
        return ConsentRepairFlow(data["entry_id"])
    raise ValueError(f"{DOMAIN}: no fix flow for {issue_id}")
