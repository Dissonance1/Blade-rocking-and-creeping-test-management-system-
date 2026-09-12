"""
Weighing machine bridge — run this on Windows (NOT in Docker/WSL).

Reads weight from a serial COM port and POSTs each reading to the
Blade Rocking backend so every open browser tab auto-fills the weight field.

Scale (this deployment):
    Adam Equipment iScale i-04, 0.1 g resolution, connected via an
    RS-232-to-Bluetooth SPP adapter, fixed at COM3 on this PC (iScale-BT-91).
    The other scale that used to share this PC (iScale-BT-0111) has moved to
    the HPTR PC — this bridge only ever opens the port it's told to, so it
    can never pick up that other scale even if it happens to be in
    Bluetooth range.

Two-PC deployment (e.g. the OH PC's own scale plus a second PC's own scale,
see CLAUDE.md's "Secondary Hardware Stations"): each PC's bridge must use a
different --station, or every browser tab on either PC receives both scales'
readings indiscriminately:
    OH PC:      python weighing_bridge.py --port COM3 --station 1
    Second PC:  python weighing_bridge.py --port COM3 --station 2 --server http://<OH PC>

    Each browser tab connects to the weighing WebSocket with ?station=1 or
    ?station=2 so readings from each scale only reach the matching form.

Whatever --server is given, this bridge also automatically falls back to
the other known OH-PC address (see KNOWN_OH_ADDRESSES) if that one stops
answering — the LAN IP and the NetBIOS hostname can fail independently of
each other (DNS/NetBIOS hiccup vs. an IP-level routing issue), and there's
no reason a reading should be lost just because whichever one happened to
be passed on the command line is temporarily the one having trouble.

Usage:
    python weighing_bridge.py                          # COM3, server = http://localhost, station 1
    python weighing_bridge.py --port COM6              # different port
    python weighing_bridge.py --server https://192.168.1.50 --insecure-ssl  # remote server, self-signed cert
    python weighing_bridge.py --station 2 --server http://172.146.5.98      # second PC

Requirements (install once):
    pip install pyserial requests
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import requests
import serial

from bridge_common import build_session as _build_session

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(_LOG_DIR / "weighing_bridge.log", encoding="utf-8")]
if sys.stderr is not None:
    _handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
)
log = logging.getLogger(__name__)

# ─── Known OH-PC addresses ────────────────────────────────────────────────────
# Kept in sync with dti_bridge.py's identical constant, oak1_camera_service.py's
# DEFAULT_ORIGINS, and CLAUDE.md's documented addresses for the OH PC — update
# all together if it ever changes. Always tried as a fallback after whatever
# --server was requested (see _candidate_servers), so a DNS/NetBIOS hiccup on
# the hostname or a routing issue on the IP doesn't independently take the
# bridge down when the other address would still have worked.
KNOWN_OH_ADDRESSES = ["http://172.146.5.98", "http://bladerocking-1-"]

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_PORT     = "COM3"
DEFAULT_SERVER   = "http://localhost"
PUSH_PATH        = "/api/v1/weighing/push"
BAUD_RATES       = [9600, 4800, 2400, 19200, 38400]
RETRY_INTERVAL_S = 5
_WEIGHT_RE       = re.compile(r"\d+\.?\d*")

# A Bluetooth SPP virtual COM port often doesn't raise SerialException when the
# scale is powered off or walks out of range — reads just keep timing out and
# returning nothing, forever, on a connection that's actually dead. If no byte
# at all has arrived in this long, treat the connection as stale and reopen
# the port rather than waiting on a connection nothing will ever answer on
# again.
_STALE_CONNECTION_S = 20


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_weight(raw: str):
    nums = _WEIGHT_RE.findall(raw.strip())
    return max(float(n) for n in nums) if nums else None


def _open_port(port: str, baud: int):
    """Try one baud rate; return an open Serial or None."""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2,
        )
        line = ser.readline()
        if line:
            log.info("[serial] connected to %s @ %d baud", port, baud)
            return ser
        ser.close()
    except serial.SerialException as exc:
        log.debug("[serial] %d baud failed: %s", baud, exc)
    return None


def _connect(port: str) -> serial.Serial:
    """Open the scale's port, retrying forever until it succeeds."""
    attempt = 0
    while True:
        attempt += 1
        log.info("[serial] opening %s (attempt %d) …", port, attempt)
        for baud in BAUD_RATES:
            ser = _open_port(port, baud)
            if ser:
                return ser
        log.warning(
            "[serial] could not open %s — retrying in %ds.\n"
            "  • Is the scale plugged in / paired and powered on?\n"
            "  • Is another application (e.g. the scale software) using the port?",
            port, RETRY_INTERVAL_S,
        )
        time.sleep(RETRY_INTERVAL_S)


# ─── Main loop ────────────────────────────────────────────────────────────────

