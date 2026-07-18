"""AT command catalog for the MEIG SLM332L (LTE Cat 1) module.

Data-driven so the GUI builds every protocol panel automatically. Each command
is a dict:

    label   : button/card title shown in the UI
    cmd     : AT template with {placeholders} filled from the fields
    fields  : list of (key, label, default) input boxes
    help    : one-line hint (syntax / prerequisite) from the manual
    data    : optional interactive data-entry spec:
              {"payload_field": <key>, "auto_len_field": <key or None>}
              The command is sent, we wait for the module's '>' / 'CONNECT'
              prompt, then the payload field's value is sent. If auto_len_field
              is set, that field is auto-filled with the payload byte length.

Command syntax taken from:
  - MEIG-SLM3XX AT Command Manual EX V2.0.6
  - MEIG SLM3XX GNSS AT Commands Manual V1.0
  - SLM3XX WIFI AT Commands Manual V1.0
"""

# Each group: (title, [command dicts])
GROUPS = [
    # ------------------------------------------------------------------ Basic
    ("Basic / Module", [
        {"label": "AT test", "cmd": "AT", "fields": [],
         "help": "Module should reply OK. Start here."},
        {"label": "Product info", "cmd": "ATI", "fields": [],
         "help": "Manufacturer, model, revision."},
        {"label": "Firmware version", "cmd": "AT+CGMR", "fields": [],
         "help": "Software revision."},
        {"label": "IMEI", "cmd": "AT+CGSN", "fields": [],
         "help": "Module serial number / IMEI."},
        {"label": "IMSI (SIM)", "cmd": "AT+CIMI", "fields": [],
         "help": "SIM international subscriber identity."},
        {"label": "ICCID", "cmd": "AT+QCCID", "fields": [],
         "help": "SIM card ICCID."},
        {"label": "SIM status", "cmd": "AT+CPIN?", "fields": [],
         "help": "READY = SIM ok; SIM PIN = PIN required."},
        {"label": "Signal quality", "cmd": "AT+CSQ", "fields": [],
         "help": "+CSQ: <rssi>,<ber>. 99 = unknown/no signal."},
        {"label": "Network registration", "cmd": "AT+CREG?", "fields": [],
         "help": "stat 1 = registered home, 5 = roaming."},
        {"label": "EPS registration (LTE)", "cmd": "AT+CEREG?", "fields": [],
         "help": "LTE attach status."},
        {"label": "Operator", "cmd": "AT+COPS?", "fields": [],
         "help": "Currently registered network operator."},
        {"label": "Network info", "cmd": "AT+QNWINFO", "fields": [],
         "help": "Access tech, band, channel, operator."},
        {"label": "Radio function (CFUN)", "cmd": "AT+CFUN={fun}",
         "fields": [("fun", "0=min 1=full 4=airplane", "1")],
         "help": "Set functionality level."},
        {"label": "Echo on/off", "cmd": "ATE{e}",
         "fields": [("e", "1=on 0=off", "1")],
         "help": "Command echo. Turn off to declutter."},
    ]),

    # ------------------------------------------------------------- PDP context
    ("Data / PDP context", [
        {"label": "Configure APN", "cmd": 'AT+QICSGP={cid},1,"{apn}","{user}","{pw}",1',
         "fields": [("cid", "Context 1-16", "1"), ("apn", "APN", "www.inwi.ma"),
                    ("user", "User", ""), ("pw", "Password", "")],
         "help": "Set APN before activating. contexttype 1=IPv4. Inwi APN = www.inwi.ma."},
        {"label": "Activate PDP", "cmd": "AT+QIACT={cid}",
         "fields": [("cid", "Context", "1")],
         "help": "Bring up data context. Required before TCP/HTTP/MQTT/FTP."},
        {"label": "Query IP address", "cmd": "AT+QIACT?", "fields": [],
         "help": "Shows active contexts and assigned IP."},
        {"label": "Deactivate PDP", "cmd": "AT+QIDEACT={cid}",
         "fields": [("cid", "Context", "1")],
         "help": "Tear down data context."},
        {"label": "Attach status", "cmd": "AT+CGATT?", "fields": [],
         "help": "1 = attached to packet domain."},
    ]),

    # --------------------------------------------------------------- TCP / UDP
    ("TCP / UDP", [
        {"label": "Open TCP client", "cmd": 'AT+QIOPEN={cid},{conn},"TCP","{host}",{port},0,1',
         "fields": [("cid", "Context", "1"), ("conn", "Connect ID 0-11", "0"),
                    ("host", "Host", "220.180.239.212"), ("port", "Port", "8009")],
         "help": "Buffer access mode (last param 1). URC +QIOPEN: on result."},
        {"label": "Open UDP socket", "cmd": 'AT+QIOPEN={cid},{conn},"UDP","{host}",{port},0,1',
         "fields": [("cid", "Context", "1"), ("conn", "Connect ID", "1"),
                    ("host", "Host", "220.180.239.212"), ("port", "Port", "8009")],
         "help": "UDP client socket."},
        {"label": "Socket status", "cmd": "AT+QISTATE?", "fields": [],
         "help": "List all open sockets and their state."},
        {"label": "Send data (TCP)", "cmd": "AT+QISEND={conn},{length}",
         "fields": [("conn", "Connect ID", "0"), ("payload", "Data", "hello"),
                    ("length", "Length (auto)", "5")],
         "data": {"payload_field": "payload", "auto_len_field": "length"},
         "help": "Sends exactly <length> bytes after the '>' prompt."},
        {"label": "Send data to remote (UDP)",
         "cmd": 'AT+QISEND={conn},{length},"{host}",{port}',
         "fields": [("conn", "Connect ID", "1"), ("host", "Remote IP", "220.180.239.212"),
                    ("port", "Remote port", "8009"), ("payload", "Data", "hello"),
                    ("length", "Length (auto)", "5")],
         "data": {"payload_field": "payload", "auto_len_field": "length"},
         "help": "UDP send to a specific remote address."},
        {"label": "Read received data", "cmd": "AT+QIRD={conn},{length}",
         "fields": [("conn", "Connect ID", "0"), ("length", "Max bytes", "1500")],
         "help": "Read buffered incoming data."},
        {"label": "Close socket", "cmd": "AT+QICLOSE={conn}",
         "fields": [("conn", "Connect ID", "0")],
         "help": "Close a socket / listener."},
    ]),

    # ----------------------------------------------------------- Ping/NTP/DNS
    ("Ping / NTP / DNS", [
        {"label": "Ping host", "cmd": 'AT+QPING={cid},"{host}"',
         "fields": [("cid", "Context", "1"), ("host", "Host", "8.8.8.8")],
         "help": "ICMP ping. PDP must be active."},
        {"label": "NTP time sync", "cmd": 'AT+QNTP={cid},"{server}",123',
         "fields": [("cid", "Context", "1"), ("server", "NTP server", "pool.ntp.org")],
         "help": "Synchronise local time from an NTP server."},
        {"label": "DNS lookup", "cmd": 'AT+QIDNSGIP={cid},"{host}"',
         "fields": [("cid", "Context", "1"), ("host", "Hostname", "www.google.com")],
         "help": "Resolve a hostname to IP address(es)."},
    ]),

    # -------------------------------------------------------------- HTTP(S)
    ("HTTP(S)", [
        {"label": "Set context id", "cmd": 'AT+QHTTPCFG="contextid",{cid}',
         "fields": [("cid", "Context", "1")],
         "help": "Bind HTTP to a PDP context."},
        {"label": "Enable response header", "cmd": 'AT+QHTTPCFG="responseheader",{en}',
         "fields": [("en", "0/1", "1")],
         "help": "Include response headers in read output."},
        {"label": "Set URL", "cmd": "AT+QHTTPURL={length},{timeout}",
         "fields": [("url", "URL", "http://www.example.com"),
                    ("length", "URL len (auto)", "22"), ("timeout", "Input timeout s", "80")],
         "data": {"payload_field": "url", "auto_len_field": "length"},
         "help": "After CONNECT prompt the URL text is sent."},
        {"label": "HTTP GET", "cmd": "AT+QHTTPGET={timeout}",
         "fields": [("timeout", "Response timeout s", "80")],
         "help": "Send GET. Result URC: +QHTTPGET: <err>,<code>,<len>."},
        {"label": "Read response", "cmd": "AT+QHTTPREAD={timeout}",
         "fields": [("timeout", "Wait timeout s", "80")],
         "help": "Output the response body via this port."},
        {"label": "HTTP POST", "cmd": "AT+QHTTPPOST={length},{intime},{rsptime}",
         "fields": [("body", "POST body", "hello=world"),
                    ("length", "Body len (auto)", "11"),
                    ("intime", "Input timeout s", "80"), ("rsptime", "Response timeout s", "80")],
         "data": {"payload_field": "body", "auto_len_field": "length"},
         "help": "After '>' prompt the body is sent."},
        {"label": "Stop HTTP", "cmd": "AT+QHTTPSTOP", "fields": [],
         "help": "Cancel an in-progress HTTP request."},
    ]),

    # ---------------------------------------------------------------- MQTT
    ("MQTT", [
        {"label": "Configure PDP cid", "cmd": 'AT+QMTCFG="pdpcid",{client},{cid}',
         "fields": [("client", "Client 0-5", "0"), ("cid", "Context", "1")],
         "help": "Bind MQTT client to a PDP context."},
        {"label": "Configure keepalive", "cmd": 'AT+QMTCFG="keepalive",{client},{ka}',
         "fields": [("client", "Client", "0"), ("ka", "Seconds 0-3600", "60")],
         "help": "MQTT keepalive interval."},
        {"label": "Enable SSL", "cmd": 'AT+QMTCFG="ssl",{client},{en},{ctx}',
         "fields": [("client", "Client", "0"), ("en", "0/1", "1"), ("ctx", "SSL ctx 0-5", "0")],
         "help": "Enable TLS for MQTTS."},
        {"label": "Open network", "cmd": 'AT+QMTOPEN={client},"{host}",{port}',
         "fields": [("client", "Client", "0"), ("host", "Broker", "broker.emqx.io"),
                    ("port", "Port", "1883")],
         "help": "TCP connect. URC +QMTOPEN: <client>,0 on success."},
        {"label": "Connect client", "cmd": 'AT+QMTCONN={client},"{clientid}","{user}","{pw}"',
         "fields": [("client", "Client", "0"), ("clientid", "Client ID", "slm332l"),
                    ("user", "Username", ""), ("pw", "Password", "")],
         "help": "MQTT CONNECT. URC +QMTCONN: <client>,0,0 on success."},
        {"label": "Subscribe topic", "cmd": 'AT+QMTSUB={client},{msgid},"{topic}",{qos}',
         "fields": [("client", "Client", "0"), ("msgid", "Msg ID", "1"),
                    ("topic", "Topic", "test/slm332l"), ("qos", "QoS 0-2", "0")],
         "help": "Subscribe. Incoming msgs arrive as +QMTRECV URCs."},
        {"label": "Unsubscribe topic", "cmd": 'AT+QMTUNS={client},{msgid},"{topic}"',
         "fields": [("client", "Client", "0"), ("msgid", "Msg ID", "2"),
                    ("topic", "Topic", "test/slm332l")],
         "help": "Unsubscribe from a topic."},
        {"label": "Publish message",
         "cmd": 'AT+QMTPUBEX={client},{msgid},{qos},{retain},"{topic}",{length}',
         "fields": [("client", "Client", "0"), ("msgid", "Msg ID", "1"),
                    ("qos", "QoS 0-2", "0"), ("retain", "Retain 0/1", "0"),
                    ("topic", "Topic", "test/slm332l"), ("payload", "Message", "hello from SLM332L"),
                    ("length", "Length (auto)", "18")],
         "data": {"payload_field": "payload", "auto_len_field": "length"},
         "help": "Publishes <length> bytes after the '>' prompt."},
        {"label": "Read buffered message", "cmd": "AT+QMTRECV={client}",
         "fields": [("client", "Client", "0")],
         "help": "Read messages held in the receive buffer."},
        {"label": "Disconnect", "cmd": "AT+QMTDISC={client}",
         "fields": [("client", "Client", "0")],
         "help": "MQTT DISCONNECT."},
        {"label": "Close network", "cmd": "AT+QMTCLOSE={client}",
         "fields": [("client", "Client", "0")],
         "help": "Close the TCP connection."},
    ]),

    # ---------------------------------------------------------------- FTP(S)
    ("FTP(S)", [
        {"label": "Set context id", "cmd": 'AT+QFTPCFG="contextid",{cid}',
         "fields": [("cid", "Context", "1")],
         "help": "Bind FTP to a PDP context."},
        {"label": "Set account", "cmd": 'AT+QFTPCFG="account","{user}","{pw}"',
         "fields": [("user", "User", "anonymous"), ("pw", "Password", "test@test.com")],
         "help": "FTP username / password."},
        {"label": "Set file type", "cmd": 'AT+QFTPCFG="filetype",{t}',
         "fields": [("t", "0=binary 1=ascii", "0")],
         "help": "Transfer file type."},
        {"label": "Set transfer mode", "cmd": 'AT+QFTPCFG="transmode",{m}',
         "fields": [("m", "0=active 1=passive", "1")],
         "help": "Passive mode is usually needed behind NAT."},
        {"label": "Login / Open", "cmd": 'AT+QFTPOPEN="{host}",{port}',
         "fields": [("host", "FTP host", "ftp.example.com"), ("port", "Port", "21")],
         "help": "Login. PDP must be active. URC +QFTPOPEN: 0,0 ok."},
        {"label": "Current directory", "cmd": "AT+QFTPPWD", "fields": [],
         "help": "Print working directory."},
        {"label": "Change directory", "cmd": 'AT+QFTPCWD="{dir}"',
         "fields": [("dir", "Path", "/")],
         "help": "Change the current directory."},
        {"label": "List directory", "cmd": 'AT+QFTPLIST="{dir}"',
         "fields": [("dir", "Path", "/")],
         "help": "List directory contents."},
        {"label": "File size", "cmd": 'AT+QFTPSIZE="{file}"',
         "fields": [("file", "Path", "/pub/test.txt")],
         "help": "Retrieve remote file size."},
        {"label": "Logout / Close", "cmd": "AT+QFTPCLOSE", "fields": [],
         "help": "Close the FTP session."},
    ]),

    # ----------------------------------------------------------------- GNSS
    ("GNSS", [
        {"label": "GNSS version", "cmd": "AT+MGPSINFO", "fields": [],
         "help": "Query GNSS engine version."},
        {"label": "Config constellations", "cmd": 'AT+MGPSCFG="gnssconfig",{cfg}',
         "fields": [("cfg", "GNSS config value", "0")],
         "help": "Select GPS/BDS/GLONASS/Galileo combination."},
        {"label": "Enable NMEA via AT", "cmd": 'AT+MGPSCFG="nmeasrc",1', "fields": [],
         "help": "Needed before reading sentences with AT+MGPSNMEA."},
        {"label": "Turn on GNSS", "cmd": "AT+MGPS={mode}",
         "fields": [("mode", "GNSS mode (1=standalone)", "1")],
         "help": "Start positioning."},
        {"label": "Get location", "cmd": "AT+MGPSLOC={mode}",
         "fields": [("mode", "Lat/lon fmt 0/1/2", "2")],
         "help": "UTC,lat,lon,HDOP,alt,fix,COG,speed,date,sats. fmt 2 = decimal deg."},
        {"label": "Get NMEA sentence", "cmd": 'AT+MGPSNMEA="{type}"',
         "fields": [("type", "GGA/RMC/GSV/GSA/GLL/VTG", "GGA")],
         "help": "Requires nmeasrc enabled."},
        {"label": "Turn off GNSS", "cmd": "AT+MGPSEND", "fields": [],
         "help": "Stop positioning."},
    ]),

    # ------------------------------------------------------------- WiFi Scan
    ("WiFi Scan", [
        {"label": "Query capability", "cmd": "AT*WIFICTRL=?", "fields": [],
         "help": "Show supported scan options / ranges."},
        {"label": "Config scan params",
         "cmd": "AT*WIFICTRL=2,{rounds},{maxbssid},{timeout},{pri}",
         "fields": [("rounds", "Scan rounds 1-255", "3"), ("maxbssid", "Max BSSID 4-255", "5"),
                    ("timeout", "Timeout s 0-255", "25"), ("pri", "Priority 0/1", "0")],
         "help": "Configure scan before starting."},
        {"label": "Start scan", "cmd": "AT*WIFICTRL=1", "fields": [],
         "help": "Results returned as *WIFICTRL URCs in the log."},
        {"label": "Start scan (FT mode)", "cmd": "AT*WIFICTRL=3", "fields": [],
         "help": "Fast-transition scan mode."},
        {"label": "Stop scan", "cmd": "AT*WIFICTRL=0", "fields": [],
         "help": "Abort an ongoing scan."},
    ]),

    # ------------------------------------------------------------------ SMS
    ("SMS", [
        {"label": "Set text mode", "cmd": "AT+CMGF=1", "fields": [],
         "help": "1 = text mode (required before sending/reading as text)."},
        {"label": "Set charset (GSM)", "cmd": 'AT+CSCS="GSM"', "fields": [],
         "help": "GSM 7-bit charset for plain ASCII text."},
        {"label": "Service centre (read)", "cmd": "AT+CSCA?", "fields": [],
         "help": "Show the SMSC number stored on the SIM."},
        {"label": "Set service centre", "cmd": 'AT+CSCA="{smsc}"',
         "fields": [("smsc", "SMSC number", "+8613800100500")],
         "help": "Set SMS centre number (usually taken from SIM automatically)."},
        {"label": "Send SMS", "cmd": 'AT+CMGS="{number}"',
         "fields": [("number", "Recipient", "+10000000000"),
                    ("message", "Message", "Hello from SLM332L")],
         "data": {"payload_field": "message", "auto_len_field": None,
                  "end": chr(26)},
         "help": "Text mode first. Sends message + Ctrl+Z after the '>' prompt. Needs SIM."},
        {"label": "List messages", "cmd": 'AT+CMGL="{stat}"',
         "fields": [("stat", 'ALL/REC UNREAD/REC READ', "ALL")],
         "help": "List stored SMS by status."},
        {"label": "Read message", "cmd": "AT+CMGR={index}",
         "fields": [("index", "Index", "1")],
         "help": "Read one stored SMS by index."},
        {"label": "Delete message", "cmd": "AT+CMGD={index},{flag}",
         "fields": [("index", "Index", "1"), ("flag", "0=one 4=all", "0")],
         "help": "Delete SMS. flag 4 = delete all."},
        {"label": "New-message indication", "cmd": "AT+CNMI=2,1,0,0,0", "fields": [],
         "help": "Report incoming SMS as +CMTI URC (shown in the log)."},
        {"label": "Storage info", "cmd": "AT+CPMS?", "fields": [],
         "help": "Message storage used/total for each memory."},
    ]),
]


def format_command(cmd_template, values):
    """Fill an AT template from a {key: value} dict, tolerating extras."""
    class _Safe(dict):
        def __missing__(self, key):
            return ""
    return cmd_template.format_map(_Safe(values))
