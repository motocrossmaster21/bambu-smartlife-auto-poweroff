"""Local safety gate. All cloud communication belongs to upstream integrations."""
import asyncio
from datetime import timedelta
import logging
from math import isfinite
import time

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .policy import Reading, Stability, evaluate

DOMAIN = "p1s_guard"
ARM = "input_boolean.bambu_auto_power_off"
FAULT = "input_boolean.p1s_power_off_fault"
NOTIFY = "input_boolean.p1s_power_off_notifications"
LOGGER = logging.getLogger(__name__)
KEYS = ("status", "nozzle", "nozzle_target", "bed", "bed_target", "progress", "online", "plug")


def finite(value):
    if not isfinite(value):
        raise vol.Invalid("Value must be finite")
    return value


SETTINGS = vol.Schema({
    **{vol.Required(f"{key}_entity"): vol.All(cv.entity_id, vol.Match(r"^sensor\."))
       for key in KEYS if key not in ("online", "plug")},
    vol.Required("online_entity"): vol.All(cv.entity_id, vol.Match(r"^binary_sensor\.")),
    vol.Required("plug_entity"): vol.All(cv.entity_id, vol.Match(r"^switch\."),
        vol.NotIn(["switch.bambu_auto_power_off"])),
    vol.Required("bridge_entry_id"): cv.string,
    vol.Required("safe_temperature"): vol.All(vol.Coerce(float), finite, vol.Range(min=1, max=50)),
    vol.Required("stable_seconds"): vol.All(vol.Coerce(float), finite, vol.Range(min=30, max=3600)),
    vol.Required("max_age_seconds"): vol.All(vol.Coerce(float), finite, vol.Range(min=5, max=120)),
    vol.Required("off_timeout_seconds"): vol.All(vol.Coerce(float), finite, vol.Range(min=5, max=120)),
})
CONFIG_SCHEMA = vol.Schema({vol.Required(DOMAIN): SETTINGS}, extra=vol.ALLOW_EXTRA)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup(hass, config):
    hass.data[DOMAIN] = {"settings": config[DOMAIN]}
    hass.async_create_task(hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "import"}, data={}))
    return True


async def async_setup_entry(hass, entry):
    settings = hass.data.get(DOMAIN, {}).get("settings")
    if settings is None:
        return False
    guard = Guard(hass, settings)
    entry.runtime_data = guard
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    guard.start()
    hass.services.async_register(DOMAIN, "power_off", guard.power_off, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "acknowledge_fault", guard.acknowledge_fault, schema=vol.Schema({}))
    return True


