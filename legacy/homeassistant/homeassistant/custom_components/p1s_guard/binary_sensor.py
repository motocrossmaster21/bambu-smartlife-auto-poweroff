"""Non-restoring safety status and readable diagnostic attributes."""
from homeassistant.components.binary_sensor import BinarySensorEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SafeSensor(entry.runtime_data)])


class SafeSensor(BinarySensorEntity):
    _attr_name = "P1S Safe Power Off"
    _attr_unique_id = "p1s_safe_power_off"
    _attr_should_poll = False
    _attr_icon = "mdi:shield-check"

    def __init__(self, guard):
        self.guard = guard
        self.entity_id = "binary_sensor.p1s_safe_power_off"

    async def async_added_to_hass(self):
        self.guard.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.guard.listeners.discard(self.async_write_ha_state))

    @property
    def is_on(self):
        return self.guard.safe

    @property
    def extra_state_attributes(self):
        return {"phase": self.guard.reason, **self.guard.settings}
