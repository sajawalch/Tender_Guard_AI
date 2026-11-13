"""
TenderGuard AI — connection checker.

Tests, in order, every step between your computer and the OpenAI API, and
tells you which step fails and what usually causes it. Uses only Python's
standard library, so it runs even if other packages are broken.

Usage:
    python check_connection.py
"""

import os
import socket
import ssl
import sys
import urllib.error
import urllib.request

HOST = "api.openai.com"
PORT = 443
failed = []


def header(text):
    print(f"\n=== {text} ===")


def ok(msg):
    print(f"  OK    {msg}")


def bad(step, msg, hint):
    print(f"  FAIL  {msg}")
    print(f"        -> {hint}")
    failed.append(step)


# ---------------------------------------------------------------- 1
header("1. API key and network settings")
key = os.environ.get("OPENAI_API_KEY", "")
if key:
    ok(f"OPENAI_API_KEY is set ({key[:7]}..., {len(key)} characters)")
else:
    bad("key", "OPENAI_API_KEY is NOT set in this terminal",
        'Run:  $env:OPENAI_API_KEY="your_key"   (same terminal, then re-run this check)')

for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "OPENAI_BASE_URL"):
    val = os.environ.get(var) or os.environ.get(var.lower())
    if val:
        print(f"  NOTE  {var} is set to: {val}")
        print("        -> If this address is wrong or the proxy is down, requests fail with 'Connection error'.")

# ---------------------------------------------------------------- 2
header(f"2. DNS: can your computer find {HOST}?")
ips = []
try:
    infos = socket.getaddrinfo(HOST, PORT, proto=socket.IPPROTO_TCP)
    ips = sorted({i[4][0] for i in infos})
    ok(f"resolved to {', '.join(ips[:3])}")
except socket.gaierror as e:
    bad("dns", f"could not resolve {HOST} ({e})",
        "DNS problem. Change your DNS to 1.1.1.1 / 8.8.8.8 (Windows: Network settings -> "
        "adapter -> IPv4 -> Use the following DNS), or turn a VPN on/off, then retry.")

# ---------------------------------------------------------------- 3
header(f"3. TCP: can your computer open a connection to {HOST}:{PORT}?")
if ips:
    connected = False
    for ip in ips[:3]:
        try:
            with socket.create_connection((ip, PORT), timeout=10):
                ok(f"connected to {ip}")
                connected = True
                break
        except OSError as e:
            print(f"  ...   {ip}: {e}")
    if not connected:
        bad("tcp", "could not connect to any address",
            "Something is blocking the connection (firewall, ISP restriction, or a VPN/proxy that "
            "is down). Try a mobile hotspot, or switch a VPN on/off.")
else:
    print("  skip  (DNS failed)")

# ---------------------------------------------------------------- 4
header("4. TLS/SSL: is the secure handshake working?")
if ips and "tcp" not in failed:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((ips[0], PORT), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=HOST) as tls:
                ok(f"secure connection established ({tls.version()})")
    except ssl.SSLError as e:
        bad("tls", f"SSL error: {e}",
            "Usually antivirus 'HTTPS scanning', a corporate/school proxy, or a wrong system clock. "
            "Turn off HTTPS scanning in your antivirus, check your date/time, and run: "
            "pip install --upgrade certifi")
    except OSError as e:
        bad("tls", f"connection dropped during handshake: {e}",
            "A firewall or filter is cutting the connection mid-way. Try another network or a VPN.")
else:
    print("  skip  (earlier step failed)")

# ---------------------------------------------------------------- 5
header("5. API call: does OpenAI answer, and accept your key?")
if not failed or failed == ["key"]:
    req = urllib.request.Request(
        f"https://{HOST}/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok(f"OpenAI answered with status {resp.status} - connection and key both work")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            bad("auth", "reached OpenAI, but the key was rejected (401)",
                "Your connection is FINE. The key is wrong, deleted or has a typo. Create a new key "
                "at platform.openai.com/api-keys and set it again.")
        elif e.code == 429:
            bad("quota", "reached OpenAI, but got 429 (rate limit / no credit)",
                "Your connection is FINE. Check billing and credit at platform.openai.com/settings/organization/billing.")
        elif e.code == 403:
            bad("blocked", "reached OpenAI, but got 403 (access denied)",
                "Access is blocked for your network or region. Try a different network or a VPN.")
        else:
            bad("http", f"OpenAI answered with HTTP {e.code}", "Unexpected response - paste this output to me.")
    except Exception as e:
        bad("https", f"{type(e).__name__}: {e}",
            "The request failed before OpenAI could answer - see the earlier steps for the likely cause.")
else:
    print("  skip  (earlier step failed)")

# ---------------------------------------------------------------- summary
header("Summary")
if not failed:
    print("  Everything works. Run generate_bid.py again.")
else:
    print(f"  First problem found at step: {failed[0]}")
    print("  Fix that one first, then run this check again. Paste this whole output to me if stuck.")
sys.exit(0 if not failed else 1)