async def async_unload_entry(hass, entry):
    if entry.runtime_data.busy:
        raise HomeAssistantError("A power-off attempt is still in progress")
    entry.runtime_data.stop()
    for service in ("power_off", "acknowledge_fault"):
        hass.services.async_remove(DOMAIN, service)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class Guard:
    def __init__(self, hass, settings):
        self.hass = hass
        self.settings = settings
        self.stability = Stability(settings["stable_seconds"])
        self.started_at = dt_util.utcnow()
        self.started = False
        self.busy = False
        self.safe = False
        self.reason = "STARTING"
        self.listeners = set()
        self.unsubscribers = []

    def start(self):
        entities = [self.settings[f"{key}_entity"] for key in KEYS] + [ARM, FAULT]
        self.unsubscribers.append(async_track_state_change_event(self.hass, entities, self.changed))
        self.unsubscribers.append(async_track_time_interval(self.hass, self.changed, timedelta(seconds=1)))
        if self.hass.is_running:
            self.on_started(None)
        else:
            self.unsubscribers.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.on_started))

    def stop(self):
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        self.started = False
        self.safe = False

    @callback
    def on_started(self, event):
        self.started = True
        self.started_at = dt_util.utcnow()
        self.changed(None)

    def bridge_connected(self):
        entry = self.hass.config_entries.async_get_entry(self.settings["bridge_entry_id"])
        return bool(entry and entry.domain == "tuya_cloud_ha_bridge"
                    and entry.state is ConfigEntryState.LOADED
                    and getattr(getattr(entry, "runtime_data", None), "connected", None) is True)

    def eligibility(self, observed=None):
        if not self.started:
            return "STARTING"
        now = dt_util.utcnow()
        readings = {}
        for key in KEYS:
            entity_id = self.settings[f"{key}_entity"]
            state = (observed[1] if observed and observed[0] == entity_id
                     else self.hass.states.get(entity_id))
            if state is not None:
                readings[key] = Reading(
                    state.state, (now - state.last_reported).total_seconds(),
                    # A plug can legitimately report only on changes. Printer
                    # telemetry must be reported after guard startup.
                    key == "plug" or state.last_reported >= self.started_at,
                    state.attributes.get("unit_of_measurement"),
                    bool(state.attributes.get("restored", False)))
        armed = self.hass.states.is_state(ARM, "on")
        if observed and observed[0] == ARM:
            armed = observed[1] is not None and observed[1].state == "on"
        return evaluate(readings,
            armed=armed,
            fault=not self.busy and not self.hass.states.is_state(FAULT, "off"),
            bridge=self.bridge_connected(), limit=self.settings["safe_temperature"],
            max_age=self.settings["max_age_seconds"])

    @callback
    def changed(self, event):
        previous = (self.safe, self.reason)
        # Preserve a brief unsafe transition even if a newer event has already
        # replaced that state by the time this listener is called.
        if hasattr(event, "data") and "entity_id" in event.data:
            observed = (event.data["entity_id"], event.data.get("new_state"))
            if observed[1] is not None:
                if observed[0] == ARM and observed[1].state == "on":
                    LOGGER.info("P1S auto power off armed")
                if observed[0] == self.settings["status_entity"] and observed[1].state == "finish":
                    LOGGER.info("P1S print finished; checking cooldown conditions")
            if self.eligibility(observed) != "ELIGIBLE":
                self.stability.update(False, time.monotonic())
        reason = self.eligibility()
        stable = self.stability.update(reason == "ELIGIBLE", time.monotonic())
        self.safe = stable and not self.busy
        self.reason = ("POWER_OFF" if self.busy else "SAFE" if stable
                       else "STABILIZING" if reason == "ELIGIBLE" else reason)
        if previous != (self.safe, self.reason):
            LOGGER.info("P1S guard: %s", self.reason)
        for listener in tuple(self.listeners):
            listener()

    async def helper(self, entity, value):
        await self.hass.services.async_call("input_boolean", "turn_on" if value else "turn_off",
                                          {"entity_id": entity}, blocking=True)

    async def acknowledge_fault(self, call):
        if self.busy or not self.hass.states.is_state(ARM, "off"):
            raise HomeAssistantError("Disarm first; no power-off attempt may be running")
        await self.helper(FAULT, False)
        persistent_notification.async_dismiss(self.hass, "p1s_power_off_failed")
        self.changed(None)

    async def power_off(self, call):
        if self.busy:
            raise HomeAssistantError("Power-off attempt already in progress")
        self.changed(None)
        if not self.safe:
            raise HomeAssistantError("P1S is not safe to turn off")
        self.busy = True
        try:
            # Persistent latch BEFORE dispatch. A crash/timeout never retries
            # silently against a later print after HA restarts.
            await self.helper(FAULT, True)
            self.changed(None)
            if not self.stability.update(self.eligibility() == "ELIGIBLE", time.monotonic()):
                raise HomeAssistantError("Safety conditions changed before dispatch")
            dispatched_at = dt_util.utcnow()
            async with asyncio.timeout(self.settings["off_timeout_seconds"]):
                await self.hass.services.async_call("switch", "turn_off",
                    {"entity_id": self.settings["plug_entity"]}, blocking=True)
                while True:
                    state = self.hass.states.get(self.settings["plug_entity"])
                    if (state and state.state == "off" and state.last_changed >= dispatched_at
                            and not state.attributes.get("restored", False)):
                        break
                    await asyncio.sleep(0.25)
            LOGGER.info("P1S power plug reported OFF")
            await self.helper(ARM, False)
            await self.helper(FAULT, False)
            LOGGER.info("P1S auto power off reset")
            if self.hass.states.is_state(NOTIFY, "on"):
                persistent_notification.async_create(self.hass,
                    "P1S wurde nach erfolgreichem Druck automatisch ausgeschaltet.",
                    title="P1S Auto Power Off", notification_id="p1s_power_off_success")
        except Exception as error:
            # Do not print upstream exception payloads, which may contain secrets.
            LOGGER.error("P1S power-off failed (%s); acknowledgement required", type(error).__name__)
            persistent_notification.async_create(self.hass,
                "Abschaltung nicht bestätigt. Steckdose prüfen. Freigabe ausschalten, "
                "dann p1s_guard.acknowledge_fault ausführen. Kein automatischer Wiederholungsversuch.",
                title="P1S Abschaltfehler", notification_id="p1s_power_off_failed")
            raise HomeAssistantError("P1S power-off failed; inspect the plug and acknowledge the fault") from None
        finally:
            self.busy = False
            self.changed(None)
