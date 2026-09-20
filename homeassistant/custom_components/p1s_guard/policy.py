"""Pure fail-closed policy, independent of Home Assistant and cloud libraries."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Reading:
    value: str
    age: float
    since_start: bool = True
    unit: str | None = None
    restored: bool = False


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


def evaluate(readings, *, armed, fault, bridge, limit, max_age):
    if not armed:
        return "DISARMED"
    if fault:
        return "FAULT"
    if not bridge:
        return "BRIDGE_OFFLINE"
    for key in ("status", "nozzle", "nozzle_target", "bed", "bed_target", "progress", "online"):
        reading = readings.get(key)
        if (reading is None or reading.restored or not reading.since_start
                or not 0 <= reading.age <= max_age
                or reading.value in ("unknown", "unavailable", "")):
            return "MISSING_OR_STALE_DATA"
    if readings["online"].value != "on":
        return "PRINTER_OFFLINE"
    plug = readings.get("plug")
    if plug is None or plug.restored or not plug.since_start or plug.value != "on":
        return "PLUG_NOT_ON"
    # Match the integration's raw value, never translated display strings.
    if readings["status"].value != "finish":
        return "WAITING_FOR_FINISH"
    values = {}
    for key in ("nozzle", "nozzle_target", "bed", "bed_target"):
        value = number(readings[key].value)
        if value is None or value < 0 or readings[key].unit != "°C":
            return "INVALID_TEMPERATURE"
        values[key] = value
    if number(readings["progress"].value) != 100:
        return "INCOMPLETE_PROGRESS"
    if values["nozzle"] > limit or values["nozzle_target"] != 0 or values["bed_target"] != 0:
        return "WAITING_FOR_COOLDOWN"
    return "ELIGIBLE"


class Stability:
    """Never restored. A scheduling gap also invalidates the observation window."""
    def __init__(self, duration):
        self.duration = duration
        self.since = None
        self.last_tick = None

    def update(self, eligible, now):
        if self.last_tick is not None and (now < self.last_tick or now - self.last_tick > 3):
            self.since = None
        self.last_tick = now
        if not eligible:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= self.duration
