import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bambuoff.config import Config
from bambuoff.policy import Gate, Store, FIELDS, decode
from bambuoff.mqtt import Connections, report, tuya_credentials
from scripts.bambu_login import save_env
from scripts.configure import prepare


def packet(**changes):
    data = dict(gcode_state="FINISH", subtask_id="123", mc_percent=100,
        nozzle_temper=49, nozzle_target_temper=0, bed_temper=30, bed_target_temper=0)
    data.update(changes)
    return {"print": data}


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config.load({})
        self.store = Store(Path(self.temp.name) / "state.json")
        self.gate = Gate(self.config, self.store)
        self.gate.ingest(packet(gcode_state="RUNNING"), -1)
        self.gate.tick(-1, True)

    def advance(self, start=0, end=31, data=None):
        for at in range(start, end):
            self.gate.ingest(data or packet(), at)
            value = self.gate.tick(at, True)
        return value

    def test_30_full_seconds_required(self):
        self.assertFalse(self.advance(end=30))
        self.gate.ingest(packet(), 30)
        self.assertTrue(self.gate.tick(30, True))

    def test_only_finish_allowed(self):
        for status in ("RUNNING", "PREPARE", "PAUSE", "FAILED", "IDLE", "UNKNOWN", "unavailable", "finish"):
            with self.subTest(status=status):
                self.gate.ingest(packet(gcode_state=status), 0)
                self.assertNotEqual(self.gate.eligible(0, True)[0], "ELIGIBLE")

    def test_heaters_and_progress(self):
        for field, value in (("nozzle_temper", 80), ("nozzle_target_temper", 60),
                              ("bed_target_temper", 60), ("mc_percent", 99)):
            self.gate.ingest(packet(**{field: value}), 0)
            self.assertFalse(self.gate.tick(0, True))

    def test_unknown_and_non_finite_values(self):
        for field in FIELDS[3:]:
            for value in (None, "unknown", "49", True, float("nan"), float("inf"), -1):
                self.gate.ingest(packet(**{field: value}), 0)
                self.assertNotEqual(self.gate.eligible(0, True)[0], "ELIGIBLE")

    def test_every_required_field_must_be_present(self):
        for field in FIELDS:
            self.gate.invalidate()
            data = packet()
            del data["print"][field]
            self.gate.ingest(data, 0)
            self.assertNotEqual(self.gate.eligible(0, True)[0], "ELIGIBLE")

    def test_partial_updates_do_not_refresh_absent_fields(self):
        self.gate.ingest(packet(), 0)
        self.gate.ingest({"print": {"nozzle_temper": 40}}, 61)
        self.assertEqual(self.gate.eligible(61, True)[0], "MISSING_OR_STALE_DATA")

    def test_single_finish_delta_survives_long_cooldown_and_pulses_once(self):
        self.gate.ingest(packet(gcode_state="RUNNING", mc_percent=90,
                                nozzle_temper=220, nozzle_target_temper=220,
                                bed_target_temper=55), 0)
        self.gate.tick(0, True)
        # RUNNING and unchanged job/bed are never repeated.
        for at in range(1, 181):
            self.gate.ingest({"print": {"nozzle_temper": 220}}, at)
            self.assertFalse(self.gate.tick(at, True))
        self.gate.ingest({"print": {"nozzle_target_temper": 0, "bed_target_temper": 0}}, 180)
        self.gate.ingest({"print": {"gcode_state": "FINISH", "mc_percent": 100}}, 181)
        self.assertFalse(self.gate.tick(181, True))
        for at in range(182, 781):
            self.gate.ingest({"print": {"nozzle_temper": 80}}, at)
            self.assertFalse(self.gate.tick(at, True))
        for at in range(781, 811):
            self.gate.ingest({"print": {"nozzle_temper": 49}}, at)
            self.assertFalse(self.gate.tick(at, True))
        self.gate.ingest({"print": {"nozzle_temper": 49}}, 811)
        self.assertTrue(self.gate.tick(811, True))
        for at in range(812, 901):
            self.gate.ingest({"print": {"nozzle_temper": 40}}, at)
            self.assertEqual(self.gate.tick(at, True), at < 841)
        self.assertEqual(self.gate.reason, "ALREADY_SIGNALED")
        self.assertEqual(self.gate.samples["gcode_state"][1], 181)

    def test_other_updates_cannot_keep_old_nozzle_measurement_fresh(self):
        self.gate.ingest(packet(nozzle_temper=80), 0)
        self.gate.tick(0, True)
        for at in range(1, 62):
            self.gate.ingest({"print": {"bed_temper": 30}}, at)
            self.assertFalse(self.gate.tick(at, True))
        self.assertEqual(self.gate.reason, "MISSING_OR_STALE_DATA")
        self.assertEqual(self.gate.snapshot(61)["stale_fields"], ["nozzle_temper"])

    def test_silent_stream_invalidates_finish_even_when_mqtt_stays_connected(self):
        self.gate.ingest(packet(nozzle_temper=80), 0)
        for at in range(62):
            self.assertFalse(self.gate.tick(at, True))
        self.assertEqual(self.gate.samples, {})
        self.assertIsNone(self.gate.completion_job)
        self.assertFalse(self.advance(62, 100))
        self.assertEqual(self.gate.reason, "WAITING_COMPLETION_EDGE")

    def test_new_job_delta_does_not_inherit_finished_job_fields(self):
        self.gate.ingest(packet(), 0)
        self.gate.ingest({"print": {"subtask_id": "124", "gcode_state": "RUNNING"}}, 1)
        self.assertFalse(self.gate.tick(1, True))
        self.assertNotIn("nozzle_target_temper", self.gate.samples)
        self.assertIsNone(self.gate.completion_job)

    def test_delta_heater_restart_resets_stability(self):
        self.advance(end=29)
        self.gate.ingest({"print": {"nozzle_target_temper": 220}}, 29)
        self.assertFalse(self.gate.tick(29, True))
        self.assertEqual(self.gate.reason, "WAITING_FOR_COOLDOWN")
        self.assertIsNone(self.gate.since)
        self.gate.ingest({"print": {"nozzle_target_temper": 0}}, 30)
        self.assertFalse(self.gate.tick(30, True))
        for at in range(31, 60):
            self.gate.ingest({"print": {"nozzle_temper": 40}}, at)
            self.assertFalse(self.gate.tick(at, True))
        self.assertTrue(self.gate.tick(60, True))

    def test_delta_running_cancels_pending_completion(self):
        self.advance(end=29)
        self.gate.ingest({"print": {"gcode_state": "RUNNING"}}, 29)
        self.assertFalse(self.gate.tick(29, True))
        self.assertIsNone(self.gate.completion_job)

    def test_brief_unsafe_sample_resets_even_within_same_tick(self):
        self.advance(end=29)
        self.gate.ingest(packet(nozzle_temper=52), 29)
        self.gate.ingest(packet(), 29)
        self.assertFalse(self.gate.tick(29, True))
        self.assertFalse(self.advance(30, 59))
        self.assertTrue(self.advance(59, 60))

    def test_connection_loss_and_reconnect_requires_new_window(self):
        self.advance(end=25)
        self.assertFalse(self.gate.tick(25, False))
        self.assertFalse(self.advance(26, 56))
        self.assertFalse(self.advance(56, 57))
        self.gate.ingest(packet(gcode_state="RUNNING"), 57)
        self.gate.tick(57, True)
        self.assertTrue(self.advance(58, 89))

    def test_restart_during_cooldown(self):
        self.advance(end=15, data=packet(nozzle_temper=80))
        self.gate = Gate(self.config, Store(self.store.path))
        self.assertFalse(self.advance(15, 45))
        self.assertFalse(self.advance(45, 46))
        self.assertEqual(self.gate.reason, "WAITING_COMPLETION_EDGE")

    def test_pulse_expires_while_status_stays_completed(self):
        self.assertTrue(self.advance())
        self.assertTrue(self.advance(31, 60))
        self.assertFalse(self.advance(60, 61))
        self.assertEqual(self.gate.reason, "PULSE_COMPLETE")
        self.assertFalse(self.advance(61, 250))
        self.assertEqual(self.gate.reason, "ALREADY_SIGNALED")

    def test_new_job_id_without_completion_edge_cannot_signal(self):
        self.advance()
        self.advance(31, 61)
        self.assertFalse(self.advance(61, 100, packet(subtask_id="124")))
        self.assertEqual(self.gate.reason, "WAITING_COMPLETION_EDGE")

    def test_startup_completed_does_not_signal(self):
        self.gate = Gate(self.config, self.store)
        self.assertFalse(self.advance(end=100))
        self.assertEqual(self.gate.reason, "WAITING_COMPLETION_EDGE")

    def test_unknown_then_completed_does_not_rearm(self):
        self.gate.ingest(packet(gcode_state="UNKNOWN"), 0)
        self.gate.tick(0, True)
        self.assertFalse(self.advance(1, 100))

    def test_unsafe_temperature_cancels_pulse_early(self):
        self.advance()
        self.gate.ingest(packet(nozzle_temper=60), 31)
        self.assertFalse(self.gate.tick(31, True))
        self.assertFalse(self.advance(32, 100))

    def test_already_signaled_job_not_replayed_after_restart(self):
        self.assertTrue(self.advance())
        self.gate = Gate(self.config, Store(self.store.path))
        self.assertFalse(self.advance())
        self.assertEqual(self.gate.reason, "ALREADY_SIGNALED")

    def test_next_job_can_signal(self):
        self.advance()
        self.gate.ingest(packet(subtask_id="124", gcode_state="RUNNING"), 31)
        self.assertFalse(self.gate.tick(31, True))
        self.assertTrue(self.advance(32, 63, packet(subtask_id="124")))

    def test_job_change_does_not_leave_previous_true_value(self):
        self.advance()
        self.gate.ingest(packet(subtask_id="124"), 31)
        self.assertFalse(self.gate.tick(31, True))

    def test_invalid_job_id(self):
        for value in (None, 0, "0", "", True, "-1", "abc"):
            self.gate.ingest(packet(subtask_id=value), 0)
            self.assertNotEqual(self.gate.eligible(0, True)[0], "ELIGIBLE")

    def test_retained_message_does_not_initialize(self):
        self.gate.ingest(packet(), 0, retained=True)
        self.assertFalse(self.gate.tick(0, True))

    def test_event_loop_gap_discards_cached_data(self):
        self.advance(end=10)
        self.assertFalse(self.gate.tick(50, True))
        self.assertEqual(self.gate.samples, {})

    def test_write_error_prevents_true(self):
        self.advance(end=30)
        with patch.object(self.store, "consume", side_effect=OSError):
            with self.assertRaises(OSError):
                self.gate.tick(30, True)
        self.assertFalse(self.gate.value)

    def test_corrupt_state_is_not_silently_overwritten(self):
        self.store.path.write_text("broken")
        with self.assertRaises(ValueError):
            Store(self.store.path)

    def test_packed_temperature_layout(self):
        data = packet()
        data["print"]["device"] = {"bed": {"info": {"temp": 30}},
            "extruder": {"info": [{"id": 0, "temp": (60 << 16) | 40}]}}
        decoded = decode(data)
        self.assertEqual(decoded["nozzle_target_temper"], 60)
        self.gate.ingest(data, 0)
        self.assertNotEqual(self.gate.eligible(0, True)[0], "ELIGIBLE")

    def test_malformed_layout_invalidates(self):
        self.advance()
        self.gate.ingest({"print": {"device": {"bed": None}}}, 31)
        self.assertFalse(self.gate.value)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.config = Config.load({})
        self.gate = Mock()
        self.gate.tick.return_value = False
        self.connections = Connections(self.config, self.gate)

    def test_signature_vector(self):
        client_id, user, password = tuya_credentials("dev", "secret", 1700000000)
        import hmac, hashlib
        expected = hmac.new(b"secret", b"deviceId=dev,timestamp=1700000000,secureMode=1,accessType=1", hashlib.sha256).hexdigest()
        self.assertEqual(password, expected)
        self.assertEqual(client_id, "tuyalink_dev")
        self.assertEqual(user, "dev|signMethod=hmacSha256,timestamp=1700000000,secureMode=1,accessType=1")

    def test_boolean_property_report(self):
        body = report("bambu_off", True, "id", 123)
        self.assertIs(body["data"]["bambu_off"]["value"], True)
        self.assertEqual(body["sys"], {"ack": 1})

    def test_bambu_connection_only_subscribes(self):
        client = Mock()
        client.subscribe.return_value = (0, 3)
        self.connections.on_connect("bambu", client, SimpleNamespace(is_failure=False))
        client.subscribe.assert_called_once_with(f"device/{self.config.serial}/report", qos=0)
        client.publish.assert_not_called()

    def test_false_cloud_ack_required_before_ready(self):
        self.connections.pending = ("id", False, 0)
        message = SimpleNamespace(topic="tylink//thing/property/report_response", retain=False,
                                  payload=b'{"msgId":"id","code":0}')
        self.connections.on_message("tuya", message)
        self.assertTrue(self.connections.ready)
        self.gate.invalidate.assert_called_once()

    def test_wrong_ack_does_not_unlock(self):
        self.connections.pending = ("id", False, 0)
        message = SimpleNamespace(topic="tylink//thing/property/report_response", retain=False,
                                  payload=b'{"msgId":"other","code":0}')
        self.connections.on_message("tuya", message)
        self.assertFalse(self.connections.ready)

    def test_error_ack_closes_connection(self):
        self.connections.pending = ("id", False, 0)
        message = SimpleNamespace(topic="tylink//thing/property/report_response", retain=False,
                                  payload=b'{"msgId":"id","code":1002}')
        self.connections.on_message("tuya", message)
        self.assertFalse(self.connections.ready)
        self.assertIsNone(self.connections.pending)

    def test_no_retained_or_retried_publish(self):
        client = Mock()
        client.publish.return_value.rc = 0
        self.connections.clients["tuya"] = client
        self.connections.subscribed["tuya"] = True
        self.connections.send(True)
        self.connections.send(True)
        self.assertEqual(client.publish.call_count, 1)
        self.assertEqual(client.publish.call_args.kwargs, {"qos": 0, "retain": False})

    def test_close_discards_client_and_pending_message(self):
        self.connections.clients["tuya"] = Mock()
        self.connections.pending = ("id", True, 0)
        self.connections.close("tuya")
        self.assertIsNone(self.connections.clients["tuya"])
        self.assertIsNone(self.connections.pending)
        self.assertFalse(self.connections.ready)

    def test_expired_pulse_reports_false_to_tuya(self):
        for name in ("bambu", "tuya"):
            client = Mock()
            client.loop.return_value = 0
            client.publish.return_value.rc = 0
            self.connections.clients[name] = client
            self.connections.connected[name] = True
            self.connections.subscribed[name] = True
        self.connections.ready = True
        self.connections.last_value = True
        self.gate.tick.return_value = False
        self.connections.pump()
        call = self.connections.clients["tuya"].publish.call_args
        self.assertIs(json.loads(call.args[1])["data"]["bambu_off"]["value"], False)
        self.connections.clients["bambu"].publish.assert_not_called()


