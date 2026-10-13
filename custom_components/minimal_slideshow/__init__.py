"""Minimal Slideshow integration lifecycle."""
from __future__ import annotations
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval
from .const import DOMAIN
from .feed import PhotoFeed
from .views import CatalogView, PhotoView, AlbumsView

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.http.register_view(CatalogView)
    hass.http.register_view(PhotoView)
    hass.http.register_view(AlbumsView)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    feed = PhotoFeed(hass, entry)
    try:
        await feed.refresh()
    except Exception:
        await feed.close()
        raise ConfigEntryNotReady("The shared album is temporarily unavailable") from None
    hass.data[DOMAIN][entry.entry_id] = feed
    async def refresh(_now):
        try:
            await feed.refresh(force=True)
        except Exception:
            feed.status("Refresh failed; retaining cached catalog")
    entry.async_on_unload(async_track_time_interval(hass, refresh, timedelta(hours=2)))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "button"])
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, ["sensor", "button"]):
        feed = hass.data[DOMAIN].pop(entry.entry_id, None)
        if feed:
            await feed.close()
        return True
    return False
