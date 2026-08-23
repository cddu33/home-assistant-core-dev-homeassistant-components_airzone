"""Support for the Airzone sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from aioairzone.common import (
    AirzoneStages,
    EcoAdapt,
    GrilleAngle,
    OperationMode,
    QAdapt,
    SleepTimeout,
)
from aioairzone.const import (
    API_COLD_ANGLE,
    API_COLD_STAGE,
    API_ECO_ADAPT,
    API_HEAT_ANGLE,
    API_HEAT_STAGE,
    API_MODE,
    API_Q_ADAPT,
    API_SLEEP,
    API_SYSTEM_ID,
    API_ZONE_ID,
    AZD_COLD_ANGLE,
    AZD_COLD_STAGE,
    AZD_COLD_STAGES,
    AZD_ECO_ADAPT,
    AZD_HEAT_ANGLE,
    AZD_HEAT_STAGE,
    AZD_HEAT_STAGES,
    AZD_ID,
    AZD_MASTER,
    AZD_MODE,
    AZD_MODES,
    AZD_Q_ADAPT,
    AZD_SLEEP,
    AZD_SYSTEM,
    AZD_SYSTEMS,
    AZD_ZONES,
)
from aioairzone.exceptions import AirzoneError

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AirzoneConfigEntry, AirzoneUpdateCoordinator
from .entity import AirzoneEntity, AirzoneSystemEntity, AirzoneZoneEntity


@dataclass(frozen=True, kw_only=True)
class AirzoneSelectDescription(SelectEntityDescription):
    """Class to describe an Airzone select entity."""

    api_param: str
    options_dict: dict[str, int | str]
    options_fn: Callable[[dict[str, Any], dict[str, int | str]], list[str]] = (
        lambda zone_data, value: list(value)
    )


GRILLE_ANGLE_DICT: Final[dict[str, int]] = {
    "90deg": GrilleAngle.DEG_90,
    "50deg": GrilleAngle.DEG_50,
    "45deg": GrilleAngle.DEG_45,
    "40deg": GrilleAngle.DEG_40,
}

MODE_DICT: Final[dict[str, int]] = {
    "cool": OperationMode.COOLING,
    "dry": OperationMode.DRY,
    "fan": OperationMode.FAN,
    "heat": OperationMode.HEATING,
    "heat_cool": OperationMode.AUTO,
    "stop": OperationMode.STOP,
}

SLEEP_DICT: Final[dict[str, int]] = {
    "off": SleepTimeout.SLEEP_OFF,
    "30m": SleepTimeout.SLEEP_30,
    "60m": SleepTimeout.SLEEP_60,
    "90m": SleepTimeout.SLEEP_90,
}

Q_ADAPT_DICT: Final[dict[str, int]] = {
    "standard": QAdapt.STANDARD,
    "power": QAdapt.POWER,
    "silence": QAdapt.SILENCE,
    "minimum": QAdapt.MINIMUM,
    "maximum": QAdapt.MAXIMUM,
}

COLD_STAGE_DICT: Final[dict[str, int]] = {
    "air": AirzoneStages.Air,
    "radiant": AirzoneStages.Radiant,
    "combined": AirzoneStages.Combined,
}

HEAT_STAGE_DICT: Final[dict[str, int]] = {
    "air": AirzoneStages.Air,
    "radiant": AirzoneStages.Radiant,
    "combined": AirzoneStages.Combined,
}

ECO_ADAPT_DICT: Final[dict[str, str]] = {
    "off": EcoAdapt.OFF,
    "manual": EcoAdapt.MANUAL,
    "a": EcoAdapt.A,
    "a_p": EcoAdapt.A_PLUS,
    "a_pp": EcoAdapt.A_PLUS_PLUS,
}


def main_zone_options(
    zone_data: dict[str, Any],
    options: dict[str, int],
) -> list[str]:
    """Filter available modes."""
    modes = zone_data.get(AZD_MODES, [])
    return [k for k, v in options.items() if v in modes]


def cold_stage_options(
    zone_data: dict[str, Any],
    options: dict[str, int],
) -> list[str]:
    """Filter available cold stages."""
    stages = zone_data.get(AZD_COLD_STAGES, [])
    return [k for k, v in options.items() if v in stages]


def heat_stage_options(
    zone_data: dict[str, Any],
    options: dict[str, int],
) -> list[str]:
    """Filter available heat stages."""
    stages = zone_data.get(AZD_HEAT_STAGES, [])
    return [k for k, v in options.items() if v in stages]


SYSTEM_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param=API_Q_ADAPT,
        entity_category=EntityCategory.CONFIG,
        key=AZD_Q_ADAPT,
        options=list(Q_ADAPT_DICT),
        options_dict=Q_ADAPT_DICT,
        translation_key="q_adapt",
    ),
)


# System-level selects that apply a zone parameter to every zone at once
# (fan-out), reproducing a "global zone" control.
SYSTEM_ZONES_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param=API_SLEEP,
        entity_category=EntityCategory.CONFIG,
        key=AZD_SLEEP,
        options=list(SLEEP_DICT),
        options_dict=SLEEP_DICT,
        translation_key="all_zones_sleep",
    ),
)


MAIN_ZONE_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param=API_MODE,
        key=AZD_MODE,
        options_dict=MODE_DICT,
        options_fn=main_zone_options,
        translation_key="modes",
    ),
)


ZONE_SELECT_TYPES: Final[tuple[AirzoneSelectDescription, ...]] = (
    AirzoneSelectDescription(
        api_param=API_COLD_ANGLE,
        entity_category=EntityCategory.CONFIG,
        key=AZD_COLD_ANGLE,
        options=list(GRILLE_ANGLE_DICT),
        options_dict=GRILLE_ANGLE_DICT,
        translation_key="grille_angles",
    ),
    AirzoneSelectDescription(
        api_param=API_HEAT_ANGLE,
        entity_category=EntityCategory.CONFIG,
        key=AZD_HEAT_ANGLE,
        options=list(GRILLE_ANGLE_DICT),
        options_dict=GRILLE_ANGLE_DICT,
        translation_key="heat_angles",
    ),
    AirzoneSelectDescription(
        api_param=API_SLEEP,
        entity_category=EntityCategory.CONFIG,
        key=AZD_SLEEP,
        options=list(SLEEP_DICT),
        options_dict=SLEEP_DICT,
        translation_key="sleep_times",
    ),
    AirzoneSelectDescription(
        api_param=API_COLD_STAGE,
        entity_category=EntityCategory.CONFIG,
        key=AZD_COLD_STAGE,
        options_dict=COLD_STAGE_DICT,
        options_fn=cold_stage_options,
        translation_key="cold_stage",
    ),
    AirzoneSelectDescription(
        api_param=API_HEAT_STAGE,
        entity_category=EntityCategory.CONFIG,
        key=AZD_HEAT_STAGE,
        options_dict=HEAT_STAGE_DICT,
        options_fn=heat_stage_options,
        translation_key="heat_stage",
    ),
    # Eco-Adapt is only present in the zone-level JSON returned by the
    # webserver (confirmed via a real diagnostics dump), not the system
    # level one, so it has to be written as a zone param, not a system one.
    # It's also not in aioairzone's API_ZONE_PARAMS allow-list, so a
    # successful write won't be reflected in the library's local cache until
    # the next poll — see the optimistic update in async_select_option.
    # Disabled by default until confirmed to be honored by real hardware.
    AirzoneSelectDescription(
        api_param=API_ECO_ADAPT,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        key=AZD_ECO_ADAPT,
        options=list(ECO_ADAPT_DICT),
        options_dict=ECO_ADAPT_DICT,
        translation_key="eco_adapt",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirzoneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add Airzone select from a config_entry."""
    coordinator = entry.runtime_data

    added_systems: set[str] = set()
    added_zones: set[str] = set()

    def _async_entity_listener() -> None:
        """Handle additions of select."""

        entities: list[AirzoneBaseSelect] = []

        systems_data = coordinator.data.get(AZD_SYSTEMS, {})
        received_systems = set(systems_data)
        new_systems = received_systems - added_systems
        if new_systems:
            entities.extend(
                AirzoneSystemSelect(
                    coordinator,
                    description,
                    entry,
                    system_id,
                    systems_data.get(system_id),
                )
                for system_id in new_systems
                for description in SYSTEM_SELECT_TYPES
                if description.key in systems_data.get(system_id)
            )
            entities.extend(
                AirzoneSystemZonesSelect(
                    coordinator,
                    description,
                    entry,
                    system_id,
                )
                for system_id in new_systems
                for description in SYSTEM_ZONES_SELECT_TYPES
            )
            added_systems.update(new_systems)

        zones_data = coordinator.data.get(AZD_ZONES, {})
        received_zones = set(zones_data)
        new_zones = received_zones - added_zones
        if new_zones:
            entities.extend(
                AirzoneZoneSelect(
                    coordinator,
                    description,
                    entry,
                    system_zone_id,
                    zones_data.get(system_zone_id),
                )
                for system_zone_id in new_zones
                for description in MAIN_ZONE_SELECT_TYPES
                if description.key in zones_data.get(system_zone_id)
                and zones_data.get(system_zone_id).get(AZD_MASTER) is True
            )
            entities.extend(
                AirzoneZoneSelect(
                    coordinator,
                    description,
                    entry,
                    system_zone_id,
                    zones_data.get(system_zone_id),
                )
                for system_zone_id in new_zones
                for description in ZONE_SELECT_TYPES
                if description.key in zones_data.get(system_zone_id)
            )
            added_zones.update(new_zones)

        async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_entity_listener))
    _async_entity_listener()


