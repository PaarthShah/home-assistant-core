"""DataUpdateCoordinator for the GTFS integration."""

from dataclasses import dataclass
import datetime
import logging
from typing import Any, override

import pygtfs
from sqlalchemy.sql import text

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type GtfsConfigEntry = ConfigEntry[GtfsCoordinator]


@dataclass
class GtfsData:
    """Resolved GTFS schedule data for a single origin/destination pair."""

    departure: dict[str, Any]
    next_departure: datetime.datetime | None
    origin: Any
    destination: Any
    trip: Any | None
    route: Any | None
    agency: Any | None


def get_next_departure(
    schedule: Any,
    start_station_id: Any,
    end_station_id: Any,
    offset: datetime.timedelta,
    include_tomorrow: bool = False,
) -> dict:
    """Get the next departure for the given schedule."""
    now = dt_util.now().replace(tzinfo=None) + offset
    now_date = now.strftime(dt_util.DATE_STR_FORMAT)
    yesterday = now - datetime.timedelta(days=1)
    yesterday_date = yesterday.strftime(dt_util.DATE_STR_FORMAT)
    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_date = tomorrow.strftime(dt_util.DATE_STR_FORMAT)

    # Fetch all departures for yesterday, today and optionally tomorrow,
    # up to an overkill maximum in case of a departure every minute for those
    # days.
    limit = 24 * 60 * 60 * 2
    tomorrow_select = tomorrow_where = tomorrow_order = ""
    if include_tomorrow:
        limit = int(limit / 2 * 3)
        tomorrow_name = tomorrow.strftime("%A").lower()
        tomorrow_select = f"calendar.{tomorrow_name} AS tomorrow,"
        tomorrow_where = f"OR calendar.{tomorrow_name} = 1"
        tomorrow_order = f"calendar.{tomorrow_name} DESC,"

    sql_query = f"""
        SELECT trip.trip_id, trip.route_id,
               time(origin_stop_time.arrival_time) AS origin_arrival_time,
               time(origin_stop_time.departure_time) AS origin_depart_time,
               date(origin_stop_time.departure_time) AS origin_depart_date,
               origin_stop_time.drop_off_type AS origin_drop_off_type,
               origin_stop_time.pickup_type AS origin_pickup_type,
               origin_stop_time.shape_dist_traveled AS origin_dist_traveled,
               origin_stop_time.stop_headsign AS origin_stop_headsign,
               origin_stop_time.stop_sequence AS origin_stop_sequence,
               origin_stop_time.timepoint AS origin_stop_timepoint,
               time(destination_stop_time.arrival_time) AS dest_arrival_time,
               time(destination_stop_time.departure_time) AS dest_depart_time,
               destination_stop_time.drop_off_type AS dest_drop_off_type,
               destination_stop_time.pickup_type AS dest_pickup_type,
               destination_stop_time.shape_dist_traveled AS dest_dist_traveled,
               destination_stop_time.stop_headsign AS dest_stop_headsign,
               destination_stop_time.stop_sequence AS dest_stop_sequence,
               destination_stop_time.timepoint AS dest_stop_timepoint,
               calendar.{yesterday.strftime("%A").lower()} AS yesterday,
               calendar.{now.strftime("%A").lower()} AS today,
               {tomorrow_select}
               calendar.start_date AS start_date,
               calendar.end_date AS end_date
        FROM trips trip
        INNER JOIN calendar calendar
                   ON trip.service_id = calendar.service_id
        INNER JOIN stop_times origin_stop_time
                   ON trip.trip_id = origin_stop_time.trip_id
        INNER JOIN stops start_station
                   ON origin_stop_time.stop_id = start_station.stop_id
        INNER JOIN stop_times destination_stop_time
                   ON trip.trip_id = destination_stop_time.trip_id
        INNER JOIN stops end_station
                   ON destination_stop_time.stop_id = end_station.stop_id
        WHERE (calendar.{yesterday.strftime("%A").lower()} = 1
               OR calendar.{now.strftime("%A").lower()} = 1
               {tomorrow_where}
               )
        AND start_station.stop_id = :origin_station_id
                   AND end_station.stop_id = :end_station_id
        AND origin_stop_sequence < dest_stop_sequence
        AND calendar.start_date <= :today
        AND calendar.end_date >= :today
        ORDER BY calendar.{yesterday.strftime("%A").lower()} DESC,
                 calendar.{now.strftime("%A").lower()} DESC,
                 {tomorrow_order}
                 origin_stop_time.departure_time
        LIMIT :limit
        """  # noqa: S608
    # Close the connection after each query; otherwise it leaks back into the
    # pool and repeated polls exhaust it (QueuePool limit reached).
    with schedule.engine.connect() as conn:
        result = conn.execute(
            text(sql_query),
            {
                "origin_station_id": start_station_id,
                "end_station_id": end_station_id,
                "today": now_date,
                "limit": limit,
            },
        ).fetchall()

    # Create lookup timetable for today and possibly tomorrow, taking into
    # account any departures from yesterday scheduled after midnight,
    # as long as all departures are within the calendar date range.
    timetable = {}
    yesterday_start = today_start = tomorrow_start = None
    yesterday_last = today_last = ""

    for row_cursor in result:
        row = row_cursor._asdict()
        if row["yesterday"] == 1 and yesterday_date >= row["start_date"]:
            extras = {"day": "yesterday", "first": None, "last": False}
            if yesterday_start is None:
                yesterday_start = row["origin_depart_date"]
            if yesterday_start != row["origin_depart_date"]:
                idx = f"{now_date} {row['origin_depart_time']}"
                timetable[idx] = {**row, **extras}
                yesterday_last = idx

        if row["today"] == 1:
            extras = {"day": "today", "first": False, "last": False}
            if today_start is None:
                today_start = row["origin_depart_date"]
                extras["first"] = True
            if today_start == row["origin_depart_date"]:
                idx_prefix = now_date
            else:
                idx_prefix = tomorrow_date
            idx = f"{idx_prefix} {row['origin_depart_time']}"
            timetable[idx] = {**row, **extras}
            today_last = idx

        if (
            "tomorrow" in row
            and row["tomorrow"] == 1
            and tomorrow_date <= row["end_date"]
        ):
            extras = {"day": "tomorrow", "first": False, "last": None}
            if tomorrow_start is None:
                tomorrow_start = row["origin_depart_date"]
                extras["first"] = True
            if tomorrow_start == row["origin_depart_date"]:
                idx = f"{tomorrow_date} {row['origin_depart_time']}"
                timetable[idx] = {**row, **extras}

    # Flag last departures.
    for idx in filter(None, [yesterday_last, today_last]):
        timetable[idx]["last"] = True

    _LOGGER.debug("Timetable: %s", sorted(timetable.keys()))

    item = {}
    for key in sorted(timetable.keys()):
        if (value := dt_util.parse_datetime(key)) is not None and value > now:
            item = timetable[key]
            _LOGGER.debug(
                "Departure found for station %s @ %s -> %s", start_station_id, key, item
            )
            break

    if item == {}:
        return {}

    # Format arrival and departure dates and times, accounting for the
    # possibility of times crossing over midnight.
    origin_arrival = now
    if item["origin_arrival_time"] > item["origin_depart_time"]:
        origin_arrival -= datetime.timedelta(days=1)
    origin_arrival_time = (
        f"{origin_arrival.strftime(dt_util.DATE_STR_FORMAT)} "
        f"{item['origin_arrival_time']}"
    )

    origin_depart_time = f"{now_date} {item['origin_depart_time']}"

    dest_arrival = now
    if item["dest_arrival_time"] < item["origin_depart_time"]:
        dest_arrival += datetime.timedelta(days=1)
    dest_arrival_time = (
        f"{dest_arrival.strftime(dt_util.DATE_STR_FORMAT)} {item['dest_arrival_time']}"
    )

    dest_depart = dest_arrival
    if item["dest_depart_time"] < item["dest_arrival_time"]:
        dest_depart += datetime.timedelta(days=1)
    dest_depart_time = (
        f"{dest_depart.strftime(dt_util.DATE_STR_FORMAT)} {item['dest_depart_time']}"
    )

    depart_time = dt_util.parse_datetime(origin_depart_time)
    arrival_time = dt_util.parse_datetime(dest_arrival_time)

    origin_stop_time = {
        "Arrival Time": origin_arrival_time,
        "Departure Time": origin_depart_time,
        "Drop Off Type": item["origin_drop_off_type"],
        "Pickup Type": item["origin_pickup_type"],
        "Shape Dist Traveled": item["origin_dist_traveled"],
        "Headsign": item["origin_stop_headsign"],
        "Sequence": item["origin_stop_sequence"],
        "Timepoint": item["origin_stop_timepoint"],
    }

    destination_stop_time = {
        "Arrival Time": dest_arrival_time,
        "Departure Time": dest_depart_time,
        "Drop Off Type": item["dest_drop_off_type"],
        "Pickup Type": item["dest_pickup_type"],
        "Shape Dist Traveled": item["dest_dist_traveled"],
        "Headsign": item["dest_stop_headsign"],
        "Sequence": item["dest_stop_sequence"],
        "Timepoint": item["dest_stop_timepoint"],
    }

    return {
        "trip_id": item["trip_id"],
        "route_id": item["route_id"],
        "day": item["day"],
        "first": item["first"],
        "last": item["last"],
        "departure_time": depart_time,
        "arrival_time": arrival_time,
        "origin_stop_time": origin_stop_time,
        "destination_stop_time": destination_stop_time,
    }


