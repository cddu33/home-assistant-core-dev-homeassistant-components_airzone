"""Tests for the unavailable grace period and the idle timeout option."""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, patch

from androidtvremote2 import remote as atv_remote
import pytest

from custom_components.androidtv_remote import idle_timeout
from custom_components.androidtv_remote.const import (
    CONF_IDLE_TIMEOUT,
    CONF_UNAVAILABLE_GRACE_PERIOD,
)
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

ENTITIES = ("media_player.my_android_tv", "remote.my_android_tv")


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, mock_api: MagicMock, **options: int
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_api._on_is_on_updated(True)
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_ON)


def _advance(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


async def test_reconnect_within_grace_period_never_unavailable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Disconnect/reconnect cycles shorter than the grace period are hidden."""
    await _setup(
        hass, mock_config_entry, mock_api, **{CONF_UNAVAILABLE_GRACE_PERIOD: 30}
    )

    states_written: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: states_written.append(event.data["new_state"].state),
    )

    for _ in range(5):
        mock_api._on_is_available_updated(False)
        _advance(hass, 20)
        await hass.async_block_till_done()
        mock_api._on_is_available_updated(True)
        await hass.async_block_till_done()

    # The timer of the last disconnect must be canceled by the reconnect.
    _advance(hass, 120)
    await hass.async_block_till_done()

    assert STATE_UNAVAILABLE not in states_written
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_ON)


async def test_unavailable_after_grace_period(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock
) -> None:
    """The entities become unavailable once the grace period has elapsed."""
    await _setup(
        hass, mock_config_entry, mock_api, **{CONF_UNAVAILABLE_GRACE_PERIOD: 30}
    )

    mock_api._on_is_available_updated(False)
    _advance(hass, 29)
    await hass.async_block_till_done()
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_ON)

    _advance(hass, 31)
    await hass.async_block_till_done()
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_UNAVAILABLE)

    mock_api._on_is_available_updated(True)
    await hass.async_block_till_done()
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_ON)


async def test_grace_period_disabled(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock
) -> None:
    """A grace period of 0 keeps the upstream behavior."""
    await _setup(
        hass, mock_config_entry, mock_api, **{CONF_UNAVAILABLE_GRACE_PERIOD: 0}
    )

    mock_api._on_is_available_updated(False)
    await hass.async_block_till_done()
    for entity in ENTITIES:
        assert hass.states.is_state(entity, STATE_UNAVAILABLE)


async def test_unload_cancels_pending_timer(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Unloading with a pending timer does not leave it running."""
    await _setup(hass, mock_config_entry, mock_api)
    mock_api._on_is_available_updated(False)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    _advance(hass, 120)
    await hass.async_block_till_done()


async def test_idle_timeout_registered(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock
) -> None:
    """The idle timeout of the entry is applied and removed on unload."""
    await _setup(hass, mock_config_entry, mock_api, **{CONF_IDLE_TIMEOUT: 90})

    assert idle_timeout._effective_timeout() == 90
    assert (
        atv_remote.RemoteProtocol._async_idle_disconnect
        is idle_timeout._async_idle_disconnect
    )

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert idle_timeout._effective_timeout() == 16


@pytest.mark.parametrize("closing", [False, True])
async def test_patched_idle_disconnect(closing: bool) -> None:
    """The patched idle disconnect waits for the configured delay then closes."""
    idle_timeout.set_idle_timeout("entry", 42)
    protocol = MagicMock()
    protocol.transport.is_closing.return_value = closing
    protocol.on_con_lost = asyncio.get_running_loop().create_future()

    with patch.object(idle_timeout.asyncio, "sleep") as mock_sleep:
        await idle_timeout._async_idle_disconnect(protocol)
    idle_timeout.remove_idle_timeout("entry")

    mock_sleep.assert_awaited_once_with(42)
    assert protocol.transport.close.call_count == (0 if closing else 1)
    assert str(protocol.on_con_lost.result()) == "Closed idle connection"
