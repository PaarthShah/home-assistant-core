"""The GTFS integration."""

import datetime
import os

import pygtfs

from homeassistant.const import CONF_OFFSET, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_DATA, CONF_DESTINATION, CONF_ORIGIN, CONF_TOMORROW, DEFAULT_PATH
from .coordinator import GtfsConfigEntry, GtfsCoordinator

PLATFORMS = [Platform.SENSOR]


def _load_schedule(gtfs_dir: str, data: str) -> pygtfs.Schedule:
    """Load the GTFS feed into a sqlite database. Runs in the executor."""
    os.makedirs(gtfs_dir, exist_ok=True)
    if not os.path.exists(os.path.join(gtfs_dir, data)):
        raise FileNotFoundError(
            f"The given GTFS data file/folder was not found: {data}"
        )

    (gtfs_root, _) = os.path.splitext(data)
    sqlite_file = f"{gtfs_root}.sqlite?check_same_thread=False"
    gtfs = pygtfs.Schedule(os.path.join(gtfs_dir, sqlite_file))
    if not gtfs.feeds:
        pygtfs.append_feed(gtfs, os.path.join(gtfs_dir, data))
    return gtfs


async def async_setup_entry(hass: HomeAssistant, entry: GtfsConfigEntry) -> bool:
    """Set up GTFS from a config entry."""
    gtfs_dir = hass.config.path(DEFAULT_PATH)
    try:
        gtfs = await hass.async_add_executor_job(
            _load_schedule, gtfs_dir, entry.data[CONF_DATA]
        )
    except OSError as err:
        raise ConfigEntryNotReady(f"Unable to load GTFS data: {err}") from err

    coordinator = GtfsCoordinator(
        hass,
        entry,
        gtfs,
        entry.data[CONF_ORIGIN],
        entry.data[CONF_DESTINATION],
        datetime.timedelta(minutes=entry.data[CONF_OFFSET]),
        entry.data[CONF_TOMORROW],
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GtfsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
