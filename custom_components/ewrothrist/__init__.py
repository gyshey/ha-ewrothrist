"""EW Rothrist Smart Meter integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import EwrClient
from .coordinator import EwrCoordinator

PLATFORMS = [Platform.SENSOR]

EwrConfigEntry = ConfigEntry[EwrCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EwrConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_create_clientsession(hass)
    client = EwrClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = EwrCoordinator(hass, entry, client, entry.data["meter"])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: EwrConfigEntry) -> None:
    """Reload on option changes (polling interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EwrConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