class GtfsCoordinator(DataUpdateCoordinator[GtfsData]):
    """Coordinator querying a GTFS schedule for the next departure."""

    config_entry: GtfsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GtfsConfigEntry,
        gtfs: pygtfs.Schedule,
        origin: str,
        destination: str,
        offset: datetime.timedelta,
        include_tomorrow: bool,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self._gtfs = gtfs
        self.origin = origin
        self.destination = destination
        self._offset = offset
        self._include_tomorrow = include_tomorrow
        self._origin: Any = None
        self._destination: Any = None
        self._trip: Any = None
        self._route: Any = None
        self._agency: Any = None

    @override
    async def _async_update_data(self) -> GtfsData:
        """Fetch the next departure from the schedule."""
        return await self.hass.async_add_executor_job(self._update)

    def _update(self) -> GtfsData:
        """Query the schedule. Runs in the executor (blocking sqlite access)."""
        if self._origin is None:
            stops = self._gtfs.stops_by_id(self.origin)
            if not stops:
                raise UpdateFailed(f"Origin stop ID {self.origin} not found")
            self._origin = stops[0]

        if self._destination is None:
            stops = self._gtfs.stops_by_id(self.destination)
            if not stops:
                raise UpdateFailed(f"Destination stop ID {self.destination} not found")
            self._destination = stops[0]

        departure = get_next_departure(
            self._gtfs,
            self.origin,
            self.destination,
            self._offset,
            self._include_tomorrow,
        )

        if not departure:
            self._trip = None
        else:
            trip_id = departure["trip_id"]
            if not self._trip or self._trip.trip_id != trip_id:
                self._trip = self._gtfs.trips_by_id(trip_id)[0]

            route_id = departure["route_id"]
            if not self._route or self._route.route_id != route_id:
                self._route = self._gtfs.routes_by_id(route_id)[0]

        if self._agency is None and self._route:
            try:
                self._agency = self._gtfs.agencies_by_id(self._route.agency_id)[0]
            except IndexError:
                _LOGGER.warning(
                    (
                        "Agency ID '%s' was not found in agency table, you may want"
                        " to update the routes database table to fix this missing"
                        " reference"
                    ),
                    self._route.agency_id,
                )
                self._agency = False

        # Resolve the timezone-aware departure here, in the executor, since
        # looking up the agency timezone performs blocking file I/O.
        next_departure: datetime.datetime | None = None
        if departure:
            tzinfo: datetime.tzinfo | None = dt_util.UTC
            if self._agency:
                tzinfo = dt_util.get_time_zone(self._agency.agency_timezone)
            next_departure = departure["departure_time"].replace(tzinfo=tzinfo)

        return GtfsData(
            departure=departure,
            next_departure=next_departure,
            origin=self._origin,
            destination=self._destination,
            trip=self._trip,
            route=self._route,
            agency=self._agency,
        )
