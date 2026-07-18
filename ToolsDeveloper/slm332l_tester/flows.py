"""End-to-end test flows for the SLM332L.

Each flow is an ordered sequence of AT commands that exercises a whole protocol
in one click (e.g. bring up data, open a TCP socket, send, read, close).

Flow dict:
    label   : shown on the Run button
    help     : one-line description
    params  : list of (key, label, default) shared input fields
    steps   : list of step dicts, each:
                {"cmd": <template>, "wait": <seconds>,
                 "data": <payload template or None>, "note": <label or None>}

Templates use {param} placeholders filled from the flow's param fields, plus the
special {len} token which the app replaces with the byte length of the step's
formatted ``data`` payload (for QISEND / QHTTPURL / QMTPUBEX length fields).
"""

FLOWS = [
    {
        "label": "Module diagnostic",
        "help": "Identity, SIM, signal, and network registration - no SIM needed to run.",
        "params": [],
        "steps": [
            {"cmd": "AT", "wait": 0.4, "note": "Link check"},
            {"cmd": "ATI", "wait": 0.5, "note": "Identity"},
            {"cmd": "AT+CGMR", "wait": 0.4, "note": "Firmware"},
            {"cmd": "AT+CGSN", "wait": 0.4, "note": "IMEI"},
            {"cmd": "AT+CIMI", "wait": 0.4, "note": "IMSI (SIM)"},
            {"cmd": "AT+QCCID", "wait": 0.4, "note": "ICCID (SIM)"},
            {"cmd": "AT+CPIN?", "wait": 0.4, "note": "SIM status"},
            {"cmd": "AT+CSQ", "wait": 0.4, "note": "Signal quality"},
            {"cmd": "AT+CREG?", "wait": 0.4, "note": "GSM registration"},
            {"cmd": "AT+CEREG?", "wait": 0.4, "note": "LTE registration"},
            {"cmd": "AT+COPS?", "wait": 0.6, "note": "Operator"},
            {"cmd": "AT+QNWINFO", "wait": 0.5, "note": "Network info"},
        ],
    },
    {
        "label": "Auto SIM + data setup",
        "help": "One-click: enable SIM detection, check SIM/PIN, full radio on, wait for "
                "registration, set APN and activate data. Reports each prerequisite. "
                "Needs a readable SIM (QSIMSTAT inserted=1); slot is hardware-selected.",
        "params": [("cid", "Context", "1"), ("apn", "APN", "www.inwi.ma")],
        "steps": [
            {"cmd": "AT+QSIMDET=1,0", "wait": 0.8, "note": "Enable SIM hot-swap detection"},
            {"cmd": "AT+QSIMSTAT?", "wait": 0.6, "note": "SIM inserted? (2nd value 1=yes)"},
            {"cmd": "AT+CPIN?", "wait": 0.8, "note": "SIM/PIN status (want READY)"},
            {"cmd": "AT+CIMI", "wait": 0.6, "note": "IMSI (proves SIM is read)"},
            {"cmd": "AT+QCCID", "wait": 0.6, "note": "ICCID"},
            {"cmd": "AT+CFUN=1", "wait": 2.0, "note": "Full functionality (radio on)"},
            {"cmd": "AT+CSQ", "wait": 0.6, "note": "Signal quality"},
            {"cmd": "AT+CEREG?", "wait": 3.0, "note": "LTE registration (want 0,1 or 0,5)"},
            {"cmd": "AT+CEREG?", "wait": 3.0, "note": "LTE registration retry"},
            {"cmd": "AT+COPS?", "wait": 0.8, "note": "Registered operator (Inwi)"},
            {"cmd": "AT+QNWINFO", "wait": 0.6, "note": "Access tech / band"},
            {"cmd": 'AT+QICSGP={cid},1,"{apn}","","",1', "wait": 0.6, "note": "Set APN"},
            {"cmd": "AT+QIACT={cid}", "wait": 4.0, "note": "Activate data context"},
            {"cmd": "AT+QIACT?", "wait": 0.8, "note": "Assigned IP (data ready)"},
        ],
    },
    {
        "label": "Bring up data (PDP)",
        "help": "Set APN and activate the data context. Do this before any IP protocol.",
        "params": [("cid", "Context", "1"), ("apn", "APN", "www.inwi.ma")],
        "steps": [
            {"cmd": 'AT+QICSGP={cid},1,"{apn}","","",1', "wait": 0.5, "note": "Configure APN"},
            {"cmd": "AT+QIACT={cid}", "wait": 3.0, "note": "Activate PDP context"},
            {"cmd": "AT+QIACT?", "wait": 0.6, "note": "Query assigned IP"},
        ],
    },
    {
        "label": "Ping / DNS / NTP",
        "help": "Connectivity checks. Requires an active PDP context.",
        "params": [("cid", "Context", "1"), ("host", "Ping/DNS host", "8.8.8.8"),
                   ("ntp", "NTP server", "pool.ntp.org")],
        "steps": [
            {"cmd": 'AT+QIDNSGIP={cid},"{host}"', "wait": 3.0, "note": "DNS lookup"},
            {"cmd": 'AT+QPING={cid},"{host}"', "wait": 6.0, "note": "Ping"},
            {"cmd": 'AT+QNTP={cid},"{ntp}",123', "wait": 4.0, "note": "NTP time sync"},
        ],
    },
    {
        "label": "HTTP GET",
        "help": "Full HTTP GET: config, set URL, GET, read body. Requires active PDP.",
        "params": [("cid", "Context", "1"), ("url", "URL", "http://www.example.com"),
                   ("tmo", "Timeout s", "80")],
        "steps": [
            {"cmd": 'AT+QHTTPCFG="contextid",{cid}', "wait": 0.5, "note": "Bind context"},
            {"cmd": 'AT+QHTTPCFG="responseheader",1', "wait": 0.4, "note": "Show headers"},
            {"cmd": "AT+QHTTPURL={len},{tmo}", "data": "{url}", "wait": 1.5, "note": "Set URL"},
            {"cmd": "AT+QHTTPGET={tmo}", "wait": 6.0, "note": "Send GET"},
            {"cmd": "AT+QHTTPREAD={tmo}", "wait": 4.0, "note": "Read response body"},
        ],
    },
    {
        "label": "TCP echo test",
        "help": "Open TCP socket, send data, read reply, close. Requires active PDP.",
        "params": [("cid", "Context", "1"), ("conn", "Connect ID", "0"),
                   ("host", "Host", "220.180.239.212"), ("port", "Port", "8009"),
                   ("msg", "Message", "hello")],
        "steps": [
            {"cmd": 'AT+QIOPEN={cid},{conn},"TCP","{host}",{port},0,1', "wait": 4.0,
             "note": "Open TCP client"},
            {"cmd": "AT+QISEND={conn},{len}", "data": "{msg}", "wait": 2.0, "note": "Send data"},
            {"cmd": "AT+QIRD={conn},1500", "wait": 1.5, "note": "Read reply"},
            {"cmd": "AT+QICLOSE={conn}", "wait": 1.0, "note": "Close socket"},
        ],
    },
    {
        "label": "MQTT publish",
        "help": "Open, connect, subscribe, publish, read, disconnect. Requires active PDP.",
        "params": [("client", "Client", "0"), ("cid", "Context", "1"),
                   ("host", "Broker", "broker.emqx.io"), ("port", "Port", "1883"),
                   ("clientid", "Client ID", "slm332l"), ("topic", "Topic", "test/slm332l"),
                   ("msg", "Message", "hello from SLM332L")],
        "steps": [
            {"cmd": 'AT+QMTCFG="pdpcid",{client},{cid}', "wait": 0.5, "note": "Bind context"},
            {"cmd": 'AT+QMTOPEN={client},"{host}",{port}', "wait": 5.0, "note": "Open network"},
            {"cmd": 'AT+QMTCONN={client},"{clientid}"', "wait": 4.0, "note": "Connect"},
            {"cmd": 'AT+QMTSUB={client},1,"{topic}",0', "wait": 3.0, "note": "Subscribe"},
            {"cmd": 'AT+QMTPUBEX={client},1,0,0,"{topic}",{len}', "data": "{msg}",
             "wait": 3.0, "note": "Publish (echoes back via subscription)"},
            {"cmd": "AT+QMTRECV={client}", "wait": 1.5, "note": "Read buffered message"},
            {"cmd": "AT+QMTDISC={client}", "wait": 2.0, "note": "Disconnect"},
            {"cmd": "AT+QMTCLOSE={client}", "wait": 1.0, "note": "Close network"},
        ],
    },
    {
        "label": "Send SMS",
        "help": "Set text mode then send an SMS. Requires a SIM registered on a network.",
        "params": [("number", "Recipient", "+10000000000"),
                   ("msg", "Message", "Hello from SLM332L")],
        "steps": [
            {"cmd": "AT+CMGF=1", "wait": 0.5, "note": "Text mode"},
            {"cmd": 'AT+CSCS="GSM"', "wait": 0.4, "note": "GSM charset"},
            {"cmd": 'AT+CMGS="{number}"', "data": "{msg}", "end": chr(26),
             "wait": 6.0, "note": "Send message (msg + Ctrl+Z)"},
        ],
    },
    {
        "label": "GNSS fix",
        "help": "Reset, turn on GNSS, then poll for a fix over ~30s. NEEDS a GPS "
                "antenna with open-sky view - indoors it stays 'Not fixed now' (516).",
        "params": [("mode", "GNSS mode", "1")],
        "steps": [
            {"cmd": "AT+MGPSEND", "wait": 1.0, "note": "Reset any running session (505 if none - ok)"},
            {"cmd": 'AT+MGPSCFG="nmeasrc",1', "wait": 0.5, "note": "Enable NMEA via AT"},
            {"cmd": "AT+MGPS={mode}", "wait": 2.0, "note": "Turn on GNSS"},
            {"cmd": "AT+MGPSLOC=2", "wait": 6.0, "note": "Location attempt 1 (516 = no fix yet)"},
            {"cmd": 'AT+MGPSNMEA="GSV"', "wait": 6.0, "note": "Satellites in view (signal check)"},
            {"cmd": "AT+MGPSLOC=2", "wait": 6.0, "note": "Location attempt 2"},
            {"cmd": 'AT+MGPSNMEA="GSV"', "wait": 6.0, "note": "Satellites in view"},
            {"cmd": "AT+MGPSLOC=2", "wait": 1.0, "note": "Location attempt 3"},
            {"cmd": 'AT+MGPSNMEA="GGA"', "wait": 0.5, "note": "GGA sentence (has lat/lon when fixed)"},
        ],
    },
    {
        "label": "WiFi scan",
        "help": "Configure and start a WiFi scan. Results arrive as *WIFICTRL URCs.",
        "params": [("rounds", "Rounds", "3"), ("maxb", "Max BSSID", "5"),
                   ("tmo", "Timeout s", "25")],
        "steps": [
            {"cmd": "AT*WIFICTRL=?", "wait": 0.5, "note": "Capability"},
            {"cmd": "AT*WIFICTRL=2,{rounds},{maxb},{tmo},0", "wait": 0.6, "note": "Configure"},
            {"cmd": "AT*WIFICTRL=1", "wait": 3.0, "note": "Start scan (watch log for results)"},
        ],
    },
]
