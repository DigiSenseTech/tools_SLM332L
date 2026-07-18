"""Framework-agnostic IoT device-simulator engine.

Turns the module into a fake sensor/tracker that pushes telemetry on a timer.
The engine is UI-independent: it takes a ``SerialWorker`` plus two callbacks
(``log`` and ``on_status``) and runs its send loop on a background thread. Both
the Tkinter and the PySide6 front-ends drive the same engine.
"""

import random
import string
import threading
import time


# Sensor "device profiles": each defines a payload template using $name
# placeholders (string.Template, so it coexists with JSON braces) that the
# engine fills with freshly simulated readings on every cycle.
SIM_PROFILES = {
    "Temperature / Humidity": {
        "key": "temp",
        "template": '{"dev":"$dev","ts":$ts,"seq":$seq,"temp":$temp,"hum":$hum}',
    },
    "GPS / GNSS tracker": {
        "key": "gps",
        "template": '{"dev":"$dev","ts":$ts,"seq":$seq,"lat":$lat,"lon":$lon,'
                    '"alt":$alt,"spd":$spd}',
    },
    "Counter / heartbeat": {
        "key": "counter",
        "template": '{"dev":"$dev","ts":$ts,"seq":$seq,"value":$value}',
    },
    # Plain-text (not JSON) profiles, well suited to the SMS transport.
    "SMS text alert": {
        "key": "temp",
        "template": "SLM332L $dev alert: temp=$temp hum=$hum (seq $seq)",
    },
    "SMS position (GPS)": {
        "key": "gps",
        "template": "SLM332L $dev pos: $lat,$lon alt=$alt spd=$spd (seq $seq)",
    },
    "Custom": {
        "key": "custom",
        "template": '{"dev":"$dev","ts":$ts,"seq":$seq,"msg":"hello"}',
    },
}

SIM_TRANSPORTS = ["MQTT publish", "TCP send", "HTTP POST", "SMS"]


class SimulatorEngine:
    """Runs the periodic telemetry-send loop on a worker thread.

    log        : callable(str) - progress/telemetry messages for the log pane.
    on_status  : callable(str) - short status text (e.g. "Running - sent 4").
    on_finish  : optional callable() - invoked on the worker thread when the
                 loop ends (front-ends use it to re-enable Start).
    """

    def __init__(self, worker, log, on_status, on_finish=None):
        self.worker = worker
        self._log = log
        self._on_status = on_status
        self._on_finish = on_finish
        self._stop = threading.Event()
        self._thread = None
        self._state = {}

    # -------------------------------------------------------------- lifecycle
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, cfg):
        """cfg: parsed dict with interval(float), count(int), transport,
        profile, template, host, port, target, clientid, cid, idx."""
        if self.is_running():
            return False
        self._state = {}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    # ----------------------------------------------------------------- engine
    def _run(self, cfg):
        sent = 0
        try:
            self._log("=== IoT simulator: %s over %s (interval %ss, count %s) ===" % (
                cfg["profile"], cfg["transport"], cfg["interval"],
                cfg["count"] or "loop"))
            if not self._setup(cfg):
                return
            i = 0
            while not self._stop.is_set() and self.worker.is_open():
                if cfg["count"] and i >= cfg["count"]:
                    break
                values = self._values(cfg, i)
                payload = string.Template(cfg["template"]).safe_substitute(values)
                self._publish(cfg, payload)
                sent += 1
                i += 1
                self._on_status("Running - sent %d" % sent)
                if self._stop.wait(cfg["interval"]):
                    break
        finally:
            self._teardown(cfg)
            self._log("=== IoT simulator stopped (%d message(s) sent) ===" % sent)
            self._on_status("Idle")
            if self._on_finish:
                self._on_finish()

    def _values(self, cfg, i):
        vals = {
            "dev": cfg.get("clientid") or "slm332l",
            "ts": int(time.time()),
            "seq": i,
        }
        key = SIM_PROFILES.get(cfg["profile"], {}).get("key", "custom")
        if key == "temp":
            vals["temp"] = round(random.uniform(18.0, 32.0), 1)
            vals["hum"] = round(random.uniform(35.0, 75.0), 1)
        elif key == "gps":
            lat = self._state.get("lat", 33.5731)   # Casablanca base point
            lon = self._state.get("lon", -7.5898)
            lat += random.uniform(-0.0005, 0.0005)
            lon += random.uniform(-0.0005, 0.0005)
            self._state["lat"] = lat
            self._state["lon"] = lon
            vals["lat"] = round(lat, 6)
            vals["lon"] = round(lon, 6)
            vals["alt"] = round(random.uniform(10.0, 60.0), 1)
            vals["spd"] = round(random.uniform(0.0, 20.0), 1)
        elif key == "counter":
            vals["value"] = i
        return vals

    @staticmethod
    def _blen(text):
        return len(text.encode("utf-8", "replace"))

    def _cmd(self, cmd, data=None, end="", wait=0.0):
        if self._stop.is_set() or not self.worker.is_open():
            return
        self.worker.send_command(cmd, data=data, end=end)
        if wait:
            self._stop.wait(wait)

    def _setup(self, cfg):
        t = cfg["transport"]
        idx, cid = cfg["idx"] or "0", cfg["cid"] or "1"
        if t == "MQTT publish":
            self._cmd('AT+QMTCFG="pdpcid",%s,%s' % (idx, cid), wait=0.5)
            self._cmd('AT+QMTOPEN=%s,"%s",%s' % (idx, cfg["host"], cfg["port"]),
                      wait=5.0)
            self._cmd('AT+QMTCONN=%s,"%s"' % (idx, cfg["clientid"] or "slm332l"),
                      wait=4.0)
        elif t == "TCP send":
            self._cmd('AT+QIOPEN=%s,%s,"TCP","%s",%s,0,1' % (
                cid, idx, cfg["host"], cfg["port"]), wait=4.0)
        elif t == "HTTP POST":
            self._cmd('AT+QHTTPCFG="contextid",%s' % cid, wait=0.5)
        elif t == "SMS":
            self._cmd("AT+CMGF=1", wait=0.4)
            self._cmd('AT+CSCS="GSM"', wait=0.4)
        return not self._stop.is_set()

    def _publish(self, cfg, payload):
        t = cfg["transport"]
        idx = cfg["idx"] or "0"
        self._log("tx: %s" % payload)
        if t == "MQTT publish":
            self._cmd('AT+QMTPUBEX=%s,1,0,0,"%s",%d' % (
                idx, cfg["target"], self._blen(payload)), data=payload)
        elif t == "TCP send":
            self._cmd("AT+QISEND=%s,%d" % (idx, self._blen(payload)), data=payload)
        elif t == "HTTP POST":
            url = cfg["target"]
            self._cmd("AT+QHTTPURL=%d,80" % self._blen(url), data=url, wait=1.0)
            self._cmd("AT+QHTTPPOST=%d,80,80" % self._blen(payload), data=payload,
                      wait=2.0)
        elif t == "SMS":
            self._cmd('AT+CMGS="%s"' % cfg["target"], data=payload, end=chr(26))

    def _teardown(self, cfg):
        t = cfg["transport"]
        idx = cfg["idx"] or "0"
        if not self.worker.is_open():
            return
        # Bypass the stop flag so teardown still transmits after Stop.
        try:
            if t == "MQTT publish":
                self.worker.send_command("AT+QMTDISC=%s" % idx)
                self.worker.send_command("AT+QMTCLOSE=%s" % idx)
            elif t == "TCP send":
                self.worker.send_command("AT+QICLOSE=%s" % idx)
        except Exception:
            pass
