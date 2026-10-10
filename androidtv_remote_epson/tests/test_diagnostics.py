"""Tests for the diagnostics data provided by the Android TV Remote integration."""

from unittest.mock import MagicMock

from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics."""
    mock_api.is_on = True
    mock_api.current_app = "some app"
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert (
        await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)
        == snapshot
    )
