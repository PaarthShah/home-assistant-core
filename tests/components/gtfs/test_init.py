"""Test the GTFS integration setup."""

import pytest

from homeassistant.components.gtfs.const import (
    CONF_DATA,
    CONF_DESTINATION,
    CONF_ORIGIN,
    CONF_TOMORROW,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_OFFSET
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from . import setup_integration

from tests.common import MockConfigEntry


@pytest.mark.usefixtures("gtfs_feed")
async def test_load_unload_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test loading and unloading a config entry."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("gtfs_feed")
async def test_setup_missing_data(hass: HomeAssistant) -> None:
    """Test that a missing data file raises ConfigEntryNotReady."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="missing_o_d",
        data={
            CONF_ORIGIN: "O",
            CONF_DESTINATION: "D",
            CONF_DATA: "missing",
            CONF_OFFSET: 0,
            CONF_TOMORROW: False,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("gtfs_feed")
async def test_import_yaml(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Test that a YAML sensor config is imported and deprecation is raised."""
    assert await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": DOMAIN,
                CONF_ORIGIN: "O",
                CONF_DESTINATION: "D",
                CONF_DATA: "feed",
            }
        },
    )
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].state is ConfigEntryState.LOADED

    assert issue_registry.async_get_issue(HOMEASSISTANT_DOMAIN, "deprecated_yaml")
