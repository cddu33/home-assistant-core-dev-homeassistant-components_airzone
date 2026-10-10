"""Make the androidtvremote2 idle disconnect timeout configurable.

androidtvremote2 closes the connection when nothing is received from the
device for 16 seconds. Some devices (e.g. Epson projectors in standby) accept
the connection but stop sending pings, so the connection is dropped and
re-established every ~16 seconds. This module replaces the hard-coded value.

The library has a single protocol class for all devices, so the effective
timeout is the largest value configured across all config entries.
"""

import asyncio
import logging

from androidtvremote2 import remote as atv_remote

from .const import CONF_IDLE_TIMEOUT_DEFAULT_VALUE

_LOGGER = logging.getLogger(__name__)

_timeouts: dict[str, int] = {}
_patched = False


def _effective_timeout() -> int:
    return max(_timeouts.values(), default=CONF_IDLE_TIMEOUT_DEFAULT_VALUE)


async def _async_idle_disconnect(self: atv_remote.RemoteProtocol) -> None:
    # Same as the library implementation, but with a configurable delay.
    await asyncio.sleep(_effective_timeout())
    atv_remote.LOGGER.debug("Closing idle connection")
    if self.transport and not self.transport.is_closing():
        self.transport.close()
    if not self.on_con_lost.done():
        self.on_con_lost.set_result(Exception("Closed idle connection"))


def _ensure_patched() -> None:
    global _patched  # noqa: PLW0603
    if _patched:
        return
    protocol = getattr(atv_remote, "RemoteProtocol", None)
    if protocol is None or not hasattr(protocol, "_async_idle_disconnect"):
        _LOGGER.warning(
            "Unsupported androidtvremote2 version: idle timeout option is ignored"
        )
        return
    protocol._async_idle_disconnect = _async_idle_disconnect  # noqa: SLF001
    _patched = True


def set_idle_timeout(entry_id: str, timeout: int) -> None:
    """Register the idle timeout of a config entry."""
    _ensure_patched()
    _timeouts[entry_id] = timeout
    _LOGGER.debug("Idle timeout is now %s seconds", _effective_timeout())


def remove_idle_timeout(entry_id: str) -> None:
    """Forget the idle timeout of an unloaded config entry."""
    _timeouts.pop(entry_id, None)
