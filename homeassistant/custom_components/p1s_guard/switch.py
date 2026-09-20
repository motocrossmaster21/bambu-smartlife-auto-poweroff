"""Device-backed proxy for the existing helper, discoverable by Tuya Bridge."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from . import ARM, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ArmSwitch(entry.runtime_data)])


class ArmSwitch(SwitchEntity):
    _attr_name = "Bambu Auto Power Off"
    _attr_unique_id = "bambu_auto_power_off_switch"
    _attr_should_poll = False
    _attr_icon = "mdi:power-sleep"
    # A regular device (not entry_type=service): the bridge exports devices.
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, "arm_switch")},
        name="Bambu Auto Power Off", manufacturer="Local", model="One-shot switch")

    def __init__(self, guard):
        self.guard = guard
        self.entity_id = "switch.bambu_auto_power_off"

    async def async_added_to_hass(self):
        self.guard.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.guard.listeners.discard(self.async_write_ha_state))

    @property
    def available(self):
        return self.hass.states.get(ARM) is not None and self.hass.states.get(ARM).state in ("on", "off")

    @property
    def is_on(self):
        return self.hass.states.is_state(ARM, "on")

    async def async_turn_on(self, **kwargs):
        await self.guard.helper(ARM, True)

    async def async_turn_off(self, **kwargs):
        await self.guard.helper(ARM, False)
