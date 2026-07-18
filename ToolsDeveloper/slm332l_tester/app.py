"""SLM332L Protocol Tester - Tkinter GUI.

A simple desktop tool to exercise every protocol the MEIG SLM332L LTE Cat 1
module supports (TCP/UDP, HTTP(S), MQTT, FTP(S), Ping/NTP/DNS, GNSS, WiFi scan)
over its serial AT interface, plus a raw AT terminal and a saveable log.
"""

import datetime
import queue
import random
import string
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .commands import GROUPS, format_command
from .flows import FLOWS
from .serial_worker import COMMON_BAUDS, DEFAULT_BAUD, SerialWorker


APP_TITLE = "SLM332L Protocol Tester"

# ------------------------------------------------------------- IoT simulator
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
    "Custom": {
        "key": "custom",
        "template": '{"dev":"$dev","ts":$ts,"seq":$seq,"msg":"hello"}',
    },
}

SIM_TRANSPORTS = ["MQTT publish", "TCP send", "HTTP POST", "SMS"]


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable frame (canvas + inner frame + scrollbar)."""

    def __init__(self, parent):
        super().__init__(parent)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(window, width=e.width),
        )
        canvas.configure(yscrollcommand=vbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        # Mouse-wheel scrolling while the pointer is over this canvas.
        def _wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.pack(fill="both", expand=True)

        self.log_queue = queue.Queue()
        self.worker = SerialWorker(on_line=self._on_line)

        # IoT-simulator engine state.
        self._sim_stop = threading.Event()
        self._sim_thread = None
        self._sim_state = {}

        self._build_connection_bar()
        self._build_body()
        self._build_log_pane()

        self.refresh_ports()
        self.master.after(60, self._drain_log)
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------- top: connection
    def _build_connection_bar(self):
        bar = ttk.LabelFrame(self, text="Connection")
        bar.pack(side="top", fill="x", padx=6, pady=(6, 3))

        ttk.Label(bar, text="Port:").grid(row=0, column=0, padx=(6, 2), pady=6)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(bar, textvariable=self.port_var,
                                       width=28, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=2, pady=6)

        ttk.Button(bar, text="Refresh", command=self.refresh_ports).grid(
            row=0, column=2, padx=2)
        ttk.Button(bar, text="Auto-detect AT port",
                   command=self.autodetect).grid(row=0, column=3, padx=2)

        ttk.Label(bar, text="Baud:").grid(row=0, column=4, padx=(12, 2))
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        baud_combo = ttk.Combobox(bar, textvariable=self.baud_var, width=8,
                                  values=[str(b) for b in COMMON_BAUDS])
        baud_combo.grid(row=0, column=5, padx=2)

        self.connect_btn = ttk.Button(bar, text="Connect",
                                      command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=6, padx=(12, 6))

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_lbl = ttk.Label(bar, textvariable=self.status_var,
                                    foreground="#b00020")
        self.status_lbl.grid(row=0, column=7, padx=6)

    # --------------------------------------------------------- middle: protocols
    def _build_body(self):
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(side="top", fill="both", expand=True, padx=6, pady=3)
        self._paned = paned

        # Tab strip on the right-hand side ("menu à droite").
        try:
            ttk.Style().configure("Right.TNotebook", tabposition="en")
            nb = ttk.Notebook(paned, style="Right.TNotebook")
        except Exception:
            nb = ttk.Notebook(paned)
        paned.add(nb, weight=3)

        # IoT device simulator first, then flows, then a tab per protocol.
        sim_tab = ScrollableFrame(nb)
        nb.add(sim_tab, text="IoT Simulator")
        self._build_simulator(sim_tab.inner)

        # Flows / diagnostics, then a tab per protocol.
        flow_tab = ScrollableFrame(nb)
        nb.add(flow_tab, text="Flows / Diagnostics")
        intro = ttk.Label(
            flow_tab.inner, foreground="#555", justify="left", wraplength=760,
            text="One-click end-to-end tests. Each runs a sequence of AT commands; "
                 "watch the log below. IP flows need an active PDP context first "
                 "(run 'Bring up data' or the Data / PDP context tab).")
        intro.pack(fill="x", padx=10, pady=(8, 2), anchor="w")
        for flow in FLOWS:
            self._build_flow_card(flow_tab.inner, flow)

        for title, commands in GROUPS:
            sf = ScrollableFrame(nb)
            nb.add(sf, text=title)
            for spec in commands:
                self._build_card(sf.inner, spec)

    def _build_flow_card(self, parent, flow):
        card = ttk.LabelFrame(parent, text=flow["label"])
        card.pack(fill="x", padx=8, pady=4, anchor="n")

        ttk.Label(card, text=flow.get("help", ""), foreground="#555",
                  wraplength=760, justify="left").pack(
            fill="x", padx=6, pady=(4, 2), anchor="w")

        entries = {}
        if flow.get("params"):
            field_row = ttk.Frame(card)
            field_row.pack(fill="x", padx=4, pady=(0, 2))
            col = 0
            for key, label, default in flow["params"]:
                ttk.Label(field_row, text=label + ":").grid(
                    row=0, column=col, sticky="e", padx=(6, 2), pady=2)
                var = tk.StringVar(value=default)
                width = 22 if key in ("url", "apn", "host", "ntp", "topic",
                                      "clientid", "msg") else 8
                ttk.Entry(field_row, textvariable=var, width=width).grid(
                    row=0, column=col + 1, sticky="w", padx=(0, 8), pady=2)
                entries[key] = var
                col += 2

        action = ttk.Frame(card)
        action.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(action, text="Run flow",
                   command=lambda f=flow, e=entries: self._run_flow(f, e)
                   ).pack(side="left", padx=6)
        ttk.Button(action, text="Stop", command=self.worker.abort_sequence
                   ).pack(side="left", padx=2)
        step_count = len(flow["steps"])
        ttk.Label(action, text="%d steps" % step_count,
                  foreground="#888").pack(side="left", padx=6)

    def _run_flow(self, flow, entries):
        if not self.worker.is_open():
            messagebox.showwarning(APP_TITLE, "Connect to a port first.")
            return
        if self.worker.is_busy():
            messagebox.showwarning(
                APP_TITLE, "A command or flow is already running.\n"
                "Wait for it to finish, or press Stop first.")
            return
        values = {k: v.get() for k, v in entries.items()}
        steps = []
        for step in flow["steps"]:
            data = step.get("data")
            payload = format_command(data, values) if data else None
            v = dict(values)
            if payload is not None:
                v["len"] = str(len(payload.encode("utf-8", "replace")))
            steps.append({
                "cmd": format_command(step["cmd"], v),
                "data": payload,
                "end": step.get("end", ""),
                "wait": step.get("wait", 0.5),
                "note": step.get("note"),
            })
        self._sys("=== Running flow: %s (%d steps) ===" % (flow["label"], len(steps)))
        self._run_bg(lambda: self.worker.run_sequence(
            steps, on_done=lambda: self._sys("=== Flow finished: %s ===" % flow["label"])))

    # ------------------------------------------------------- IoT simulator UI
    def _build_simulator(self, parent):
        intro = ttk.Label(
            parent, foreground="#555", justify="left", wraplength=760,
            text="Simulate an IoT device: pick a sensor profile and a transport, "
                 "set the interval and how many messages, then Start. Each cycle "
                 "generates fresh readings and publishes them over the module - "
                 "like a real sensor or GPS tracker pushing telemetry. Needs an "
                 "active PDP context first (except SMS, which needs a registered SIM).")
        intro.pack(fill="x", padx=10, pady=(8, 4), anchor="w")

        card = ttk.LabelFrame(parent, text="Device configuration")
        card.pack(fill="x", padx=8, pady=4, anchor="n")
        grid = ttk.Frame(card)
        grid.pack(fill="x", padx=6, pady=6)

        self.sim = {}

        def add(row, col, key, label, default, width=16):
            ttk.Label(grid, text=label + ":").grid(
                row=row, column=col, sticky="e", padx=(6, 2), pady=3)
            var = tk.StringVar(value=default)
            ttk.Entry(grid, textvariable=var, width=width).grid(
                row=row, column=col + 1, sticky="w", padx=(0, 10), pady=3)
            self.sim[key] = var
            return var

        # Profile + transport dropdowns.
        ttk.Label(grid, text="Sensor profile:").grid(
            row=0, column=0, sticky="e", padx=(6, 2), pady=3)
        self.sim["profile"] = tk.StringVar(value=list(SIM_PROFILES)[0])
        prof_combo = ttk.Combobox(grid, textvariable=self.sim["profile"], width=22,
                                  state="readonly", values=list(SIM_PROFILES))
        prof_combo.grid(row=0, column=1, sticky="w", padx=(0, 10), pady=3)
        prof_combo.bind("<<ComboboxSelected>>", self._sim_on_profile)

        ttk.Label(grid, text="Transport:").grid(
            row=0, column=2, sticky="e", padx=(6, 2), pady=3)
        self.sim["transport"] = tk.StringVar(value=SIM_TRANSPORTS[0])
        ttk.Combobox(grid, textvariable=self.sim["transport"], width=14,
                     state="readonly", values=SIM_TRANSPORTS).grid(
            row=0, column=3, sticky="w", padx=(0, 10), pady=3)

        add(1, 0, "interval", "Interval (s)", "5", width=8)
        add(1, 2, "count", "Count (0=loop)", "0", width=8)

        add(2, 0, "host", "Host / Broker", "broker.emqx.io", width=22)
        add(2, 2, "port", "Port", "1883", width=8)

        add(3, 0, "target", "Topic / URL / Number", "test/slm332l", width=22)
        add(3, 2, "clientid", "Device / Client ID", "slm332l", width=14)

        add(4, 0, "cid", "PDP context", "1", width=8)
        add(4, 2, "idx", "Client / Conn idx", "0", width=8)

        # Payload template (string.Template $placeholders).
        ttk.Label(grid, text="Payload template:").grid(
            row=5, column=0, sticky="e", padx=(6, 2), pady=(8, 3))
        self.sim["template"] = tk.StringVar(
            value=SIM_PROFILES[self.sim["profile"].get()]["template"])
        ttk.Entry(grid, textvariable=self.sim["template"], width=64).grid(
            row=5, column=1, columnspan=3, sticky="we", padx=(0, 10), pady=(8, 3))
        ttk.Label(grid, foreground="#888", wraplength=760, justify="left",
                  text="Placeholders: $dev $ts $seq  +  temp:$temp $hum  "
                       "gps:$lat $lon $alt $spd  counter:$value").grid(
            row=6, column=1, columnspan=3, sticky="w", padx=(0, 10))

        # Controls.
        action = ttk.Frame(card)
        action.pack(fill="x", padx=6, pady=(2, 8))
        self.sim_start_btn = ttk.Button(action, text="Start cycle",
                                        command=self._sim_start)
        self.sim_start_btn.pack(side="left", padx=(0, 4))
        self.sim_stop_btn = ttk.Button(action, text="Stop", state="disabled",
                                       command=self._sim_stop_cycle)
        self.sim_stop_btn.pack(side="left", padx=4)
        self.sim_status = tk.StringVar(value="Idle")
        ttk.Label(action, textvariable=self.sim_status,
                  foreground="#0a7d28").pack(side="left", padx=12)

    def _sim_on_profile(self, _event=None):
        prof = SIM_PROFILES.get(self.sim["profile"].get())
        if prof:
            self.sim["template"].set(prof["template"])

    # --------------------------------------------------------- simulator engine
    def _sim_start(self):
        if not self.worker.is_open():
            messagebox.showwarning(APP_TITLE, "Connect to a port first.")
            return
        if self._sim_thread and self._sim_thread.is_alive():
            messagebox.showinfo(APP_TITLE, "A simulation cycle is already running.")
            return
        try:
            cfg = {k: v.get().strip() for k, v in self.sim.items()}
            cfg["interval"] = max(0.2, float(cfg["interval"] or "5"))
            cfg["count"] = int(cfg["count"] or "0")
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Interval and Count must be numbers.")
            return

        self._sim_state = {}
        self._sim_stop.clear()
        self.sim_start_btn.configure(state="disabled")
        self.sim_stop_btn.configure(state="normal")
        self.sim_status.set("Running...")
        self._sim_thread = threading.Thread(
            target=self._sim_run, args=(cfg,), daemon=True)
        self._sim_thread.start()

    def _sim_stop_cycle(self):
        self._sim_stop.set()
        self.sim_status.set("Stopping...")

    def _sim_run(self, cfg):
        transport = cfg["transport"]
        sent = 0
        try:
            self._sys("=== IoT simulator: %s over %s (interval %ss, count %s) ===" % (
                cfg["profile"], transport, cfg["interval"],
                cfg["count"] or "loop"))
            if not self._sim_setup(cfg):
                return
            i = 0
            while not self._sim_stop.is_set() and self.worker.is_open():
                if cfg["count"] and i >= cfg["count"]:
                    break
                values = self._sim_values(cfg, i)
                payload = string.Template(cfg["template"]).safe_substitute(values)
                self._sim_publish(cfg, payload)
                sent += 1
                i += 1
                self._set_sim_status("Running - sent %d" % sent)
                if self._sim_stop.wait(cfg["interval"]):
                    break
        finally:
            self._sim_teardown(cfg)
            self._sys("=== IoT simulator stopped (%d message(s) sent) ===" % sent)
            self._set_sim_status("Idle")
            self.master.after(0, self._sim_reset_buttons)

    def _sim_reset_buttons(self):
        self.sim_start_btn.configure(state="normal")
        self.sim_stop_btn.configure(state="disabled")

    def _set_sim_status(self, text):
        self.master.after(0, lambda: self.sim_status.set(text))

    def _sim_values(self, cfg, i):
        """Generate one simulated reading for iteration ``i``."""
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
            # Random-walk around a base point (Casablanca by default).
            lat = self._sim_state.get("lat", 33.5731)
            lon = self._sim_state.get("lon", -7.5898)
            lat += random.uniform(-0.0005, 0.0005)
            lon += random.uniform(-0.0005, 0.0005)
            self._sim_state["lat"] = lat
            self._sim_state["lon"] = lon
            vals["lat"] = round(lat, 6)
            vals["lon"] = round(lon, 6)
            vals["alt"] = round(random.uniform(10.0, 60.0), 1)
            vals["spd"] = round(random.uniform(0.0, 20.0), 1)
        elif key == "counter":
            vals["value"] = i
        return vals

    def _sim_cmd(self, cmd, data=None, end="", wait=0.0):
        """Send one command from the simulator thread and pause briefly."""
        if self._sim_stop.is_set() or not self.worker.is_open():
            return
        self.worker.send_command(cmd, data=data, end=end)
        if wait:
            self._sim_stop.wait(wait)

    def _blen(self, text):
        return len(text.encode("utf-8", "replace"))

    def _sim_setup(self, cfg):
        """Open/connect the transport once before the send loop. Returns ok."""
        t = cfg["transport"]
        idx, cid = cfg["idx"] or "0", cfg["cid"] or "1"
        if t == "MQTT publish":
            self._sim_cmd('AT+QMTCFG="pdpcid",%s,%s' % (idx, cid), wait=0.5)
            self._sim_cmd('AT+QMTOPEN=%s,"%s",%s' % (idx, cfg["host"], cfg["port"]),
                          wait=5.0)
            self._sim_cmd('AT+QMTCONN=%s,"%s"' % (idx, cfg["clientid"] or "slm332l"),
                          wait=4.0)
        elif t == "TCP send":
            self._sim_cmd('AT+QIOPEN=%s,%s,"TCP","%s",%s,0,1' % (
                cid, idx, cfg["host"], cfg["port"]), wait=4.0)
        elif t == "HTTP POST":
            self._sim_cmd('AT+QHTTPCFG="contextid",%s' % cid, wait=0.5)
        elif t == "SMS":
            self._sim_cmd("AT+CMGF=1", wait=0.4)
            self._sim_cmd('AT+CSCS="GSM"', wait=0.4)
        return not self._sim_stop.is_set()

    def _sim_publish(self, cfg, payload):
        """Send one telemetry message over the chosen transport."""
        t = cfg["transport"]
        idx = cfg["idx"] or "0"
        self._sys("tx: %s" % payload)
        if t == "MQTT publish":
            self._sim_cmd('AT+QMTPUBEX=%s,1,0,0,"%s",%d' % (
                idx, cfg["target"], self._blen(payload)), data=payload)
        elif t == "TCP send":
            self._sim_cmd("AT+QISEND=%s,%d" % (idx, self._blen(payload)),
                          data=payload)
        elif t == "HTTP POST":
            url = cfg["target"]
            self._sim_cmd("AT+QHTTPURL=%d,80" % self._blen(url), data=url, wait=1.0)
            self._sim_cmd("AT+QHTTPPOST=%d,80,80" % self._blen(payload), data=payload,
                          wait=2.0)
        elif t == "SMS":
            self._sim_cmd('AT+CMGS="%s"' % cfg["target"], data=payload, end=chr(26))

    def _sim_teardown(self, cfg):
        t = cfg["transport"]
        idx = cfg["idx"] or "0"
        if not self.worker.is_open():
            return
        # Clear the stop flag locally so teardown commands still transmit.
        try:
            if t == "MQTT publish":
                self.worker.send_command("AT+QMTDISC=%s" % idx)
                self.worker.send_command("AT+QMTCLOSE=%s" % idx)
            elif t == "TCP send":
                self.worker.send_command("AT+QICLOSE=%s" % idx)
        except Exception:
            pass

    def _build_card(self, parent, spec):
        card = ttk.LabelFrame(parent, text=spec["label"])
        card.pack(fill="x", padx=8, pady=4, anchor="n")

        # Field entries.
        entries = {}
        field_row = ttk.Frame(card)
        field_row.pack(fill="x", padx=4, pady=(4, 2))
        col = 0
        for key, label, default in spec.get("fields", []):
            ttk.Label(field_row, text=label + ":").grid(
                row=0, column=col, sticky="e", padx=(6, 2), pady=2)
            var = tk.StringVar(value=default)
            width = 22 if key in ("url", "apn", "host", "server", "topic",
                                  "clientid", "payload", "body", "dir", "file",
                                  "message", "number", "smsc") else 10
            ent = ttk.Entry(field_row, textvariable=var, width=width)
            ent.grid(row=0, column=col + 1, sticky="w", padx=(0, 8), pady=2)
            entries[key] = var
            col += 2

        # Action row: preview + send.
        action = ttk.Frame(card)
        action.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(action, text="Send",
                   command=lambda s=spec, e=entries: self._send_spec(s, e)
                   ).pack(side="left", padx=6)
        ttk.Label(action, text=spec.get("help", ""), foreground="#555",
                  wraplength=680, justify="left").pack(side="left", padx=6)

    # -------------------------------------------------------------- bottom: log
    def _build_log_pane(self):
        frame = ttk.LabelFrame(self._paned, text="Log / Terminal")
        self._paned.add(frame, weight=2)

        self.log = tk.Text(frame, height=12, wrap="none", bg="#0b1021",
                           fg="#d6e2ff", insertbackground="#d6e2ff")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=yscroll.set, state="disabled")
        self.log.tag_configure("tx", foreground="#7ee787")
        self.log.tag_configure("sys", foreground="#f0b429")
        self.log.tag_configure("rx", foreground="#d6e2ff")
        self.log.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # Raw command + controls.
        ctl = ttk.Frame(self)
        ctl.pack(side="bottom", fill="x", padx=6, pady=(0, 6))
        ttk.Label(ctl, text="Raw AT:").pack(side="left", padx=(2, 4))
        self.raw_var = tk.StringVar()
        raw_entry = ttk.Entry(ctl, textvariable=self.raw_var)
        raw_entry.pack(side="left", fill="x", expand=True, padx=2)
        raw_entry.bind("<Return>", lambda e: self._send_raw())
        ttk.Button(ctl, text="Send", command=self._send_raw).pack(side="left", padx=2)
        ttk.Button(ctl, text="+++", width=4,
                   command=lambda: self._run_bg(self.worker.send_escape)
                   ).pack(side="left", padx=2)
        ttk.Button(ctl, text="Ctrl+Z", width=7,
                   command=self.worker.send_ctrl_z).pack(side="left", padx=2)
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Autoscroll",
                        variable=self.autoscroll).pack(side="left", padx=6)
        ttk.Button(ctl, text="Clear", command=self._clear_log).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save log", command=self._save_log).pack(side="left", padx=2)

    # ------------------------------------------------------------- port actions
    def refresh_ports(self):
        ports = SerialWorker.list_ports()
        values = ["%s  -  %s" % (dev, desc) for dev, desc in ports]
        self._port_map = {v: dev for v, (dev, desc) in zip(values, ports)}
        self.port_combo["values"] = values
        if values and not self.port_var.get():
            self.port_combo.current(0)

    def _selected_port(self):
        sel = self.port_var.get()
        return self._port_map.get(sel, sel.split(" ")[0] if sel else "")

    def autodetect(self):
        self._sys("Auto-detecting AT port (this closes/reopens ports)...")

        def worker():
            try:
                baud = int(self.baud_var.get())
            except ValueError:
                baud = DEFAULT_BAUD
            found = SerialWorker.autodetect(baud=baud, log=self._sys_threadsafe)
            if found:
                self._sys_threadsafe("Auto-detect: AT port(s) = %s" % ", ".join(found))
                # Preselect the first match in the combo.
                self.master.after(0, lambda: self._select_device(found[0]))
            else:
                self._sys_threadsafe("Auto-detect: no port answered AT. "
                                     "Check driver / power / baud.")

        self._run_bg(worker)

    def _select_device(self, dev):
        for value, mapped in getattr(self, "_port_map", {}).items():
            if mapped == dev:
                self.port_var.set(value)
                return
        self.port_var.set(dev)

    # ------------------------------------------------------------- connect/send
    def toggle_connection(self):
        if self.worker.is_open():
            self.worker.close()
            self.status_var.set("Disconnected")
            self.status_lbl.configure(foreground="#b00020")
            self.connect_btn.configure(text="Connect")
            self._sys("Disconnected.")
            return
        port = self._selected_port()
        if not port:
            messagebox.showwarning(APP_TITLE, "Select a serial port first.")
            return
        try:
            baud = int(self.baud_var.get())
        except ValueError:
            baud = DEFAULT_BAUD
        try:
            self.worker.open(port, baud)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "Could not open %s:\n%s" % (port, exc))
            return
        self.status_var.set("Connected  %s @ %d" % (port, baud))
        self.status_lbl.configure(foreground="#0a7d28")
        self.connect_btn.configure(text="Disconnect")
        self._sys("Connected to %s at %d baud." % (port, baud))

    def _send_spec(self, spec, entries):
        if not self.worker.is_open():
            messagebox.showwarning(APP_TITLE, "Connect to a port first.")
            return
        if self.worker.is_busy():
            messagebox.showwarning(
                APP_TITLE, "A command or flow is already running.\n"
                "Wait for it to finish, or press Stop first.")
            return
        values = {k: v.get() for k, v in entries.items()}
        data_spec = spec.get("data")
        payload = None
        end = ""
        if data_spec:
            payload = values.get(data_spec["payload_field"], "")
            len_field = data_spec.get("auto_len_field")
            if len_field:
                values[len_field] = str(len(payload.encode("utf-8", "replace")))
            end = data_spec.get("end", "")
        cmd = format_command(spec["cmd"], values)
        self._run_bg(lambda: self.worker.send_command(cmd, data=payload, end=end))

    def _send_raw(self):
        text = self.raw_var.get().strip()
        if not text:
            return
        if not self.worker.is_open():
            messagebox.showwarning(APP_TITLE, "Connect to a port first.")
            return
        if self.worker.is_busy():
            messagebox.showwarning(
                APP_TITLE, "A command or flow is already running.\n"
                "Wait for it to finish, or press Stop first.")
            return
        # Route through the locked send path so it can't interleave with a flow.
        self._run_bg(lambda: self.worker.send_command(text))
        self.raw_var.set("")

    # ------------------------------------------------------------------ logging
    def _on_line(self, text):
        # Called from worker threads; hand off to the GUI thread via the queue.
        self.log_queue.put(text)

    def _sys(self, text):
        self.log_queue.put("~ " + text)

    def _sys_threadsafe(self, text):
        self.log_queue.put("~ " + text)

    def _drain_log(self):
        try:
            while True:
                text = self.log_queue.get_nowait()
                self._append(text)
        except queue.Empty:
            pass
        self.master.after(60, self._drain_log)

    def _append(self, text):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        if text.startswith(">>>"):
            tag = "tx"
        elif text.startswith("~"):
            tag = "sys"
        else:
            tag = "rx"
        self.log.configure(state="normal")
        self.log.insert("end", "[%s] %s\n" % (stamp, text), tag)
        self.log.configure(state="disabled")
        if self.autoscroll.get():
            self.log.see("end")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            title="Save log", defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
            initialfile="slm332l_log_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.log.get("1.0", "end"))
            self._sys("Log saved to %s" % path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "Could not save log:\n%s" % exc)

    # ------------------------------------------------------------------- misc
    def _run_bg(self, func):
        threading.Thread(target=func, daemon=True).start()

    def _on_close(self):
        self._sim_stop.set()
        try:
            self.worker.close()
        finally:
            self.master.destroy()


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("980x720")
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
