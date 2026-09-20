"""Validate the deployed settings validators without importing the HA runtime."""
import ast
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
import unittest
import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / "homeassistant/custom_components/p1s_guard/__init__.py").read_text())
nodes = [node for node in tree.body if
         (isinstance(node, ast.FunctionDef) and node.name == "finite") or
         (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
          ("KEYS", "SETTINGS") for target in node.targets))]
namespace = dict(vol=vol, cv=SimpleNamespace(entity_id=str, string=str), isfinite=isfinite)
exec(compile(ast.Module(body=nodes, type_ignores=[]), "guard_settings", "exec"), namespace)


class SchemaTests(unittest.TestCase):
    def settings(self):
        values = {f"{key}_entity": f"sensor.{key}" for key in namespace["KEYS"]}
        values.update(online_entity="binary_sensor.online", plug_entity="switch.real_plug",
            bridge_entry_id="replace_with_bridge_config_entry_id", safe_temperature="50",
            stable_seconds="30", max_age_seconds="60", off_timeout_seconds="20")
        return values

    def test_env_numbers_are_coerced(self):
        self.assertEqual(namespace["SETTINGS"](self.settings())["safe_temperature"], 50)

    def test_nan_infinity_and_unsafe_limits_rejected(self):
        for key in ("safe_temperature", "stable_seconds", "max_age_seconds", "off_timeout_seconds"):
            for value in ("nan", "inf", "-inf", "0", "invalid"):
                values = self.settings()
                values[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(vol.Invalid):
                    namespace["SETTINGS"](values)
        for key, value in (("stable_seconds", "29"), ("safe_temperature", "51")):
            values = self.settings()
            values[key] = value
            with self.assertRaises(vol.Invalid):
                namespace["SETTINGS"](values)

    def test_wrong_domains_and_proxy_as_target_rejected(self):
        for key, value in (("plug_entity", "sensor.plug"),
                           ("plug_entity", "switch.bambu_auto_power_off"),
                           ("online_entity", "sensor.online"),
                           ("status_entity", "input_boolean.fake_status")):
            values = self.settings()
            values[key] = value
            with self.assertRaises(vol.Invalid):
                namespace["SETTINGS"](values)
