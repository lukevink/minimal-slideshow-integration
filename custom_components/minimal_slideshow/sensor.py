"""Photo count and album selection metadata, without share credentials."""
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from .const import DOMAIN
from .providers import PROVIDERS
from homeassistant.helpers.dispatcher import async_dispatcher_connect
SCAN_INTERVAL = timedelta(minutes=5)

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PhotoCount(hass.data[DOMAIN][entry.entry_id], entry)])

class PhotoCount(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Photos"
    _attr_icon = "mdi:image-multiple"
    _attr_native_unit_of_measurement = "photos"
    def __init__(self, feed, entry):
        self.feed = feed
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_photos"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title, "manufacturer": "Minimal Slideshow", "model": PROVIDERS.get(entry.data.get("provider", "icloud"), "Photos"), "entry_type": "service"}
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, f"{DOMAIN}_{self.entry.entry_id}_command", self.async_write_ha_state))
    @property
    def native_value(self):
        return len(self.feed.items)
    @property
    def extra_state_attributes(self):
        return {"album_id": self.entry.entry_id, "photos_served": self.feed.served, "last_command": getattr(self.feed, "last_command", None), "command_sequence": getattr(self.feed, "command_sequence", 0), "status": getattr(self.feed, "error", None) or "ready"}
    async def async_update(self):
        # Catalog refresh is scheduled by the integration, not by each entity.
        pass
