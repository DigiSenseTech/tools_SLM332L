"""SLM332L Protocol Tester - PySide6 (Qt) front-end.

A modern desktop UI over the same backend as the Tkinter version: the serial
worker, the data-driven command catalog, the end-to-end flows, and the IoT
device-simulator engine are all reused unchanged. This module only builds the
interface (dark theme, right-hand navigation menu, live log).

Run with:  python -m slm332l_tester.qt_app
"""

import datetime
import html
import sys
import threading

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from .commands import GROUPS, format_command
from .flows import FLOWS
from .serial_worker import COMMON_BAUDS, DEFAULT_BAUD, SerialWorker
from .simulator import SIM_PROFILES, SIM_TRANSPORTS, SimulatorEngine


APP_TITLE = "SLM332L Protocol Tester"

# Wide fields get more room; everything else stays compact.
WIDE_KEYS = {"url", "apn", "host", "server", "topic", "clientid", "payload",
             "body", "dir", "file", "message", "number", "smsc", "ntp", "msg",
             "target", "template"}

STYLE = """
* { font-size: 13px; color: #d6e2ff; }
QMainWindow, QWidget { background: #0e1424; }
QLabel { background: transparent; }
QLabel#hint { color: #8aa0c8; }
QLabel#intro { color: #9fb4d8; }
QGroupBox {
    background: #151d33; border: 1px solid #24304f; border-radius: 10px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: #7ee787; font-weight: 600;
}
QLineEdit, QComboBox {
    background: #0b1021; border: 1px solid #2a3a5f; border-radius: 6px;
    padding: 5px 8px; selection-background-color: #2d6cdf;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #3d7bff; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #0b1021; border: 1px solid #2a3a5f;
    selection-background-color: #2d6cdf;
}
QPushButton {
    background: #1d2a49; border: 1px solid #2f3f66; border-radius: 6px;
    padding: 6px 14px; color: #e6eeff;
}
QPushButton:hover { background: #26365c; border: 1px solid #3d7bff; }
QPushButton:pressed { background: #16223d; }
QPushButton:disabled { color: #5a6b8c; background: #131a2c; border: 1px solid #222c47; }
QPushButton#accent { background: #2d6cdf; border: 1px solid #3d7bff; font-weight: 600; }
QPushButton#accent:hover { background: #3a79ee; }
QPushButton#danger { background: #7a2233; border: 1px solid #a53b4f; }
QPushButton#danger:hover { background: #8f2a3d; }
QListWidget {
    background: #0b1021; border: 1px solid #24304f; border-radius: 10px;
    padding: 6px; outline: 0;
}
QListWidget::item { padding: 9px 12px; border-radius: 7px; margin: 2px 0; }
QListWidget::item:selected { background: #2d6cdf; color: white; }
QListWidget::item:hover:!selected { background: #1b2740; }
QTextEdit {
    background: #080c18; border: 1px solid #24304f; border-radius: 8px;
}
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #1a2338; }
"""


