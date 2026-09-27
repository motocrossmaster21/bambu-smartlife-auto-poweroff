"""Run the actual Guard class with a fake HA service/state boundary.

This exercises orchestration but does not replace a real HA integration test.
"""
import ast
import asyncio
from datetime import datetime, timezone, timedelta
import logging
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_policy import policy

source = Path(__file__).resolve().parents[1] / "homeassistant/custom_components/p1s_guard/__init__.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
guard_tree = ast.Module(body=[node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Guard"], type_ignores=[])


class HAError(Exception):
    pass


loaded = object()
namespace = dict(asyncio=asyncio, time=time, Reading=policy.Reading, Stability=policy.Stability,
    evaluate=policy.evaluate, dt_util=SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc)),
    callback=lambda func: func, HomeAssistantError=HAError,
    ConfigEntryState=SimpleNamespace(LOADED=loaded), persistent_notification=Mock(),
    LOGGER=logging.getLogger("guard-test"), ARM="input_boolean.bambu_auto_power_off",
    FAULT="input_boolean.p1s_power_off_fault", NOTIFY="input_boolean.p1s_power_off_notifications",
    KEYS=("status", "nozzle", "nozzle_target", "bed", "bed_target", "progress", "online", "plug"))
exec(compile(guard_tree, str(source), "exec"), namespace)
Guard = namespace["Guard"]
ARM, FAULT = namespace["ARM"], namespace["FAULT"]


class States:
    def __init__(self):
        self.data = {}

    def set(self, entity, value, unit=None):
        now = datetime.now(timezone.utc)
        self.data[entity] = SimpleNamespace(state=value, last_reported=now,
            last_changed=now, attributes={"unit_of_measurement": unit})

    def get(self, entity):
        return self.data.get(entity)

    def is_state(self, entity, value):
        return bool(self.get(entity) and self.get(entity).state == value)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.states = States()
        self.calls = []
        self.behavior = "success"
        self.bridge = SimpleNamespace(domain="tuya_cloud_ha_bridge", state=loaded,
                                      runtime_data=SimpleNamespace(connected=True))
        settings = {f"{key}_entity": f"sensor.{key}" for key in namespace["KEYS"]}
        settings.update(bridge_entry_id="bridge", safe_temperature=50, stable_seconds=30,
                        max_age_seconds=60, off_timeout_seconds=0.01)
        self.hass = SimpleNamespace(states=self.states,
            config_entries=SimpleNamespace(async_get_entry=lambda entry: self.bridge),
            services=SimpleNamespace(async_call=self.service))
        self.guard = Guard(self.hass, settings)
        self.guard.started = True
        self.guard.started_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        for key, value in dict(status="finish", nozzle="49", nozzle_target="0", bed="30",
                              bed_target="0", progress="100", online="on", plug="on").items():
            self.states.set(f"sensor.{key}", value, "°C")
        self.states.set(ARM, "on")
        self.states.set(FAULT, "off")
        self.states.set(namespace["NOTIFY"], "off")
        now = time.monotonic()
        for tick in range(31):
            self.guard.stability.update(True, now - 30 + tick)

    async def service(self, domain, service, data, blocking):
        entity = data["entity_id"]
        self.calls.append((domain, service, entity))
        if domain == "input_boolean":
            self.states.set(entity, "on" if service == "turn_on" else "off")
            if entity == FAULT and service == "turn_on" and self.behavior == "race":
                self.states.set("sensor.status", "running")
            self.guard.changed(None)
        elif self.behavior == "error":
            raise HAError("potentially sensitive upstream error")
        elif self.behavior == "success":
            self.states.set(entity, "off")
            self.guard.changed(None)

    async def test_confirmed_off_then_one_shot_reset(self):
        await self.guard.power_off(None)
        self.assertEqual(self.calls, [
            ("input_boolean", "turn_on", FAULT),
            ("switch", "turn_off", "sensor.plug"),
            ("input_boolean", "turn_off", ARM),
            ("input_boolean", "turn_off", FAULT)])
        self.assertFalse(self.guard.busy)
        self.assertFalse(self.guard.safe)

    async def test_service_failure_keeps_intent_and_latches_fault(self):
        self.behavior = "error"
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertTrue(self.states.is_state(ARM, "on"))
        self.assertTrue(self.states.is_state(FAULT, "on"))
        before = len(self.calls)
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertEqual(len(self.calls), before)

    async def test_unconfirmed_off_times_out_without_reset(self):
        self.behavior = "no_confirmation"
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertTrue(self.states.is_state(ARM, "on"))
        self.assertTrue(self.states.is_state(FAULT, "on"))

    async def test_changed_data_between_latch_and_dispatch_blocks(self):
        self.behavior = "race"
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertFalse(any(domain == "switch" for domain, _, _ in self.calls))

    async def test_direct_service_cannot_bypass_timer(self):
        self.guard.stability = policy.Stability(30)
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertEqual(self.calls, [])

    async def test_bridge_disconnected_or_incompatible_blocks(self):
        for runtime in (None, SimpleNamespace(connected=False), SimpleNamespace()):
            self.bridge.runtime_data = runtime
            self.assertFalse(self.guard.bridge_connected())
            with self.assertRaises(HAError):
                await self.guard.power_off(None)
        self.assertEqual(self.calls, [])

    async def test_fault_acknowledgement_requires_disarming(self):
        self.states.set(FAULT, "on")
        with self.assertRaises(HAError):
            await self.guard.acknowledge_fault(None)
        self.states.set(ARM, "off")
        await self.guard.acknowledge_fault(None)
        self.assertTrue(self.states.is_state(FAULT, "off"))

    async def test_parallel_invocation_rejected(self):
        self.guard.busy = True
        with self.assertRaises(HAError):
            await self.guard.power_off(None)
        self.assertEqual(self.calls, [])

    async def test_persisted_fault_blocks_new_guard_after_restart(self):
        self.states.set(FAULT, "on")
        restarted = Guard(self.hass, self.guard.settings)
        restarted.started = True
        restarted.changed(None)
        self.assertEqual(restarted.reason, "FAULT")
        self.assertFalse(restarted.safe)

    async def test_queued_unsafe_transition_resets_window(self):
        unsafe = SimpleNamespace(state="running", last_reported=datetime.now(timezone.utc),
                                 last_changed=datetime.now(timezone.utc), attributes={})
        # Current snapshot is already finish again; queued event was running.
        event = SimpleNamespace(data={"entity_id": "sensor.status", "new_state": unsafe})
        self.guard.changed(event)
        self.assertFalse(self.guard.safe)
        with self.assertRaises(HAError):
            await self.guard.power_off(None)

    async def test_queued_disarm_transition_resets_window(self):
        event = SimpleNamespace(data={"entity_id": ARM, "new_state": SimpleNamespace(state="off")})
        self.guard.changed(event)
        self.assertFalse(self.guard.safe)
