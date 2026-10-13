"""Automation controls for all open Minimal cards displaying this source."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN
ACTIONS={'next':('Next Image','mdi:skip-next'),'previous':('Previous Image','mdi:skip-previous'),'restart':('Restart','mdi:restart')}

async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([SlideshowButton(hass,entry,action) for action in ACTIONS])

class SlideshowButton(ButtonEntity):
    _attr_has_entity_name=True
    def __init__(self,hass,entry,action):
        self.hass=hass;self.entry=entry;self.action=action
        self._attr_name,self._attr_icon=ACTIONS[action]
        self._attr_unique_id=f'{entry.entry_id}_{action}'
        self._attr_device_info={'identifiers':{(DOMAIN,entry.entry_id)}}
    async def async_press(self):
        feed=self.hass.data[DOMAIN][self.entry.entry_id]
        feed.command_sequence=getattr(feed,'command_sequence',0)+1
        feed.last_command=self.action
        self.hass.bus.async_fire(f'{DOMAIN}_command',{'entry_id':self.entry.entry_id,'command':self.action,'sequence':feed.command_sequence})
        async_dispatcher_send(self.hass,f'{DOMAIN}_{self.entry.entry_id}_command')
