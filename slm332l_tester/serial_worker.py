"""Serial communication layer for the SLM332L AT-command tester.

Owns the serial port, runs a background reader thread that streams every
incoming line to a callback, and provides both plain and interactive
(prompt-based) command sending. Also auto-detects which COM port answers AT.
"""

import threading
import time

import serial
import serial.tools.list_ports as list_ports


DEFAULT_BAUD = 115200
COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]


class SerialWorker:
    """Manages one serial connection to the modem.

    on_line: callback(text: str) invoked for every line received from the
             module and for local echoes of what we send. Called from the
             reader thread, so the GUI must marshal it onto the UI thread.
    """

    def __init__(self, on_line):
        self.on_line = on_line
        self.ser = None
        self._reader = None
        self._running = False
        self._prompt_event = threading.Event()
        self._seq_abort = threading.Event()
        # Serializes all command/flow IO so nothing interleaves on the port.
        self._io_lock = threading.Lock()

    # ------------------------------------------------------------------ ports
    @staticmethod
    def list_ports():
        """Return a list of (device, description) for every serial port."""
        return [(p.device, p.description or "") for p in list_ports.comports()]

    def is_open(self):
        return self.ser is not None and self.ser.is_open

    # ------------------------------------------------------------- open/close
    def open(self, port, baud=DEFAULT_BAUD):
        self.close()
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def close(self):
        self._running = False
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    # ----------------------------------------------------------- reader thread
    def _read_loop(self):
        buf = b""
        while self._running and self.ser is not None:
            try:
                data = self.ser.read(256)
            except Exception as exc:
                self._emit("[reader error] %s" % exc)
                break
            if not data:
                continue
            buf += data

            # Detect the data-entry prompt ('>' from QISEND/QMTPUBEX or the
            # 'CONNECT' banner from QHTTPURL/QHTTPPOST). These do not end with
            # a newline, so they must be handled before line splitting.
            if b">" in data or b"CONNECT" in buf:
                self._prompt_event.set()

            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace").rstrip("\r")
                if text != "":
                    self._emit(text)

            # Flush a trailing prompt that has no newline after it.
            stripped = buf.strip()
            if stripped in (b">", b"CONNECT"):
                self._emit(buf.decode("utf-8", "replace").strip())
                buf = b""

    def _emit(self, text):
        try:
            self.on_line(text)
        except Exception:
            pass

    # --------------------------------------------------------------- sending
    def send_raw(self, text, append_cr=True):
        """Write a raw string to the port (adds <CR><LF> by default)."""
        if not self.is_open():
            self._emit("[not connected]")
            return
        payload = text.encode("utf-8", "replace")
        if append_cr:
            payload += b"\r\n"
        try:
            self.ser.write(payload)
            self._emit(">>> " + text)
        except Exception as exc:
            self._emit("[write error] %s" % exc)

    def is_busy(self):
        """True while a command or flow currently holds the serial port."""
        return self._io_lock.locked()

    def send_command(self, cmd, data=None, end="", prompt_timeout=4.0):
        """Send a command, serialized against any other command/flow.

        Blocks until the port is free (a running flow finishes) so nothing
        interleaves on the wire. Call on a worker thread.
        """
        with self._io_lock:
            self._do_command(cmd, data=data, end=end, prompt_timeout=prompt_timeout)

    def _do_command(self, cmd, data=None, end="", prompt_timeout=4.0):
        """Actual send logic. Assumes the caller holds ``_io_lock``.

        ``end`` is the terminator: "" for length-based sends (QISEND / QHTTPURL /
        QMTPUBEX, which auto-complete once the byte count is reached) or
        chr(26) (Ctrl+Z) for SMS text mode (AT+CMGS).
        """
        if not self.is_open():
            self._emit("[not connected]")
            return
        self._prompt_event.clear()
        self.send_raw(cmd)
        if data is None:
            return
        if self._prompt_event.wait(prompt_timeout):
            time.sleep(0.05)
            try:
                self.ser.write(data.encode("utf-8", "replace")
                               + end.encode("utf-8", "replace"))
                suffix = " <Ctrl+Z>" if end == chr(26) else ""
                self._emit(">>> [payload] " + data + suffix)
            except Exception as exc:
                self._emit("[write error] %s" % exc)
        else:
            self._emit("[timeout] no input prompt received for data entry")

    def run_sequence(self, steps, on_done=None):
        """Run an ordered list of steps as one flow.

        Each step is a dict: {"cmd": str, "wait": float, "data": str|None,
        "note": str|None}. Runs synchronously (call on a worker thread). Use
        abort_sequence() to stop early.
        """
        if self.is_busy():
            self._emit("~ busy: another command or flow is running - ignored")
            return
        self._seq_abort.clear()
        with self._io_lock:
            for step in steps:
                if self._seq_abort.is_set() or not self.is_open():
                    self._emit("~ flow aborted")
                    break
                note = step.get("note")
                if note:
                    self._emit("~ " + note)
                self._do_command(step["cmd"], data=step.get("data"),
                                 end=step.get("end", ""))
                # Interruptible wait.
                self._seq_abort.wait(step.get("wait", 0.5))
        if on_done:
            on_done()

    def abort_sequence(self):
        self._seq_abort.set()

    def send_escape(self):
        """Send the +++ escape sequence to leave transparent/data mode."""
        if not self.is_open():
            self._emit("[not connected]")
            return
        time.sleep(1.0)
        self.ser.write(b"+++")
        self._emit(">>> +++ (escape to command mode)")
        time.sleep(1.0)

    def send_ctrl_z(self):
        if self.is_open():
            self.ser.write(b"\x1a")
            self._emit(">>> <Ctrl+Z>")

    # ----------------------------------------------------------- auto-detect
    @staticmethod
    def autodetect(baud=DEFAULT_BAUD, log=None):
        """Probe every serial port with 'AT' and return the list of ports
        that answer 'OK' (these are AT command ports)."""
        found = []
        for dev, desc in SerialWorker.list_ports():
            if log:
                log("Probing %s (%s) ..." % (dev, desc))
            try:
                s = serial.Serial(dev, baud, timeout=0.5)
            except Exception as exc:
                if log:
                    log("  %s: cannot open (%s)" % (dev, exc))
                continue
            try:
                s.reset_input_buffer()
                s.write(b"AT\r\n")
                time.sleep(0.4)
                resp = s.read(256).decode("utf-8", "replace")
                if "OK" in resp:
                    found.append(dev)
                    if log:
                        log("  %s: responds OK  <-- AT port" % dev)
                elif log:
                    log("  %s: no AT response" % dev)
            except Exception as exc:
                if log:
                    log("  %s: error (%s)" % (dev, exc))
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        return found
