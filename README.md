# SLM332L Protocol Tester

A simple Python/Tkinter desktop tool to test **all protocols** of the
**MEIG SLM332L** LTE Cat 1 module over its serial AT-command interface.

The module is driven entirely by AT commands over a USB/UART COM port. This tool
gives you a guided button-per-command UI for every protocol in the manuals, an
auto-detector for the AT port, a raw AT terminal, and a saveable session log.

## Protocols covered

| Tab | Commands |
|-----|----------|
| **Flows / Diagnostics** | One-click end-to-end sequences: Module diagnostic, Bring up data (PDP), Ping/DNS/NTP, HTTP GET, TCP echo, MQTT publish, GNSS fix, WiFi scan |
| Basic / Module | AT, ATI, firmware, IMEI, IMSI, ICCID, SIM status, signal (CSQ), registration, operator, network info, CFUN, echo |
| Data / PDP context | QICSGP (APN), QIACT / QIACT? / QIDEACT, CGATT |
| TCP / UDP | QIOPEN (TCP/UDP), QISEND (with data prompt), QIRD, QISTATE, QICLOSE |
| Ping / NTP / DNS | QPING, QNTP, QIDNSGIP |
| HTTP(S) | QHTTPCFG, QHTTPURL, QHTTPGET, QHTTPREAD, QHTTPPOST, QHTTPSTOP |
| MQTT | QMTCFG, QMTOPEN, QMTCONN, QMTSUB, QMTUNS, QMTPUBEX, QMTRECV, QMTDISC, QMTCLOSE |
| FTP(S) | QFTPCFG, QFTPOPEN, QFTPPWD/CWD/LIST/SIZE, QFTPCLOSE |
| GNSS | MGPSINFO, MGPSCFG, MGPS, MGPSLOC, MGPSNMEA, MGPSEND |
| WiFi Scan | *WIFICTRL (query / config / start / stop) |
| SMS | CMGF, CSCS, CSCA, **CMGS (simple sender)**, CMGL, CMGR, CMGD, CNMI, CPMS |

## Requirements

- **Python 3.8+** (Tkinter ships with standard Python on Windows)
- **pyserial** — `pip install -r requirements.txt`
- **MEIG ASR USB driver** installed (from [`drivers/`](drivers/) — extract
  `MEIG_ASR_USB_Driver_v1.0.3.3.zip` and run the installer), so the module
  enumerates its COM ports.

## Run

```
pip install -r requirements.txt
python -m slm332l_tester
```

or just double-click **`run.bat`** on Windows.

## Usage

1. **Connect the module** via USB. It enumerates several ports; the AT commands
   go to the **"MeigSmart USB AT Port"** (on this machine that is `COM8`).
2. Click **Auto-detect AT port** — it probes each port with `AT` and highlights
   the one that answers `OK`. Then click **Connect**.
3. Start on the **Basic / Module** tab: send `AT`, check `AT+CSQ` (signal) and
   `AT+CPIN?` (SIM).
4. For any data protocol (TCP/HTTP/MQTT/FTP), first go to **Data / PDP context**:
   set your APN with *Configure APN*, then *Activate PDP*.
5. Open a protocol tab, fill the fields, and click **Send**. All traffic —
   commands, responses, and asynchronous URCs — streams into the log.
6. Or use the **Flows / Diagnostics** tab to run a whole protocol test in one
   click (e.g. *HTTP GET* runs config → set URL → GET → read automatically).
   **Run flow** executes the sequence; **Stop** aborts it.
7. **Save log** writes a timestamped transcript for your test report.

> **Tip:** *Module diagnostic* on the Flows tab is the fastest way to confirm a
> new board — it checks identity, SIM, signal, and registration with one click
> and needs no SIM to run.

### Notes

- **Interactive commands** (QISEND, QHTTPURL, QHTTPPOST, QMTPUBEX) wait for the
  module's `>` or `CONNECT` prompt, then send the payload automatically. The
  length field is auto-filled from the payload so the byte count always matches.
- **Send an SMS:** SMS tab → *Set text mode*, then *Send SMS* (enter recipient +
  message). It waits for the `>` prompt and appends **Ctrl+Z** to send. Or use
  the **Send SMS** flow to set text mode and send in one click. Needs a SIM
  registered on a network.
- **`+++`** leaves transparent/data mode; **Ctrl+Z** ends variable-length input.
- GNSS NMEA output is also streamed on the dedicated **USB Nmea Port** (`COM6`);
  this tool reads positioning via `AT+MGPSLOC` / `AT+MGPSNMEA` on the AT port.

## Project layout

```
slm332l_tester/
  serial_worker.py   # serial connection, reader thread, auto-detect, flow runner
  commands.py        # data-driven catalog of every protocol command
  flows.py           # end-to-end multi-step test sequences
  app.py             # Tkinter GUI (connection bar, Flows + protocol tabs, log)
  __main__.py        # entry point for `python -m slm332l_tester`
requirements.txt
run.bat
```

The command catalog is data-driven: to add or tweak a command, edit
`commands.py` — the GUI builds its panels from it automatically.
