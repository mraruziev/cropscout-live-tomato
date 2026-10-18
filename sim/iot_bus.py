"""
IoT telemetry bus for the robot: every state change is a JSON message on a topic.

    bus = IoTBus()                                   # logs to out/telemetry.jsonl
    bus = IoTBus(broker="test.mosquitto.org")        # ...and publishes over MQTT (pip install paho-mqtt)
    bus.publish("spray", {"side": "left", "heads": [0, 1], "dose_ml": 20})

Topics (prefix cropscout/<robot_id>/):
    telemetry   x_m, speed, tank_ml, tank_pct, pump_on, valves[6], mission_time_s      ~10 Hz while driving
    inspection  plant, side, label, diagnosis, confidence, severity, dose_ml, heads, image   per plant
    spray       side, heads, dose_ml, seconds, tank_ml_after                                    per spray
    mission     start / summary

Same messages whether the source is the MuJoCo twin or the real robot: the dashboard, the farmer app
and the CropSCOUT web app can subscribe to either. `bus.last` keeps the latest message per topic.
"""
import json
import os
import socket
import threading
import time
from pathlib import Path


class IoTBus:
    def __init__(self, robot_id="a08", broker=None, port=1883, log_path="out/telemetry.jsonl", quiet=False):
        self.robot_id = robot_id
        self.prefix = f"cropscout/{robot_id}/"
        self.last = {}
        self.history = []
        self.listeners = []
        self.mqtt = None
        self.quiet = quiet
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._log = open(log_path, "a", buffering=1)
        broker = broker or os.environ.get("CROPSCOUT_MQTT")
        if broker:
            self._connect_mqtt(broker, port)

    def _connect_mqtt(self, broker, port):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            if not self.quiet:
                print("[iot] paho-mqtt not installed (pip install paho-mqtt); logging to file only")
            return
        try:
            socket.create_connection((broker, port), timeout=3).close()
            client = mqtt.Client(client_id=f"cropscout-{self.robot_id}-{int(time.time())}")
            client.connect_async(broker, port, keepalive=30)
            client.loop_start()
            self.mqtt = client
            if not self.quiet:
                print(f"[iot] publishing to mqtt://{broker}:{port}/{self.prefix}#")
        except OSError as e:
            if not self.quiet:
                print(f"[iot] broker {broker}:{port} unreachable ({e}); logging to file only")

    def subscribe(self, fn):
        """fn(topic, payload) is called for every message (in-process)."""
        self.listeners.append(fn)

    def publish(self, topic, payload):
        msg = dict(payload)
        msg["t"] = round(time.time(), 3)
        msg["robot"] = self.robot_id
        self.last[topic] = msg
        self.history.append((topic, msg))
        line = json.dumps({"topic": self.prefix + topic, **msg}, default=str)
        self._log.write(line + "\n")
        if self.mqtt is not None:
            try:
                self.mqtt.publish(self.prefix + topic, line, qos=0)
            except Exception:
                pass
        for fn in self.listeners:
            try:
                fn(topic, msg)
            except Exception:
                pass
        return msg

    def close(self):
        try:
            self._log.close()
            if self.mqtt is not None:
                self.mqtt.loop_stop()
        except Exception:
            pass
