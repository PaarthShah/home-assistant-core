"""Common fixtures for the GTFS tests."""

from collections.abc import Generator
from pathlib import Path
import shutil
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components import gtfs
from homeassistant.components.gtfs import config_flow as gtfs_config_flow
from homeassistant.components.gtfs.const import (
    CONF_DATA,
    CONF_DESTINATION,
    CONF_ORIGIN,
    CONF_TOMORROW,
    DOMAIN,
)
from homeassistant.const import CONF_OFFSET

from tests.common import MockConfigEntry

FIXTURE_FEED = Path(__file__).parent / "fixtures" / "gtfs"


@pytest.fixture
def gtfs_feed(tmp_path: Path) -> Generator[None]:
    """Copy the GTFS feed fixture into an isolated directory."""
    shutil.copytree(FIXTURE_FEED, tmp_path / "feed")
    with (
        patch.object(gtfs, "DEFAULT_PATH", str(tmp_path)),
        patch.object(gtfs_config_flow, "DEFAULT_PATH", str(tmp_path)),
    ):
        yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.gtfs.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="O → D",
        entry_id="01JBXP0X0000000000000GTFS0",
        unique_id="feed_o_d",
        data={
            CONF_ORIGIN: "O",
            CONF_DESTINATION: "D",
            CONF_DATA: "feed",
            CONF_OFFSET: 0,
            CONF_TOMORROW: False,
        },
    )