def _read_next_weight(ser: serial.Serial, port: str, last_weight, last_data_at: float):
    """Read and parse one line from the scale.

    Returns ``(ser, weight, last_data_at)`` — ``ser`` is a freshly reconnected
    handle if the port needed to be reopened; ``weight`` is ``None`` when
    there's nothing new to post this iteration (caller should just loop
    again); ``last_data_at`` is the monotonic timestamp of the last time any
    byte was actually seen on the wire, refreshed here so the caller can
    detect a connection that's gone silent (see _STALE_CONNECTION_S).
    """
    try:
        raw = ser.readline()
    except serial.SerialException as exc:
        log.exception("[serial] read error: %s — reconnecting in 5 s …", exc)
        try:
            ser.close()
        except Exception:
            pass
        time.sleep(5)
        return _connect(port), None, time.monotonic()

    if not raw:
        if time.monotonic() - last_data_at > _STALE_CONNECTION_S:
            log.warning(
                "[serial] no data for %ds — scale likely powered off or out of "
                "range; reconnecting …", _STALE_CONNECTION_S,
            )
            try:
                ser.close()
            except Exception:
                pass
            return _connect(port), None, time.monotonic()
        time.sleep(0.05)
        return ser, None, last_data_at

    last_data_at = time.monotonic()
    decoded = raw.decode("ascii", errors="ignore").strip()
    if not decoded:
        return ser, None, last_data_at

    weight = _parse_weight(decoded)
    if weight is None or weight == last_weight:
        return ser, None, last_data_at
    return ser, weight, last_data_at


def _candidate_servers(server: str) -> list[str]:
    """Requested --server first, then the other known OH-PC address(es), de-duplicated."""
    candidates = [server]
    for addr in KNOWN_OH_ADDRESSES:
        if addr not in candidates:
            candidates.append(addr)
    return candidates


def _wait_until_any_reachable(session: requests.Session, servers: list[str], retry_interval_s: int) -> None:
    """Blocks (retrying forever) until at least one of ``servers`` responds to
    /health. Whichever one answers is moved to the front of ``servers`` (in
    place) so the rest of the run tries it first.
    """
    attempt = 0
    while True:
        attempt += 1
        for i, candidate in enumerate(servers):
            try:
                r = session.get(candidate.rstrip("/") + "/health", timeout=5)
                log.info("[http ] %s reachable — status %s", candidate, r.status_code)
                if i != 0:
                    servers.insert(0, servers.pop(i))
                return
            except requests.RequestException as exc:
                log.debug("[http ] %s unreachable: %s", candidate, exc)
        log.warning(
            "[http ] none of %s reachable (attempt %d) — retrying in %ds\n"
            "  • Is the server running?  (docker compose ps)\n"
            "  • Is the address correct?  Try http://localhost or https://<server-ip>",
            servers, attempt, retry_interval_s,
        )
        time.sleep(retry_interval_s)


def _post_weight(session: requests.Session, servers: list[str], weight: float, station: str) -> None:
    """Tries each of ``servers`` in order until one accepts the reading.
    Whichever one succeeds is moved to the front of ``servers`` (in place) so
    subsequent readings try it first — sticky to whichever address is
    actually working right now, without needing to know that in advance.
    """
    for i, server in enumerate(servers):
        push_url = server.rstrip("/") + PUSH_PATH
        try:
            resp = session.post(push_url, json={"value": weight, "station": station}, timeout=3)
            if resp.status_code == 200:
                log.info("[http ] ✓ accepted (%.4f) via %s", weight, server)
                if i != 0:
                    servers.insert(0, servers.pop(i))
                return
            log.warning("[http ] %s returned %d: %s", server, resp.status_code, resp.text[:120])
        except requests.RequestException as exc:
            log.warning("[http ] POST to %s failed: %s", server, exc)
    log.warning("[http ] weight %.4f could not be posted to any of %s", weight, servers)


def run(port: str, server: str, station: str, insecure_ssl: bool = False) -> None:
    servers = _candidate_servers(server)
    log.info("[http ] candidate servers (station %s, in order): %s", station, servers)

    # Verify at least one server is reachable before opening the serial port
    # — retry forever rather than exiting, since the backend may come up
    # after this bridge is started.
    session = _build_session(insecure_ssl)
    _wait_until_any_reachable(session, servers, RETRY_INTERVAL_S)

    ser = _connect(port)

    last_weight = None
    last_data_at = time.monotonic()
    log.info("[ready] reading weight — Ctrl+C to stop")

    try:
        while True:
            ser, weight, last_data_at = _read_next_weight(ser, port, last_weight, last_data_at)
            if weight is None:
                continue

            last_weight = weight
            log.info("[scale] %.4f  →  posting …", weight)
            _post_weight(session, servers, weight, station)

    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        try:
            if ser and ser.is_open:
                ser.close()
                log.info("[serial] port closed")
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Weighing machine bridge for Blade Rocking System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python weighing_bridge.py                     # COM3, station 1
  python weighing_bridge.py --port COM6         # different port
  python weighing_bridge.py --port COM6 --server https://192.168.1.50 --insecure-ssl

To list available COM ports:
  python -m serial.tools.list_ports
""",
    )
    parser.add_argument(
        "--port", default=DEFAULT_PORT,
        help=f"Windows COM port name (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER,
        help=f"Server base URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--station", default="1",
        help=(
            "Station identifier for this scale (default: 1). Use a different "
            "value on each PC that runs its own weighing bridge against the "
            "same central backend — otherwise every browser tab, on either "
            "PC, receives both scales' readings. The browser's measurement "
            "form must connect with the matching ?station= value."
        ),
    )
    parser.add_argument(
        "--insecure-ssl", action="store_true",
        help=(
            "Disable TLS certificate verification. Only needed when --server "
            "is the documented self-signed cert on the LAN server; verified "
            "by default."
        ),
    )
    args = parser.parse_args()
    run(args.port, args.server, args.station, args.insecure_ssl)


if __name__ == "__main__":
    main()
