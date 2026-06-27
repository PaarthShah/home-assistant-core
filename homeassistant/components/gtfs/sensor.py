"""Support for GTFS (General Transit Feed Specification)."""

import datetime
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME, CONF_OFFSET
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ATTR_ARRIVAL,
    ATTR_BICYCLE,
    ATTR_DAY,
    ATTR_DROP_OFF_DESTINATION,
    ATTR_DROP_OFF_ORIGIN,
    ATTR_FIRST,
    ATTR_INFO,
    ATTR_LAST,
    ATTR_LOCATION_DESTINATION,
    ATTR_LOCATION_ORIGIN,
    ATTR_OFFSET,
    ATTR_PICKUP_DESTINATION,
    ATTR_PICKUP_ORIGIN,
    ATTR_ROUTE_TYPE,
    ATTR_TIMEPOINT_DESTINATION,
    ATTR_TIMEPOINT_ORIGIN,
    ATTR_WHEELCHAIR,
    ATTR_WHEELCHAIR_DESTINATION,
    ATTR_WHEELCHAIR_ORIGIN,
    BICYCLE_ALLOWED_DEFAULT,
    BICYCLE_ALLOWED_OPTIONS,
    CONF_DATA,
    CONF_DESTINATION,
    CONF_ORIGIN,
    CONF_TOMORROW,
    DOMAIN,
    DROP_OFF_TYPE_DEFAULT,
    DROP_OFF_TYPE_OPTIONS,
    ICON,
    ICONS,
    LOCATION_TYPE_DEFAULT,
    LOCATION_TYPE_OPTIONS,
    PICKUP_TYPE_DEFAULT,
    PICKUP_TYPE_OPTIONS,
    ROUTE_TYPE_OPTIONS,
    TIMEPOINT_DEFAULT,
    TIMEPOINT_OPTIONS,
    WHEELCHAIR_ACCESS_DEFAULT,
    WHEELCHAIR_ACCESS_OPTIONS,
    WHEELCHAIR_BOARDING_DEFAULT,
    WHEELCHAIR_BOARDING_OPTIONS,
)
from .coordinator import GtfsConfigEntry, GtfsCoordinator, GtfsData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ORIGIN): cv.string,
        vol.Required(CONF_DESTINATION): cv.string,
        vol.Required(CONF_DATA): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_OFFSET, default=0): cv.time_period,
        vol.Optional(CONF_TOMORROW, default=False): cv.boolean,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the GTFS sensor from YAML, triggering an import to the config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=config
    )
    if (
        result.get("type") is FlowResultType.ABORT
        and result.get("reason") != "already_configured"
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"deprecated_yaml_import_issue_{result.get('reason')}",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key="deprecated_yaml_import_issue",
            translation_placeholders={
                "domain": DOMAIN,
                "integration_title": "GTFS",
            },
        )
        return

    ir.async_create_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        "deprecated_yaml",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        translation_placeholders={
            "domain": DOMAIN,
            "integration_title": "GTFS",
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GtfsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the GTFS sensor from a config entry."""
    async_add_entities([GTFSDepartureSensor(entry.runtime_data, entry)])


def _dict_for_table(resource: Any) -> dict[str, str]:
    """Return a dictionary for the SQLAlchemy resource given."""
    return {
        column.name: str(getattr(resource, column.name))
        for column in resource.__table__.columns
    }


def _append_keys(
    attributes: dict[str, Any], resource: dict[str, Any], prefix: str
) -> None:
    """Format key/value pairs and append them to attributes."""
    for attr, val in resource.items():
        if val == "" or val is None or attr == "feed_id":
            continue
        key = attr if attr.startswith(prefix) else f"{prefix} {attr}"
        attributes[slugify(key)] = val


def _build_attributes(
    data: GtfsData,
    offset: int,
    include_tomorrow: bool,
    state: datetime.datetime | None,
) -> dict[str, Any]:
    """Build the state attributes from the coordinator data."""
    attributes: dict[str, Any] = {ATTR_OFFSET: offset}
    departure = data.departure

    if departure:
        attributes[ATTR_ARRIVAL] = dt_util.as_utc(departure["arrival_time"]).isoformat()
        attributes[ATTR_DAY] = departure["day"]
        if departure["first"] is not None:
            attributes[ATTR_FIRST] = departure["first"]
        if departure["last"] is not None:
            attributes[ATTR_LAST] = departure["last"]
    elif state is None:
        attributes[ATTR_INFO] = (
            "No more departures" if include_tomorrow else "No more departures today"
        )

    if data.agency:
        _append_keys(attributes, _dict_for_table(data.agency), "Agency")

    if data.origin:
        _append_keys(attributes, _dict_for_table(data.origin), "Origin Station")
        attributes[ATTR_LOCATION_ORIGIN] = LOCATION_TYPE_OPTIONS.get(
            data.origin.location_type, LOCATION_TYPE_DEFAULT
        )
        attributes[ATTR_WHEELCHAIR_ORIGIN] = WHEELCHAIR_BOARDING_OPTIONS.get(
            data.origin.wheelchair_boarding, WHEELCHAIR_BOARDING_DEFAULT
        )

    if data.destination:
        _append_keys(
            attributes, _dict_for_table(data.destination), "Destination Station"
        )
        attributes[ATTR_LOCATION_DESTINATION] = LOCATION_TYPE_OPTIONS.get(
            data.destination.location_type, LOCATION_TYPE_DEFAULT
        )
        attributes[ATTR_WHEELCHAIR_DESTINATION] = WHEELCHAIR_BOARDING_OPTIONS.get(
            data.destination.wheelchair_boarding, WHEELCHAIR_BOARDING_DEFAULT
        )

    if data.route:
        _append_keys(attributes, _dict_for_table(data.route), "Route")
        attributes[ATTR_ROUTE_TYPE] = ROUTE_TYPE_OPTIONS[data.route.route_type]

    if data.trip:
        _append_keys(attributes, _dict_for_table(data.trip), "Trip")
        attributes[ATTR_BICYCLE] = BICYCLE_ALLOWED_OPTIONS.get(
            data.trip.bikes_allowed, BICYCLE_ALLOWED_DEFAULT
        )
        attributes[ATTR_WHEELCHAIR] = WHEELCHAIR_ACCESS_OPTIONS.get(
            data.trip.wheelchair_accessible, WHEELCHAIR_ACCESS_DEFAULT
        )

    if departure:
        origin_stop_time = departure["origin_stop_time"]
        _append_keys(attributes, origin_stop_time, "origin_stop")
        attributes[ATTR_DROP_OFF_ORIGIN] = DROP_OFF_TYPE_OPTIONS.get(
            origin_stop_time["Drop Off Type"], DROP_OFF_TYPE_DEFAULT
        )
        attributes[ATTR_PICKUP_ORIGIN] = PICKUP_TYPE_OPTIONS.get(
            origin_stop_time["Pickup Type"], PICKUP_TYPE_DEFAULT
        )
        attributes[ATTR_TIMEPOINT_ORIGIN] = TIMEPOINT_OPTIONS.get(
            origin_stop_time["Timepoint"], TIMEPOINT_DEFAULT
        )

        destination_stop_time = departure["destination_stop_time"]
        _append_keys(attributes, destination_stop_time, "destination_stop")
        attributes[ATTR_DROP_OFF_DESTINATION] = DROP_OFF_TYPE_OPTIONS.get(
            destination_stop_time["Drop Off Type"], DROP_OFF_TYPE_DEFAULT
        )
        attributes[ATTR_PICKUP_DESTINATION] = PICKUP_TYPE_OPTIONS.get(
            destination_stop_time["Pickup Type"], PICKUP_TYPE_DEFAULT
        )
        attributes[ATTR_TIMEPOINT_DESTINATION] = TIMEPOINT_OPTIONS.get(
            destination_stop_time["Timepoint"], TIMEPOINT_DEFAULT
        )

    return attributes


class GTFSDepartureSensor(CoordinatorEntity[GtfsCoordinator], SensorEntity):
    """Implementation of a GTFS departure sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: GtfsCoordinator, entry: GtfsConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    @override
    def native_value(self) -> datetime.datetime | None:
        """Return the departure time of the next service."""
        return self.coordinator.data.next_departure

    @property
    @override
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        if route := self.coordinator.data.route:
            return ICONS.get(route.route_type, ICON)
        return ICON

    @property
    @override
    def attribution(self) -> str | None:
        """Return the attribution of the agency."""
        if agency := self.coordinator.data.agency:
            return agency.agency_name
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return _build_attributes(
            self.coordinator.data,
            self._entry.data[CONF_OFFSET],
            self._entry.data[CONF_TOMORROW],
            self.native_value,
        )