class AirzoneBaseSelect(AirzoneEntity, SelectEntity):
    """Define an Airzone select."""

    entity_description: AirzoneSelectDescription
    values_dict: dict[int | str, str]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    def _get_current_option(self) -> str | None:
        value = self.get_airzone_value(self.entity_description.key)
        return self.values_dict.get(value)

    @callback
    def _async_update_attrs(self) -> None:
        """Update select attributes."""
        self._attr_current_option = self._get_current_option()


class AirzoneSystemSelect(AirzoneSystemEntity, AirzoneBaseSelect):
    """Define an Airzone System select."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        description: AirzoneSelectDescription,
        entry: ConfigEntry,
        system_id: str,
        system_data: dict[str, Any],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, system_data)

        self._attr_unique_id = f"{self._attr_unique_id}_{system_id}_{description.key}"
        self.entity_description = description

        self._attr_options = self.entity_description.options_fn(
            system_data, description.options_dict
        )

        self.values_dict = {v: k for k, v in description.options_dict.items()}

        self._async_update_attrs()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        param = self.entity_description.api_param
        value = self.entity_description.options_dict[option]
        await self._async_update_sys_params({param: value})


class AirzoneSystemZonesSelect(AirzoneSystemEntity, AirzoneBaseSelect):
    """Define a global select that applies a zone parameter to all zones."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        description: AirzoneSelectDescription,
        entry: ConfigEntry,
        system_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, coordinator.data[AZD_SYSTEMS][system_id])

        self._attr_unique_id = (
            f"{self._attr_unique_id}_{system_id}_all_zones_{description.key}"
        )
        self.entity_description = description
        self._attr_options = list(description.options_dict)
        self.values_dict = {v: k for k, v in description.options_dict.items()}

        self._async_update_attrs()

    def _system_zones(self) -> list[dict[str, Any]]:
        """Return the data of every zone belonging to this system."""
        zones = self.coordinator.data.get(AZD_ZONES, {})
        return [
            zone for zone in zones.values() if zone.get(AZD_SYSTEM) == self.system_id
        ]

    def _zone_value(self, key: str) -> Any:
        """Return a representative value from the master zone of the system."""
        zones = self._system_zones()
        for zone in zones:
            if zone.get(AZD_MASTER):
                return zone.get(key)
        return zones[0].get(key) if zones else None

    def _get_current_option(self) -> str | None:
        value = self._zone_value(self.entity_description.key)
        return self.values_dict.get(value)

    async def async_select_option(self, option: str) -> None:
        """Apply the selected option to every zone that supports it (fan-out)."""
        param = self.entity_description.api_param
        key = self.entity_description.key
        value = self.entity_description.options_dict[option]
        try:
            for zone in self._system_zones():
                if key not in zone:
                    # This zone doesn't expose the parameter (e.g. no
                    # physical thermostat), skip it instead of sending an
                    # unsupported/invalid value.
                    continue
                await self.coordinator.airzone.set_hvac_parameters(
                    {
                        API_SYSTEM_ID: zone[AZD_SYSTEM],
                        API_ZONE_ID: zone[AZD_ID],
                        param: value,
                    }
                )
        except AirzoneError as error:
            raise HomeAssistantError(
                f"Failed to set system {self.entity_id}: {error}"
            ) from error

        self.coordinator.async_set_updated_data(self.coordinator.airzone.data())


