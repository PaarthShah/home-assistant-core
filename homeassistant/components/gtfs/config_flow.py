"""Config flow for the GTFS integration."""

import os
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_OFFSET
from homeassistant.helpers import selector
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .const import (
    CONF_DATA,
    CONF_DESTINATION,
    CONF_ORIGIN,
    CONF_TOMORROW,
    DEFAULT_PATH,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ORIGIN): selector.TextSelector(),
        vol.Required(CONF_DESTINATION): selector.TextSelector(),
        vol.Required(CONF_DATA): selector.TextSelector(),
        vol.Optional(CONF_OFFSET, default=0): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
        vol.Optional(CONF_TOMORROW, default=False): selector.BooleanSelector(),
    }
)


class GtfsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GTFS."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            origin = user_input[CONF_ORIGIN]
            destination = user_input[CONF_DESTINATION]
            data = user_input[CONF_DATA]

            await self.async_set_unique_id(slugify(f"{data}_{origin}_{destination}"))
            self._abort_if_unique_id_configured()

            if not await self.hass.async_add_executor_job(self._data_exists, data):
                errors["base"] = "invalid_path"
            else:
                return self.async_create_entry(
                    title=f"{origin} → {destination}",
                    data={
                        CONF_ORIGIN: origin,
                        CONF_DESTINATION: destination,
                        CONF_DATA: data,
                        CONF_OFFSET: int(user_input[CONF_OFFSET]),
                        CONF_TOMORROW: user_input[CONF_TOMORROW],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_import(self, import_data: ConfigType) -> ConfigFlowResult:
        """Handle import from configuration.yaml."""
        origin = import_data[CONF_ORIGIN]
        destination = import_data[CONF_DESTINATION]
        data = import_data[CONF_DATA]

        await self.async_set_unique_id(slugify(f"{data}_{origin}_{destination}"))
        self._abort_if_unique_id_configured()

        if not await self.hass.async_add_executor_job(self._data_exists, data):
            return self.async_abort(reason="invalid_path")

        return self.async_create_entry(
            title=import_data.get(CONF_NAME) or f"{origin} → {destination}",
            data={
                CONF_ORIGIN: origin,
                CONF_DESTINATION: destination,
                CONF_DATA: data,
                CONF_OFFSET: int(import_data[CONF_OFFSET].total_seconds() // 60),
                CONF_TOMORROW: import_data[CONF_TOMORROW],
            },
        )

    def _data_exists(self, data: str) -> bool:
        """Check the GTFS data file/folder exists. Runs in the executor."""
        return os.path.exists(os.path.join(self.hass.config.path(DEFAULT_PATH), data))