class Bridge(QObject):
    """Marshals worker-thread events onto the Qt GUI thread via signals."""
    line = Signal(str)
    status = Signal(str)
    select_device = Signal(str)
    sim_finished = Signal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1120, 800)

        self.bridge = Bridge()
        self.worker = SerialWorker(on_line=lambda t: self.bridge.line.emit(t))
        self.sim = SimulatorEngine(
            self.worker,
            log=lambda s: self.bridge.line.emit("~ " + s),
            on_status=lambda s: self.bridge.status.emit(s),
            on_finish=lambda: self.bridge.sim_finished.emit(),
        )
        self._port_map = {}

        self._build_ui()

        self.bridge.line.connect(self._append_log)
        self.bridge.status.connect(self._set_sim_status)
        self.bridge.select_device.connect(self._select_device)
        self.bridge.sim_finished.connect(self._sim_reset_buttons)

        self.refresh_ports()

    # -------------------------------------------------------------- UI layout
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_connection_bar())

        main_split = QSplitter(Qt.Vertical)
        root.addWidget(main_split, 1)

        # Content (left) + navigation menu (right).
        content_split = QSplitter(Qt.Horizontal)
        self.stack = QStackedWidget()
        self.nav = QListWidget()
        self.nav.setMaximumWidth(220)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        content_split.addWidget(self.stack)
        content_split.addWidget(self.nav)          # menu on the right
        content_split.setStretchFactor(0, 1)
        content_split.setStretchFactor(1, 0)
        main_split.addWidget(content_split)

        main_split.addWidget(self._build_log_pane())
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 2)

        # Pages: simulator first, then flows, then one per protocol group.
        self._add_page("IoT Simulator", self._build_simulator_page())
        self._add_page("Flows / Diagnostics", self._build_flows_page())
        for title, commands in GROUPS:
            self._add_page(title, self._build_group_page(commands))
        self.nav.setCurrentRow(0)

    def _add_page(self, title, widget):
        self.nav.addItem(title)
        self.stack.addWidget(self._scroll(widget))

    @staticmethod
    def _scroll(inner):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        return area

    def _build_connection_bar(self):
        box = QGroupBox("Connection")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)

        lay.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        lay.addWidget(self.port_combo)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_ports)
        lay.addWidget(btn_refresh)

        btn_auto = QPushButton("Auto-detect AT port")
        btn_auto.clicked.connect(self.autodetect)
        lay.addWidget(btn_auto)

        lay.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in COMMON_BAUDS])
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD))
        self.baud_combo.setMaximumWidth(100)
        lay.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("accent")
        self.connect_btn.clicked.connect(self.toggle_connection)
        lay.addWidget(self.connect_btn)

        lay.addStretch(1)
        self.status_lbl = QLabel("Disconnected")
        self.status_lbl.setStyleSheet("color:#ff6b81; font-weight:600;")
        lay.addWidget(self.status_lbl)
        return box

    # ------------------------------------------------------------ simulator UI
    def _build_simulator_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        intro = QLabel(
            "Simulate an IoT device: pick a sensor profile and a transport, set "
            "the interval and how many messages, then Start. Each cycle generates "
            "fresh readings and pushes them over the module - like a real sensor "
            "or GPS tracker sending telemetry. Bring up a PDP context first "
            "(except SMS, which needs a registered SIM).")
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        v.addWidget(intro)

        box = QGroupBox("Device configuration")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.simf = {}

        self.simf["profile"] = QComboBox()
        self.simf["profile"].addItems(list(SIM_PROFILES))
        self.simf["profile"].currentTextChanged.connect(self._sim_on_profile)
        self.simf["transport"] = QComboBox()
        self.simf["transport"].addItems(SIM_TRANSPORTS)

        grid.addWidget(QLabel("Sensor profile:"), 0, 0, Qt.AlignRight)
        grid.addWidget(self.simf["profile"], 0, 1)
        grid.addWidget(QLabel("Transport:"), 0, 2, Qt.AlignRight)
        grid.addWidget(self.simf["transport"], 0, 3)

        def add_field(row, col, key, label, default):
            grid.addWidget(QLabel(label + ":"), row, col, Qt.AlignRight)
            edit = QLineEdit(default)
            self.simf[key] = edit
            grid.addWidget(edit, row, col + 1)

        add_field(1, 0, "interval", "Interval (s)", "5")
        add_field(1, 2, "count", "Count (0=loop)", "0")
        add_field(2, 0, "host", "Host / Broker", "broker.emqx.io")
        add_field(2, 2, "port", "Port", "1883")
        add_field(3, 0, "target", "Topic / URL / Number", "test/slm332l")
        add_field(3, 2, "clientid", "Device / Client ID", "slm332l")
        add_field(4, 0, "cid", "PDP context", "1")
        add_field(4, 2, "idx", "Client / Conn idx", "0")

        grid.addWidget(QLabel("Payload template:"), 5, 0, Qt.AlignRight)
        self.simf["template"] = QLineEdit(
            SIM_PROFILES[self.simf["profile"].currentText()]["template"])
        grid.addWidget(self.simf["template"], 5, 1, 1, 3)

        hint = QLabel("Placeholders: $dev $ts $seq  •  temp: $temp $hum  •  "
                      "gps: $lat $lon $alt $spd  •  counter: $value")
        hint.setObjectName("hint")
        grid.addWidget(hint, 6, 1, 1, 3)
        v.addWidget(box)

        controls = QHBoxLayout()
        self.sim_start_btn = QPushButton("Start cycle")
        self.sim_start_btn.setObjectName("accent")
        self.sim_start_btn.clicked.connect(self._sim_start)
        self.sim_stop_btn = QPushButton("Stop")
        self.sim_stop_btn.setObjectName("danger")
        self.sim_stop_btn.setEnabled(False)
        self.sim_stop_btn.clicked.connect(self._sim_stop)
        self.sim_status = QLabel("Idle")
        self.sim_status.setStyleSheet("color:#7ee787; font-weight:600;")
        controls.addWidget(self.sim_start_btn)
        controls.addWidget(self.sim_stop_btn)
        controls.addWidget(self.sim_status)
        controls.addStretch(1)
        v.addLayout(controls)
        v.addStretch(1)
        return page

    def _sim_on_profile(self, name):
        prof = SIM_PROFILES.get(name)
        if prof:
            self.simf["template"].setText(prof["template"])

    def _sim_start(self):
        if not self.worker.is_open():
            self._warn("Connect to a port first.")
            return
        if self.sim.is_running():
            self._info("A simulation cycle is already running.")
            return
        try:
            cfg = {}
            for key, w in self.simf.items():
                cfg[key] = w.currentText() if isinstance(w, QComboBox) else w.text().strip()
            cfg["interval"] = max(0.2, float(cfg["interval"] or "5"))
            cfg["count"] = int(cfg["count"] or "0")
        except ValueError:
            self._warn("Interval and Count must be numbers.")
            return
        self.sim_start_btn.setEnabled(False)
        self.sim_stop_btn.setEnabled(True)
        self.sim_status.setText("Running...")
        self.sim.start(cfg)

    def _sim_stop(self):
        self.sim.stop()
        self.sim_status.setText("Stopping...")

    def _sim_reset_buttons(self):
        self.sim_start_btn.setEnabled(True)
        self.sim_stop_btn.setEnabled(False)

    def _set_sim_status(self, text):
        self.sim_status.setText(text)

    # --------------------------------------------------------------- flows UI
    def _build_flows_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        intro = QLabel(
            "One-click end-to-end tests. Each runs a sequence of AT commands; "
            "watch the log below. IP flows need an active PDP context first.")
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        v.addWidget(intro)
        for flow in FLOWS:
            v.addWidget(self._flow_card(flow))
        v.addStretch(1)
        return page

    def _flow_card(self, flow):
        box = QGroupBox(flow["label"])
        v = QVBoxLayout(box)
        help_lbl = QLabel(flow.get("help", ""))
        help_lbl.setObjectName("hint")
        help_lbl.setWordWrap(True)
        v.addWidget(help_lbl)

        entries = {}
        if flow.get("params"):
            row = QHBoxLayout()
            for key, label, default in flow["params"]:
                row.addWidget(QLabel(label + ":"))
                edit = QLineEdit(default)
                edit.setMinimumWidth(150 if key in WIDE_KEYS else 70)
                entries[key] = edit
                row.addWidget(edit)
            row.addStretch(1)
            v.addLayout(row)

        actions = QHBoxLayout()
        run = QPushButton("Run flow")
        run.setObjectName("accent")
        run.clicked.connect(lambda _=False, f=flow, e=entries: self._run_flow(f, e))
        stop = QPushButton("Stop")
        stop.clicked.connect(self.worker.abort_sequence)
        actions.addWidget(run)
        actions.addWidget(stop)
        actions.addWidget(QLabel("%d steps" % len(flow["steps"])))
        actions.addStretch(1)
        v.addLayout(actions)
        return box

    def _run_flow(self, flow, entries):
        if not self._ready():
            return
        values = {k: e.text() for k, e in entries.items()}
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
        self.bridge.line.emit("~ === Running flow: %s (%d steps) ===" % (
            flow["label"], len(steps)))
        self._run_bg(lambda: self.worker.run_sequence(
            steps, on_done=lambda: self.bridge.line.emit(
                "~ === Flow finished: %s ===" % flow["label"])))

    # ------------------------------------------------------------ protocol UI
    def _build_group_page(self, commands):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        for spec in commands:
            v.addWidget(self._command_card(spec))
        v.addStretch(1)
        return page

    def _command_card(self, spec):
        box = QGroupBox(spec["label"])
        v = QVBoxLayout(box)
        entries = {}
        if spec.get("fields"):
            row = QHBoxLayout()
            for key, label, default in spec["fields"]:
                row.addWidget(QLabel(label + ":"))
                edit = QLineEdit(default)
                edit.setMinimumWidth(150 if key in WIDE_KEYS else 70)
                entries[key] = edit
                row.addWidget(edit)
            row.addStretch(1)
            v.addLayout(row)

        actions = QHBoxLayout()
        send = QPushButton("Send")
        send.setObjectName("accent")
        send.clicked.connect(lambda _=False, s=spec, e=entries: self._send_spec(s, e))
        actions.addWidget(send)
        help_lbl = QLabel(spec.get("help", ""))
        help_lbl.setObjectName("hint")
        help_lbl.setWordWrap(True)
        actions.addWidget(help_lbl, 1)
        v.addLayout(actions)
        return box

    def _send_spec(self, spec, entries):
        if not self._ready():
            return
        values = {k: e.text() for k, e in entries.items()}
        data_spec = spec.get("data")
        payload, end = None, ""
        if data_spec:
            payload = values.get(data_spec["payload_field"], "")
            len_field = data_spec.get("auto_len_field")
            if len_field:
                values[len_field] = str(len(payload.encode("utf-8", "replace")))
            end = data_spec.get("end", "")
        cmd = format_command(spec["cmd"], values)
        self._run_bg(lambda: self.worker.send_command(cmd, data=payload, end=end))

    # ---------------------------------------------------------------- log pane
    def _build_log_pane(self):
        box = QGroupBox("Log / Terminal")
        v = QVBoxLayout(box)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        v.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Raw AT:"))
        self.raw_edit = QLineEdit()
        self.raw_edit.returnPressed.connect(self._send_raw)
        row.addWidget(self.raw_edit, 1)
        send = QPushButton("Send")
        send.clicked.connect(self._send_raw)
        row.addWidget(send)
        esc = QPushButton("+++")
        esc.clicked.connect(lambda: self._run_bg(self.worker.send_escape))
        row.addWidget(esc)
        ctrlz = QPushButton("Ctrl+Z")
        ctrlz.clicked.connect(self.worker.send_ctrl_z)
        row.addWidget(ctrlz)
        self.autoscroll = QCheckBox("Autoscroll")
        self.autoscroll.setChecked(True)
        row.addWidget(self.autoscroll)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.log.clear)
        row.addWidget(clear)
        save = QPushButton("Save log")
        save.clicked.connect(self._save_log)
        row.addWidget(save)
        v.addLayout(row)
        return box

    def _append_log(self, text):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        if text.startswith(">>>"):
            color = "#7ee787"
        elif text.startswith("~"):
            color = "#f0b429"
        else:
            color = "#d6e2ff"
        line = ('<span style="color:#5a6b8c">[%s]</span> '
                '<span style="color:%s">%s</span>' % (
                    stamp, color, html.escape(text)))
        self.log.append(line)
        if self.autoscroll.isChecked():
            self.log.ensureCursorVisible()
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log",
            "slm332l_log_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "Text (*.txt);;All files (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.log.toPlainText())
            self.bridge.line.emit("~ Log saved to %s" % path)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, "Could not save log:\n%s" % exc)

    # ------------------------------------------------------------ port actions
    def refresh_ports(self):
        ports = SerialWorker.list_ports()
        self.port_combo.clear()
        self._port_map = {}
        for dev, desc in ports:
            label = "%s  -  %s" % (dev, desc)
            self._port_map[label] = dev
            self.port_combo.addItem(label)

    def _selected_port(self):
        label = self.port_combo.currentText()
        return self._port_map.get(label, label.split(" ")[0] if label else "")

    def autodetect(self):
        self.bridge.line.emit("~ Auto-detecting AT port (this closes/reopens ports)...")

        def work():
            try:
                baud = int(self.baud_combo.currentText())
            except ValueError:
                baud = DEFAULT_BAUD
            found = SerialWorker.autodetect(
                baud=baud, log=lambda s: self.bridge.line.emit("~ " + s))
            if found:
                self.bridge.line.emit("~ Auto-detect: AT port(s) = %s" % ", ".join(found))
                self.bridge.select_device.emit(found[0])
            else:
                self.bridge.line.emit(
                    "~ Auto-detect: no port answered AT. Check driver / power / baud.")

        self._run_bg(work)

    def _select_device(self, dev):
        for label, mapped in self._port_map.items():
            if mapped == dev:
                self.port_combo.setCurrentText(label)
                return

    def toggle_connection(self):
        if self.worker.is_open():
            self.worker.close()
            self.status_lbl.setText("Disconnected")
            self.status_lbl.setStyleSheet("color:#ff6b81; font-weight:600;")
            self.connect_btn.setText("Connect")
            self.bridge.line.emit("~ Disconnected.")
            return
        port = self._selected_port()
        if not port:
            self._warn("Select a serial port first.")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            baud = DEFAULT_BAUD
        try:
            self.worker.open(port, baud)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, "Could not open %s:\n%s" % (port, exc))
            return
        self.status_lbl.setText("Connected  %s @ %d" % (port, baud))
        self.status_lbl.setStyleSheet("color:#7ee787; font-weight:600;")
        self.connect_btn.setText("Disconnect")
        self.bridge.line.emit("~ Connected to %s at %d baud." % (port, baud))

    def _send_raw(self):
        text = self.raw_edit.text().strip()
        if not text:
            return
        if not self._ready():
            return
        self._run_bg(lambda: self.worker.send_command(text))
        self.raw_edit.clear()

    # ------------------------------------------------------------------ misc
    def _ready(self):
        if not self.worker.is_open():
            self._warn("Connect to a port first.")
            return False
        if self.worker.is_busy():
            self._warn("A command or flow is already running.\n"
                       "Wait for it to finish, or press Stop first.")
            return False
        return True

    def _run_bg(self, func):
        threading.Thread(target=func, daemon=True).start()

    def _warn(self, msg):
        QMessageBox.warning(self, APP_TITLE, msg)

    def _info(self, msg):
        QMessageBox.information(self, APP_TITLE, msg)

    def closeEvent(self, event):
        self.sim.stop()
        try:
            self.worker.close()
        finally:
            super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
