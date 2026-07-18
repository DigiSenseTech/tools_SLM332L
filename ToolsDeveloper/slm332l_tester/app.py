"""SLM332L Protocol Tester - Tkinter GUI.

A simple desktop tool to exercise every protocol the MEIG SLM332L LTE Cat 1
module supports (TCP/UDP, HTTP(S), MQTT, FTP(S), Ping/NTP/DNS, GNSS, WiFi scan)
over its serial AT interface, plus a raw AT terminal and a saveable log.
"""

import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .commands import GROUPS, format_command
from .flows import FLOWS
from .serial_worker import COMMON_BAUDS, DEFAULT_BAUD, SerialWorker


APP_TITLE = "SLM332L Protocol Tester"


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

        nb = ttk.Notebook(paned)
        paned.add(nb, weight=3)

        # Flows / diagnostics first, then a tab per protocol.
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
