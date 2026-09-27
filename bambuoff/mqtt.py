"""Small adapters for the Bambu report topic and the documented TuyaLink protocol.

Connections are pumped in one thread. A reconnect ALWAYS creates a new client;
no stale MQTT publish can be replayed by paho's reconnect queue.
"""
import hashlib
import hmac
import json
import logging
import ssl
import time
import uuid

from paho.mqtt import client as mqtt

LOG = logging.getLogger(__name__)


def tuya_credentials(device_id, secret, timestamp):
    plain = f"deviceId={device_id},timestamp={timestamp},secureMode=1,accessType=1"
    username = f"{device_id}|signMethod=hmacSha256,timestamp={timestamp},secureMode=1,accessType=1"
    password = hmac.new(secret.encode(), plain.encode(), hashlib.sha256).hexdigest()
    return f"tuyalink_{device_id}", username, password


def report(code, value, message_id, timestamp):
    return {"msgId": message_id, "time": timestamp, "sys": {"ack": 1},
            "data": {code: {"value": bool(value), "time": timestamp}}}


def make_client(client_id, username, password):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                         clean_session=True, protocol=mqtt.MQTTv311)
    client.username_pw_set(username, password)
    client.tls_set_context(ssl.create_default_context())
    client.connect_timeout = 5
    return client


class Connections:
    def __init__(self, config, gate):
        self.config, self.gate = config, gate
        self.clients = {"bambu": None, "tuya": None}
        self.next_attempt = {"bambu": 0, "tuya": 0}
        self.connected = {"bambu": False, "tuya": False}
        self.subscribed = {"bambu": False, "tuya": False}
        self.subscription_ids = {}
        self.ready = False
        self.pending = None
        self.last_value = None
        self.last_ack = None
        self.opened_at = {}

    def close(self, name):
        client = self.clients[name]
        self.clients[name] = None
        self.connected[name] = self.subscribed[name] = False
        if name == "tuya":
            self.ready, self.pending, self.last_value = False, None, None
        self.gate.invalidate()
        self.next_attempt[name] = time.monotonic() + 5
        if client:
            try:
                client.disconnect()
                client.loop(timeout=0.01)
            except (OSError, ValueError):
                pass

    def open(self, name):
        config = self.config
        if name == "bambu":
            client = make_client(f"bambuoff_{uuid.uuid4().hex[:16]}", config.username, config.token)
            host = config.bambu_host
        else:
            args = tuya_credentials(config.device_id, config.device_secret, int(time.time()))
            client = make_client(*args)
            host = config.tuya_host
        self.clients[name] = client
        self.opened_at[name] = time.monotonic()
        client.on_connect = lambda c, u, flags, reason, props: self.on_connect(name, c, reason)
        client.on_disconnect = lambda c, u, flags, reason, props: self.on_disconnect(name)
        client.on_subscribe = lambda c, u, mid, reasons, props: self.on_subscribe(name, mid, reasons)
        client.on_message = lambda c, u, message: self.on_message(name, message)
        client.connect(host, 8883, keepalive=30)

    def on_connect(self, name, client, reason):
        if reason.is_failure:
            LOG.warning("%s connection rejected; check local credentials/region", name)
            self.connected[name] = False
            return
        self.connected[name] = True
        topic = (f"device/{self.config.serial}/report" if name == "bambu" else
                 f"tylink/{self.config.device_id}/thing/property/report_response")
        result, mid = client.subscribe(topic, qos=0)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("Subscription failed")
        self.subscription_ids[name] = mid
        LOG.info("%s connected", name)

    def on_disconnect(self, name):
        self.connected[name] = self.subscribed[name] = False
        self.gate.invalidate()
        if name == "tuya":
            self.ready = False

    def on_subscribe(self, name, mid, reasons):
        if mid == self.subscription_ids.get(name) and reasons and all(not code.is_failure for code in reasons):
            self.subscribed[name] = True

    def on_message(self, name, message):
        expected = (f"device/{self.config.serial}/report" if name == "bambu" else
                    f"tylink/{self.config.device_id}/thing/property/report_response")
        if message.topic != expected or message.retain:
            return
        try:
            if len(message.payload) > 1024 * 1024:
                raise ValueError("Oversized message")
            data = json.loads(message.payload)
            if not isinstance(data, dict):
                raise ValueError("Invalid message")
        except (ValueError, UnicodeError):
            self.gate.invalidate()
            LOG.warning("%s invalid message; safety window reset", name)
            return
        if name == "bambu":
            self.gate.ingest(data, time.monotonic())
        elif self.pending and data.get("msgId") == self.pending[0]:
            if type(data.get("code")) is not int or data["code"] != 0:
                LOG.error("Tuya rejected property report; check product code and permissions")
                self.close("tuya")
                return
            self.last_value = self.pending[1]
            self.pending = None
            self.last_ack = time.monotonic()
            if not self.ready and self.last_value is False:
                self.ready = True
                self.gate.invalidate()
            LOG.info("Tuya confirmed BambuOff=%s", self.last_value)

    def send(self, value):
        client = self.clients["tuya"]
        if not client or not self.subscribed["tuya"] or self.pending:
            return
        message_id = uuid.uuid4().hex
        self.pending = (message_id, bool(value), time.monotonic())
        topic = f"tylink/{self.config.device_id}/thing/property/report"
        # QoS 0 + Tuya application ACK, no retained messages or automatic retry.
        result = client.publish(topic, json.dumps(report(self.config.property_code, value,
                                message_id, int(time.time() * 1000))), qos=0, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.close("tuya")

    def pump(self):
        for name in self.clients:
            try:
                if self.clients[name] is None and time.monotonic() >= self.next_attempt[name]:
                    self.open(name)
                client = self.clients[name]
                if client:
                    result = client.loop(timeout=0.05)
                    if result != mqtt.MQTT_ERR_SUCCESS:
                        self.close(name)
                    elif not self.subscribed[name] and time.monotonic() - self.opened_at[name] > 10:
                        self.close(name)
            except (OSError, ValueError, ConnectionError):
                LOG.warning("%s connection unavailable; retry in 5 seconds", name)
                self.close(name)
        now = time.monotonic()
        value = self.gate.tick(now, all(self.subscribed.values()) and self.ready)
        if self.pending and self.pending[1] and not value:
            # Discard potentially buffered true before it can survive a reconnect.
            self.close("tuya")
        elif self.pending and now - self.pending[2] > 10:
            LOG.warning("Tuya report unconfirmed; reconnect without replay")
            self.close("tuya")
        elif self.subscribed["tuya"] and not self.pending:
            if not self.ready:
                self.send(False)
            elif value != self.last_value:
                self.send(value)

    def shutdown(self):
        # Best effort only: offline cloud state cannot be guaranteed cleared.
        if self.subscribed["tuya"] and not self.pending:
            self.send(False)
            if self.clients["tuya"]:
                self.clients["tuya"].loop(timeout=0.1)
        for name in self.clients:
            self.close(name)