class AirzoneZoneSelect(AirzoneZoneEntity, AirzoneBaseSelect):
    """Define an Airzone Zone select."""

    def __init__(
        self,
        coordinator: AirzoneUpdateCoordinator,
        description: AirzoneSelectDescription,
        entry: ConfigEntry,
        system_zone_id: str,
        zone_data: dict[str, Any],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, system_zone_id, zone_data)

        self._attr_unique_id = (
            f"{self._attr_unique_id}_{system_zone_id}_{description.key}"
        )
        self.entity_description = description

        self._attr_options = self.entity_description.options_fn(
            zone_data, description.options_dict
        )

        # A select with a single (or no) option cannot be acted upon, so
        # disable it by default (e.g. cold/heat stage when the zone only
        # exposes one stage). It can still be enabled manually.
        if len(self._attr_options) <= 1:
            self._attr_entity_registry_enabled_default = False

        self.values_dict = {v: k for k, v in description.options_dict.items()}

        self._async_update_attrs()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        param = self.entity_description.api_param
        value = self.entity_description.options_dict[option]
        await self._async_update_hvac_params({param: value})

        if self.entity_description.key == AZD_ECO_ADAPT:
            # eco_adapt isn't in aioairzone's API_ZONE_PARAMS allow-list, so
            # the coordinator's cached data above won't reflect this write
            # until the next poll. Update the displayed state optimistically
            # so it doesn't look stuck on the previous value in the
            # meantime (worse if polling is disabled).
            self._attr_current_option = option
            self.async_write_ha_state()
