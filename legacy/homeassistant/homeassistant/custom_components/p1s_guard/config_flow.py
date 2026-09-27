"""Register a single local guard device; settings remain in YAML/ENV."""
from homeassistant import config_entries


class ConfigFlow(config_entries.ConfigFlow, domain="p1s_guard"):
    VERSION = 1

    async def async_step_import(self, user_input):
        await self.async_set_unique_id("p1s_guard")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="P1S Power Guard", data={})

    async def async_step_user(self, user_input=None):
        return self.async_abort(reason="yaml_required")
