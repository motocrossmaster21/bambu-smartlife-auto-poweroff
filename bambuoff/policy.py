"""Session-scoped delta telemetry, fresh nozzle readings and durable deduplication."""
import hashlib
import json
import math
import os
from pathlib import Path

FIELDS = ("gcode_state", "subtask_id", "mc_percent", "nozzle_temper",
          "nozzle_target_temper", "bed_temper", "bed_target_temper")


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def decode(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("print"), dict):
        return None
    data = payload["print"].copy()
    device = data.get("device", {})
    if not isinstance(device, dict):
        raise ValueError("Invalid telemetry")
    bed = device.get("bed", {}).get("info", {})
    if "temp" in bed:
        packed = bed["temp"]
        if type(packed) is not int or not 0 <= packed <= 0xFFFFFFFF:
            raise ValueError("Invalid packed temperature")
        data["bed_temper"], data["bed_target_temper"] = packed & 0xFFFF, packed >> 16
    extruder = device.get("extruder", {}).get("info")
    if extruder is not None:
        # This project targets the single-nozzle P1S only.
        if not isinstance(extruder, list) or len(extruder) != 1 or extruder[0].get("id") != 0:
            raise ValueError("Unsupported extruder layout")
        packed = extruder[0].get("temp")
        if type(packed) is not int or not 0 <= packed <= 0xFFFFFFFF:
            raise ValueError("Invalid packed temperature")
        data["nozzle_temper"], data["nozzle_target_temper"] = packed & 0xFFFF, packed >> 16
    return data


class Store:
    def __init__(self, filename):
        self.path = Path(filename)
        self.last_job = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("last_job"), str):
                raise ValueError("Invalid state file; restore backup, do not silently reset")
            self.last_job = data["last_job"]

    def consume(self, job):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"version": 1, "last_job": job}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        # Make the rename durable on Linux before emitting a cloud event.
        if os.name == "posix":
            descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.last_job = job


class Gate:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.samples = {}
        self.since = None
        self.last_tick = None
        self.active_job = None
        self.value = False
        self.reason = "WAITING_FOR_DATA"
        self.last_status = None
        self.completion_job = None
        self.pulse_started = None
        self.last_report = None

    def invalidate(self):
        self.samples.clear()
        self.since = None
        self.active_job = None
        self.value = False
        self.last_status = None
        self.completion_job = None
        self.pulse_started = None
        self.last_report = None

    def expire_stream(self, now):
        # A cloud socket alone does not prove that printer reports still arrive.
        # Never merge new deltas into state from before an unobserved interval.
        if self.last_report is not None and not 0 <= now - self.last_report <= self.config.max_age:
            self.invalidate()

    def ingest(self, payload, now, retained=False):
        if retained:
            return
        try:
            data = decode(payload)
            if data is None:
                return
        except (ValueError, TypeError, AttributeError, KeyError):
            self.invalidate()
            return
        if not any(key in data for key in FIELDS):
            return
        self.expire_stream(now)
        self.last_report = now
        prior_task = self.samples.get("subtask_id", (None,))[0]
        task = data.get("subtask_id", prior_task)
        if prior_task is not None and task != prior_task:
            self.invalidate()
            self.last_report = now
        status = data.get("gcode_state", self.last_status)
        # A completed value at startup/reconnect is not a completion edge.
        # Only an observed active print transitioning to FINISH arms this job.
        if "gcode_state" in data:
            if status == "FINISH" and self.last_status in ("RUNNING", "PREPARE", "PAUSE"):
                self.completion_job = str(task) if task == prior_task else None
            elif status != "FINISH":
                self.completion_job = None
            self.last_status = status
        # A status-only FINISH delta must not erase unchanged targets/job data.
        # A different job, disconnect or silent stream DOES erase the cache.
        for key in FIELDS:
            if key in data:
                self.samples[key] = (data[key], now)
        if self.eligible(now, True)[0] != "ELIGIBLE":
            self.since, self.active_job, self.value = None, None, False

    def eligible(self, now, connected):
        if not connected:
            return "CLOUD_DISCONNECTED", None
        if any(key not in self.samples for key in FIELDS):
            return "MISSING_OR_STALE_DATA", None
        if not 0 <= now - self.samples["nozzle_temper"][1] <= self.config.max_age:
            return "MISSING_OR_STALE_DATA", None
        data = {key: value[0] for key, value in self.samples.items()}
        if data["gcode_state"] != "FINISH":
            return "WAITING_FOR_FINISH", None
        task = data["subtask_id"]
        if isinstance(task, bool) or not str(task).isdigit() or int(task) <= 0:
            return "MISSING_CLOUD_JOB_ID", None
        if number(data["mc_percent"]) != 100:
            return "INCOMPLETE_PROGRESS", None
        values = {}
        for key in FIELDS[3:]:
            value = number(data[key])
            maximum = 400 if key.startswith("nozzle") else 150
            if value is None or not 0 <= value <= maximum:
                return "INVALID_TEMPERATURE", None
            values[key] = value
        if (values["nozzle_temper"] > self.config.limit or values["nozzle_target_temper"] != 0
                or values["bed_target_temper"] != 0):
            return "WAITING_FOR_COOLDOWN", None
        job = hashlib.sha256(f"{self.config.serial}:{task}".encode()).hexdigest()
        return "ELIGIBLE", job

    def tick(self, now, connected):
        if not connected:
            self.invalidate()
        if self.last_tick is not None and (now < self.last_tick or now - self.last_tick > 3):
            self.invalidate()
        self.expire_stream(now)
        self.last_tick = now
        reason, job = self.eligible(now, connected)
        if reason != "ELIGIBLE":
            self.since = None
            self.active_job = None
            self.value = False
            self.reason = reason
        elif self.active_job == job:
            if now - self.pulse_started >= self.config.pulse:
                self.value, self.reason = False, "PULSE_COMPLETE"
                self.active_job, self.since = None, None
            else:
                self.value, self.reason = True, "SAFE"
        elif self.store.last_job == job:
            self.value, self.reason = False, "ALREADY_SIGNALED"
            self.since = None
        elif self.completion_job != str(self.samples["subtask_id"][0]):
            self.value, self.reason = False, "WAITING_COMPLETION_EDGE"
            self.since = None
        else:
            if self.since is None:
                self.since = now
            self.reason = "STABILIZING"
            if now - self.since >= self.config.stable:
                # Durable at-most-once intent: prefer a missed event to a replay.
                self.store.consume(job)
                self.active_job, self.value, self.reason = job, True, "SAFE"
                self.pulse_started = now
        return self.value

    def snapshot(self, now):
        return {"bambu_off": self.value, "phase": self.reason,
            "missing_fields": [key for key in FIELDS if key not in self.samples],
            "stale_fields": [key for key in ("nozzle_temper",) if key in self.samples
                and not 0 <= now - self.samples[key][1] <= self.config.max_age],
            "pulse_remaining_seconds": round(max(0, self.config.pulse - (now - self.pulse_started)), 1)
                if self.value and self.pulse_started is not None else 0,
            "stable_seconds": round(max(0, now - self.since), 1) if self.since is not None else 0,
            "telemetry": {key: {"value": val, "age_seconds": round(now - at, 1),
                "freshness_policy": "recent_measurement" if key == "nozzle_temper" else "session_cached"}
                for key, (val, at) in self.samples.items() if key != "subtask_id"}}
