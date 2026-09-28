"""Local status page and standalone service. Demo never imports an MQTT adapter."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import signal
import socket
import threading
import time

from .config import Config
from .policy import Gate, Store

PHASE_LABELS = {
    "WAITING_FOR_DATA": "Warte auf Druckerdaten",
    "CLOUD_DISCONNECTED": "Cloud-Verbindung unterbrochen – kein Abschaltsignal",
    "MISSING_OR_STALE_DATA": "Druckerdaten fehlen oder sind zu alt",
    "WAITING_FOR_FINISH": "Warte auf erfolgreichen Druckabschluss",
    "MISSING_CLOUD_JOB_ID": "Gültige Druckauftrag-ID fehlt",
    "INCOMPLETE_PROGRESS": "Warte auf 100 % Druckfortschritt",
    "INVALID_TEMPERATURE": "Temperaturdaten sind ungültig",
    "WAITING_FOR_COOLDOWN": "Warte auf Abkühlung und ausgeschaltete Heizungen",
    "WAITING_COMPLETION_EDGE": "Warte auf einen neu beobachteten Druckabschluss",
    "STABILIZING": "Abschaltbedingungen erfüllt – Sicherheitswartezeit läuft",
    "SAFE": "Abschaltsignal EIN – Impuls läuft",
    "PULSE_COMPLETE": "Abschaltsignal zurückgesetzt – Impuls beendet",
    "ALREADY_SIGNALED": "Für diesen Druck wurde bereits ein Abschaltsignal ausgelöst",
}

PAGE = """<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BambuOff</title>
<style>body{font:18px system-ui;max-width:700px;margin:10vh auto;padding:24px;background:#122027;color:#edf6f6}
h1{font-size:42px}#signal{font-size:32px;color:#77dfb6}pre{white-space:pre-wrap;font-size:15px}small{color:#abc}</style>
<h1>BambuOff</h1><p id="signal">Verbinde …</p><p id="phase"></p><p id="cloud"></p><p id="mode"></p>
<details><summary>Technische Details</summary><pre id="state"></pre></details>
<small>Diese Seite zeigt den Status. Aktionen auf der Steckdose richtest du in Smart Life ein.</small>
<script>async function refresh(){try{const r=await fetch('/status',{cache:'no-store'});const s=await r.json();
document.querySelector('#signal').textContent=s.bambu_off?'Abschaltsignal: EIN':'Abschaltsignal: AUS';
document.querySelector('#phase').textContent=s.phase_label;
document.querySelector('#cloud').textContent=s.mode==='demo'?'Tuya: im Demo-Modus nicht verbunden':
    s.tuya_confirmed_bambu_off===true?'Zuletzt von Tuya bestätigtes Abschaltsignal: EIN':
    s.tuya_confirmed_bambu_off===false?'Zuletzt von Tuya bestätigtes Abschaltsignal: AUS':
    'Tuya: noch kein bestätigter Signalwert';
document.querySelector('#mode').textContent=s.mode==='demo'?'DEMO · simulierte Werte · keine Cloud-Verbindung':'LIVE · Bambu Cloud → TuyaLink';
document.querySelector('#state').textContent=JSON.stringify(s,null,2)}catch(e){document.querySelector('#signal').textContent='App nicht erreichbar'}}
refresh();setInterval(refresh,1000)</script></html>"""


class Status:
    snapshot = {}
    updated = 0


class StatusServer(ThreadingHTTPServer):
    """Bound workers and connection lifetime, including trickled HTTP headers."""

    max_connections = 8
    request_queue_size = 8
    idle_timeout = 2
    connection_lifetime = 5

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        # Never block the accept loop or create a waiting worker when full.
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request.settimeout(self.idle_timeout)
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    @staticmethod
    def expire_connection(request):
        # shutdown interrupts a blocked read/write; the worker owns close().
        try:
            request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def process_request_thread(self, request, client_address):
        deadline = threading.Timer(self.connection_lifetime, self.expire_connection,
                                   args=(request,))
        deadline.daemon = True
        try:
            deadline.start()
            self.finish_request(request, client_address)
        except OSError:
            # Timeouts, expired connections and clients disconnecting are normal.
            pass
        except Exception:
            self.handle_error(request, client_address)
        finally:
            deadline.cancel()
            if deadline.ident is not None:
                deadline.join()
            self.shutdown_request(request)
            self.slots.release()

    def handle_error(self, request, client_address):
        # Do not print client input or exception payloads to container logs.
        logging.error("HTTP request failed")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            payload, kind, code = PAGE.encode(), "text/html; charset=utf-8", 200
        elif self.path == "/status":
            payload, kind, code = json.dumps(Status.snapshot).encode(), "application/json", 200
        elif self.path == "/health":
            payload, kind = b"ok", "text/plain"
            code = 200 if time.monotonic() - Status.updated < 25 else 503
        else:
            self.send_error(404)
            return
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class DemoStore:
    last_job = None

    def consume(self, job):
        self.last_job = job


def demo_message(elapsed, cycle):
    return {"print": {"gcode_state": "RUNNING" if elapsed < 5 else "FINISH",
        "subtask_id": str(cycle + 1), "mc_percent": 50 if elapsed < 5 else 100,
        "nozzle_temper": 180 if elapsed < 5 else 80 if elapsed < 10 else 40,
        "nozzle_target_temper": 200 if elapsed < 5 else 0,
        "bed_temper": 35, "bed_target_temper": 60 if elapsed < 5 else 0}}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = Config.load()
        gate = Gate(config, DemoStore() if config.mode == "demo" else Store(config.state_file))
    except (ValueError, OSError):
        logging.error("Configuration/state invalid. Check ENV and state file locally; see README.")
        return 1
    connections = None
    if config.mode == "live":
        from .mqtt import Connections
        connections = Connections(config, gate)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    # Native Python binds to loopback; Docker sets HTTP_BIND explicitly below.
    server = StatusServer((os.environ.get("HTTP_BIND", "127.0.0.1"), 8080), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start, previous = time.monotonic(), None
    logging.info("BambuOff started in %s mode", config.mode)
    try:
        while not stop.is_set():
            now = time.monotonic()
            if connections:
                connections.pump()
            else:
                cycle_length = int(config.stable + config.pulse + 25)
                cycle, elapsed = divmod(int(now - start), cycle_length)
                gate.ingest(demo_message(elapsed, cycle), now)
                gate.tick(now, True)
            Status.snapshot = {"mode": config.mode, **gate.snapshot(time.monotonic()),
                "phase_label": PHASE_LABELS.get(gate.reason, "Unbekannter Status"),
                "tuya_confirmed_bambu_off": connections.last_value if connections else None}
            Status.updated = time.monotonic()
            if previous != gate.reason:
                logging.info("BambuOff: %s", gate.reason)
                previous = gate.reason
            stop.wait(0.1)
    except Exception:
        # Never include exceptions containing credentials or received payloads.
        logging.error("Service stopped after an internal error; no new safety signal will be sent")
        return 1
    finally:
        if connections:
            connections.shutdown()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