class ConfigTests(unittest.TestCase):
    def test_demo_needs_no_credentials(self):
        self.assertEqual(Config.load({}).mode, "demo")

    def test_live_requires_credentials(self):
        with self.assertRaises(ValueError):
            Config.load({"MODE": "live"})

    def test_unsafe_numbers_rejected(self):
        for name, value in (("STABLE_SECONDS", "29"), ("SAFE_NOZZLE_TEMPERATURE", "51"),
                            ("SAFE_NOZZLE_TEMPERATURE", "nan"), ("MAX_DATA_AGE_SECONDS", "inf")):
            with self.assertRaises(ValueError):
                Config.load({name: value})

    def test_env_helpers_preserve_existing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path, example = Path(temp) / ".env", Path(temp) / ".env.example"
            path.write_text("MODE=live\nEXISTING=value\n")
            example.write_text("MODE=demo\nPORT=8080\n")
            prepare(path, example)
            save_env({"BAMBU_ACCESS_TOKEN": "local-test-token"}, path)
            text = path.read_text()
            self.assertIn("MODE=live", text)
            self.assertIn("EXISTING=value", text)
            self.assertEqual(text.count("PORT="), 1)
            self.assertIn("BAMBU_ACCESS_TOKEN='local-test-token'", text)

    def test_docker_build_context_excludes_credentials_and_ha(self):
        text = Path("Dockerfile").read_text()
        self.assertNotIn("COPY . ", text)
        self.assertIn("COPY bambuoff ./bambuoff", text)
        self.assertTrue(Path(".dockerignore").read_text().startswith("**"))

    def test_compose_contains_no_plug_control_or_ha(self):
        import yaml
        compose = yaml.safe_load(Path("compose.yaml").read_text())
        self.assertEqual(list(compose["services"]), ["bambuoff"])
        self.assertNotIn("home-assistant", str(compose))
        self.assertNotIn("PLUG", str(compose))
