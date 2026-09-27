import http.client
import io
import json
import unittest
from unittest.mock import patch

from scripts.smoke_demo import check


class SmokeDemoTests(unittest.TestCase):
    def run_check(self, fetch, timeout=40):
        self.now = 0

        def sleep(seconds):
            self.now += seconds

        with patch("scripts.smoke_demo.time.monotonic", side_effect=lambda: self.now), \
                patch("scripts.smoke_demo.time.sleep", side_effect=sleep), \
                patch("scripts.smoke_demo.urllib.request.urlopen", side_effect=fetch):
            check(timeout=timeout)

    def response(self, mode="demo"):
        active = 1 <= self.now < 31
        return io.BytesIO(json.dumps({
            "mode": mode, "tuya_confirmed_bambu_off": None,
            "bambu_off": active, "stable_seconds": 30,
            "phase": "SAFE" if active else "ALREADY_SIGNALED",
            "telemetry": {"gcode_state": {"value": "FINISH"}},
        }).encode())

    def test_startup_reset_or_closed_http_response_is_retried(self):
        for error in (ConnectionResetError, http.client.RemoteDisconnected):
            with self.subTest(error=error):
                def fetch(*args, **kwargs):
                    if self.now == 0:
                        raise error("startup")
                    return self.response()
                self.run_check(fetch)

    def test_persistent_reset_still_fails_with_diagnostic(self):
        def fetch(*args, **kwargs):
            raise ConnectionResetError("unavailable")
        with self.assertRaisesRegex(AssertionError, "last transport error: ConnectionResetError"):
            self.run_check(fetch, timeout=2)

    def test_interrupted_pulse_does_not_pass_as_continuously_observed(self):
        def fetch(*args, **kwargs):
            if self.now == 10:
                raise ConnectionResetError("interrupted")
            return self.response()
        with self.assertRaisesRegex(AssertionError, "Complete demo cycle not observed"):
            self.run_check(fetch)

    def test_live_mode_assertion_is_not_retried(self):
        with self.assertRaisesRegex(AssertionError, "must never run against live"):
            self.run_check(lambda *args, **kwargs: self.response(mode="live"))
        self.assertEqual(self.now, 0)
