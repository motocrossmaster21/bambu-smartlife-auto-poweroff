"""Exercise deployed policy code, including the ten requested scenarios."""
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1] / "homeassistant/custom_components/p1s_guard/policy.py"
spec = importlib.util.spec_from_file_location("guard_policy", path)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


def readings(**updates):
    values = dict(status="finish", nozzle="49", nozzle_target="0", bed="30",
                  bed_target="0", progress="100", online="on", plug="on")
    values.update(updates)
    return {key: policy.Reading(value, 0, unit="°C" if key in
            ("nozzle", "nozzle_target", "bed", "bed_target") else None)
            for key, value in values.items()}


def eligible(data=None, **kwargs):
    options = dict(armed=True, fault=False, bridge=True, limit=50, max_age=60)
    options.update(kwargs)
    return policy.evaluate(data if data is not None else readings(), **options) == "ELIGIBLE"


class PolicyTests(unittest.TestCase):
    def test_01_disarmed(self):
        self.assertFalse(eligible(armed=False))

    def test_02_non_success_statuses(self):
        for status in ("running", "prepare", "pause", "idle", "unknown", "offline", "FINISH", "completed"):
            with self.subTest(status=status):
                self.assertFalse(eligible(readings(status=status)))

    def test_03_hot_nozzle(self):
        self.assertFalse(eligible(readings(nozzle="80")))

    def test_04_safe_after_full_duration(self):
        clock = policy.Stability(30)
        for second in range(30):
            self.assertFalse(clock.update(eligible(), second))
        self.assertTrue(clock.update(eligible(), 30))

    def test_05_failed_print(self):
        self.assertFalse(eligible(readings(status="failed")))

    def test_06_unavailable_status(self):
        self.assertFalse(eligible(readings(status="unavailable")))

    def test_07_bad_temperatures(self):
        for key in ("nozzle", "nozzle_target", "bed", "bed_target"):
            for value in ("unknown", "unavailable", "nan", "inf", "-inf", "-1", "", "abc"):
                with self.subTest(key=key, value=value):
                    self.assertFalse(eligible(readings(**{key: value})))

    def test_08_brief_temperature_drop_resets_timer(self):
        clock = policy.Stability(30)
        for second in range(20):
            clock.update(eligible(), second)
        self.assertFalse(clock.update(eligible(readings(nozzle="52")), 20))
        for second in range(21, 51):
            self.assertFalse(clock.update(eligible(), second))
        self.assertTrue(clock.update(eligible(), 51))

    def test_09_heater_targets(self):
        self.assertFalse(eligible(readings(nozzle_target="60")))
        self.assertFalse(eligible(readings(bed_target="60")))

    def test_10_restart_requires_new_interval(self):
        before = policy.Stability(30)
        for second in range(40):
            before.update(True, second)
        after = policy.Stability(30)
        self.assertFalse(after.update(True, 40))
        self.assertFalse(after.update(True, 41))

    def test_all_missing_stale_restored_and_preboot_readings_block(self):
        for key in readings():
            data = readings()
            del data[key]
            self.assertFalse(eligible(data))
        for key in set(readings()) - {"plug"}:
            original = readings()[key]
            for age, since_start, restored in ((61, True, False), (-1, True, False),
                                              (0, False, False), (0, True, True)):
                data = readings()
                data[key] = policy.Reading(original.value, age, since_start, original.unit, restored)
                self.assertFalse(eligible(data))

    def test_offline_and_fault(self):
        self.assertFalse(eligible(bridge=False))
        self.assertFalse(eligible(fault=True))
        self.assertFalse(eligible(readings(online="off")))
        self.assertFalse(eligible(readings(plug="unavailable")))
        self.assertFalse(eligible(readings(plug="off")))

    def test_progress_and_celsius(self):
        self.assertFalse(eligible(readings(progress="99")))
        data = readings()
        data["nozzle"] = policy.Reading("49", 0, unit="°F")
        self.assertFalse(eligible(data))

    def test_boundary_and_late_arming(self):
        self.assertTrue(eligible(readings(nozzle="50")))
        self.assertFalse(eligible(readings(nozzle="50.1")))
        clock = policy.Stability(30)
        self.assertFalse(clock.update(eligible(armed=False), 0))
        self.assertFalse(clock.update(eligible(), 1))
        for second in range(2, 31):
            self.assertFalse(clock.update(eligible(), second))
        self.assertTrue(clock.update(eligible(), 31))

    def test_event_loop_gap_cannot_count_as_observation(self):
        clock = policy.Stability(30)
        clock.update(True, 0)
        self.assertFalse(clock.update(True, 60))

    def test_disconnect_resets_stability(self):
        clock = policy.Stability(30)
        for second in range(30):
            clock.update(True, second)
        self.assertFalse(clock.update(eligible(bridge=False), 30))
        self.assertFalse(clock.update(True, 31))


if __name__ == "__main__":
    unittest.main()
