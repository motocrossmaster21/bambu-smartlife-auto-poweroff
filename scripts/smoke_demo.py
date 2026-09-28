"""Observe the running demo: 30-second gate, signal and return to false."""
import json
import http.client
import time
import urllib.error
import urllib.request


def check(url="http://127.0.0.1:8089", timeout=180):
    deadline = time.monotonic() + timeout
    saw_true = False
    phases = set()
    true_since = None
    measured_full_pulse = False
    previous_value = None
    last_transport_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/status", timeout=2) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            last_transport_error = type(exc).__name__
            # A missing observation must not count towards a continuous pulse.
            previous_value, true_since = None, None
            time.sleep(0.5)
            continue
        assert data["mode"] == "demo", "Smoke check must never run against live mode"
        assert data["tuya_confirmed_bambu_off"] is None, "Demo must have no cloud publisher"
        phases.add(data["phase"])
        if data["bambu_off"]:
            assert data["phase"] == "SAFE"
            assert data["stable_seconds"] >= 30
            saw_true = True
            if previous_value is False:
                true_since = time.monotonic()
        if previous_value is True and not data["bambu_off"] and true_since is not None:
            assert 28 <= time.monotonic() - true_since <= 32, "Expected a 30-second pulse"
            measured_full_pulse = True
            assert data["telemetry"]["gcode_state"]["value"] == "FINISH", "Reset must occur before next print"
        if saw_true and measured_full_pulse and data["phase"] == "ALREADY_SIGNALED":
            print("Demo passed: 30-second stability gate, 30-second pulse, reset while FINISH stays set; no cloud connection.")
            return
        previous_value = data["bambu_off"]
        time.sleep(0.5)
    raise AssertionError(
        f"Complete demo cycle not observed in {timeout}s; "
        f"observed phases: {sorted(phases)}; last transport error: {last_transport_error}")


if __name__ == "__main__":
    check()
