"""Environment-only configuration; never render credentials."""
from dataclasses import dataclass
import math
import os
import re


def bounded(env, name, default, low, high):
    try:
        value = float(env.get(name, default))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {name}") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid {name}")
    return value


@dataclass(repr=False)
class Config:
    mode: str
    serial: str
    username: str
    token: str
    bambu_host: str
    device_id: str
    device_secret: str
    tuya_host: str
    property_code: str
    limit: float
    stable: float
    pulse: float
    max_age: float
    state_file: str

    @classmethod
    def load(cls, env=None):
        env = os.environ if env is None else env
        mode = env.get("MODE", "demo")
        if mode not in ("demo", "live"):
            raise ValueError("MODE must be demo or live")
        region = env.get("BAMBU_REGION", "global")
        if region not in ("global", "china"):
            raise ValueError("BAMBU_REGION must be global or china")
        required = ("BAMBU_SERIAL", "BAMBU_USERNAME", "BAMBU_ACCESS_TOKEN",
                    "TUYA_DEVICE_ID", "TUYA_DEVICE_SECRET")
        if mode == "live":
            for name in required:
                if not env.get(name, "").strip():
                    raise ValueError(f"Missing {name}; see .env.example")
            for name in ("BAMBU_SERIAL", "BAMBU_USERNAME", "TUYA_DEVICE_ID"):
                if not re.fullmatch(r"[A-Za-z0-9_-]+", env[name]):
                    raise ValueError(f"Invalid {name}")
        code = env.get("TUYA_PROPERTY_CODE", "bambu_off")
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", code):
            raise ValueError("Invalid TUYA_PROPERTY_CODE")
        host = env.get("TUYA_MQTT_HOST", "m1.tuyaeu.com")
        if host not in ("m1.tuyaeu.com", "m1.tuyaus.com", "m1.tuyacn.com",
                        "m1.tuyain.com", "m1-sg.lifeaiot.com"):
            raise ValueError("Unsupported TUYA_MQTT_HOST; use the device's TuyaLink endpoint")
        return cls(mode, *(env.get(name, "") for name in required[:3]),
            "cn.mqtt.bambulab.com" if region == "china" else "us.mqtt.bambulab.com",
            env.get("TUYA_DEVICE_ID", ""), env.get("TUYA_DEVICE_SECRET", ""), host, code,
            bounded(env, "SAFE_NOZZLE_TEMPERATURE", 50, 1, 50),
            bounded(env, "STABLE_SECONDS", 30, 30, 3600),
            bounded(env, "PULSE_SECONDS", 30, 1, 120),
            bounded(env, "MAX_DATA_AGE_SECONDS", 60, 5, 120),
            env.get("STATE_FILE", "runtime/bambuoff/state.json"))
