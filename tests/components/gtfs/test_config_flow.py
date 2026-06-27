"""Test the GTFS config flow."""

from datetime import timedelta
from unittest.mock import patch

import pytest

from homeassistant.components.gtfs.const import (
    CONF_DATA,
    CONF_DESTINATION,
    CONF_ORIGIN,
    CONF_TOMORROW,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import CONF_NAME, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry

USER_INPUT = {
    CONF_ORIGIN: "O",
    CONF_DESTINATION: "D",
    CONF_DATA: "feed",
    CONF_OFFSET: 0,
    CONF_TOMORROW: False,
}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test the full user config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "O → D"
    assert result["data"] == {
        CONF_ORIGIN: "O",
        CONF_DESTINATION: "D",
        CONF_DATA: "feed",
        CONF_OFFSET: 0,
        CONF_TOMORROW: False,
    }
    assert result["result"].unique_id == "feed_o_d"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_invalid_path(hass: HomeAssistant) -> None:
    """Test the user flow when the data file is missing."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=False
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_path"}

    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_import_flow(hass: HomeAssistant) -> None:
    """Test importing a YAML configuration."""
    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_ORIGIN: "O",
                CONF_DESTINATION: "D",
                CONF_DATA: "feed",
                CONF_OFFSET: timedelta(minutes=5),
                CONF_TOMORROW: True,
                CONF_NAME: "My GTFS",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My GTFS"
    assert result["data"] == {
        CONF_ORIGIN: "O",
        CONF_DESTINATION: "D",
        CONF_DATA: "feed",
        CONF_OFFSET: 5,
        CONF_TOMORROW: True,
    }
    assert result["result"].unique_id == "feed_o_d"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_import_flow_invalid_path(hass: HomeAssistant) -> None:
    """Test importing a YAML configuration with a missing data file."""
    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=False
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_ORIGIN: "O",
                CONF_DESTINATION: "D",
                CONF_DATA: "feed",
                CONF_OFFSET: timedelta(0),
                CONF_TOMORROW: False,
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_path"


@pytest.mark.parametrize(
    ("source", "data"),
    [
        (SOURCE_USER, USER_INPUT),
        (
            SOURCE_IMPORT,
            {
                CONF_ORIGIN: "O",
                CONF_DESTINATION: "D",
                CONF_DATA: "feed",
                CONF_OFFSET: timedelta(0),
                CONF_TOMORROW: False,
            },
        ),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_duplicate_aborts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    source: str,
    data: dict,
) -> None:
    """Test that an already configured origin/destination/data aborts."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.gtfs.config_flow.os.path.exists", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": source}, data=data
        )
        if result["type"] is FlowResultType.FORM:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], data
            )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
