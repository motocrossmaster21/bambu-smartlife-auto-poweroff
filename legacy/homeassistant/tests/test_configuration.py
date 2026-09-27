"""Structural checks; HA's own schema check is a separate CI/NAS step."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class Loader(yaml.SafeLoader):
    pass


def tagged(loader, node):
    return loader.construct_scalar(node)


Loader.add_constructor("!env_var", tagged)
Loader.add_constructor("!include", tagged)


class ConfigurationTests(unittest.TestCase):
    def test_yaml_and_includes(self):
        paths = [ROOT / "compose.yaml", *ROOT.joinpath("homeassistant").rglob("*.yaml"),
                 ROOT / ".github/workflows/validate.yml"]
        for path in paths:
            with self.subTest(path=path.name):
                yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
        settings = yaml.load((ROOT / "homeassistant/guard.yaml").read_text(), Loader=Loader)
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        env = compose["services"]["homeassistant"]["environment"]
        for expression in settings.values():
            self.assertIn(expression.split()[0], env)

    def test_no_privileged_host_network_or_docker_socket(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        self.assertNotIn("version", compose)
        service = compose["services"]["homeassistant"]
        self.assertFalse(service.get("privileged", False))
        self.assertNotEqual(service.get("network_mode"), "host")
        self.assertNotIn("docker.sock", str(service))

    def test_single_guarded_automation(self):
        automations = yaml.safe_load((ROOT / "homeassistant/automations.yaml").read_text())
        self.assertEqual(automations[0]["mode"], "single")
        self.assertEqual(automations[0]["actions"], [{"action": "p1s_guard.power_off"}])
