"""
DTI (Dial Test Indicator) gauge bridge — run this on Windows (NOT in Docker/WSL).

Reads a dimensional reading from a DTI gauge over RS-232/USB serial and POSTs
each reading to the Blade Rocking backend so the browser auto-fills the correct
height-position field (H1 … Hn) in the measurement form.

The bridge cycles through positions automatically after each captured reading.
The operator physically moves the probe tip to each position, then presses the
gauge's DATA/SEND button.  The bridge associates each incoming reading with the
next position in sequence and broadcasts it to the backend.

Usage:
    python dti_bridge.py                                          # COM7, H1-H4
    python dti_bridge.py --port COM4                             # different port
    python dti_bridge.py --port COM7 --positions H1 H2 H3 H4 H5 # five positions
    python dti_bridge.py --port COM7 --server https://192.168.1.50

Requirements (install once):
    pip install pyserial requests

Primary gauge (this deployment):
    Sylvac BT, 0.001 mm resolution (Bluetooth RS-232 adapter) — default COM7

Supported gauges (RS-232 / Bluetooth output):
    Sylvac BT, Mitutoyo 543 series, Mitutoyo 293 series, Mahr MarCator,
    Sylvac S_Dial Work / Smart, or any gauge producing a plain ASCII numeric
    reading per line.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from itertools import cycle

import requests
import serial
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_PORT      = "COM7"
DEFAULT_SERVER    = "https://localhost"
DEFAULT_POSITIONS = ["H1", "H2", "H3", "H4"]
PUSH_PATH         = "/api/v1/dti/push"
BAUD_RATES        = [9600, 4800, 2400, 19200, 38400]

# Many DTI gauges output: "+012.345\r\n" or "12.345\r\n" or "  12.345 mm\r\n"
_DTI_RE = re.compile(r"[+-]?\d+\.?\d*")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_reading(raw: str) -> float | None:
    """Extract the first numeric value from a raw gauge output line."""
    nums = _DTI_RE.findall(raw.strip())
    if not nums:
        return None
    try:
        return float(nums[0])
    except ValueError:
        return None


def _open_port(port: str, baud: int) -> serial.Serial | None:
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


def _connect(port: str) -> serial.Serial | None:
    """Try every baud rate in order. Return open Serial or None."""
    log.info("[serial] opening %s …", port)
    for baud in BAUD_RATES:
        ser = _open_port(port, baud)
        if ser:
            return ser
    log.error(
        "[serial] could not open %s at any baud rate.\n"
        "  • Is the DTI gauge powered on and plugged in?\n"
        "  • Is the COM port correct?  (Run: python -m serial.tools.list_ports)\n"
        "  • Is another application using the port?",
        port,
    )
    return None


# ─── Main loop ────────────────────────────────────────────────────────────────

def run(port: str, server: str, positions: list[str]) -> None:
    push_url = server.rstrip("/") + PUSH_PATH
    log.info("[http ] push URL → %s", push_url)
    log.info("[http ] SSL verification disabled (self-signed cert)")
    log.info("[dti  ] position sequence: %s (cycling)", " → ".join(positions))

    session = requests.Session()
    session.verify = False

    try:
        r = session.get(server.rstrip("/") + "/health", timeout=5)
        log.info("[http ] server reachable — status %s", r.status_code)
    except requests.RequestException as exc:
        log.error(
            "[http ] cannot reach server at %s: %s\n"
            "  • Is the server running?  (docker compose ps)\n"
            "  • Is the URL correct?  Try https://localhost or https://<server-ip>",
            server, exc,
        )
        return

    ser = _connect(port)
    if ser is None:
        return

    pos_cycle = cycle(positions)
    current_pos = next(pos_cycle)
    log.info("[ready] waiting for DTI reading at position %s — Ctrl+C to stop", current_pos)

    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                log.error("[serial] read error: %s — reconnecting in 5 s …", exc)
                try:
                    ser.close()
                except Exception:
                    pass
                time.sleep(5)
                ser = _connect(port)
                if ser is None:
                    return
                continue

            if not raw:
                time.sleep(0.05)
                continue

            decoded = raw.decode("ascii", errors="ignore").strip()
            if not decoded:
                continue

            value = _parse_reading(decoded)
            if value is None:
                log.debug("[dti  ] unparseable line: %r", decoded)
                continue

            log.info("[dti  ] %s = %.4f mm  →  posting …", current_pos, value)

            try:
                resp = session.post(
                    push_url,
                    json={"position": current_pos, "value": value},
                    timeout=3,
                )
                if resp.status_code == 200:
                    log.info("[http ] ✓ accepted  %s = %.4f", current_pos, value)
                else:
                    log.warning(
                        "[http ] server returned %d: %s",
                        resp.status_code, resp.text[:120],
                    )
            except requests.RequestException as exc:
                log.warning("[http ] POST failed: %s", exc)

            current_pos = next(pos_cycle)
            log.info("[dti  ] ready for next reading at position %s", current_pos)

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
        description="DTI gauge bridge for Blade Rocking System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dti_bridge.py
  python dti_bridge.py --port COM4
  python dti_bridge.py --port COM7 --positions H1 H2 H3 H4 H5
  python dti_bridge.py --port COM7 --server https://192.168.1.50

To list available COM ports:
  python -m serial.tools.list_ports

Typical DTI gauge RS-232 settings:
  Baud:  9600
  Data:  8 bits, No parity, 1 stop bit (8N1)
  Flow:  None (or Hardware for some Mitutoyo models)
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
        "--positions", nargs="+", default=DEFAULT_POSITIONS,
        metavar="Hn",
        help=(
            f"Ordered height positions to cycle through (default: {' '.join(DEFAULT_POSITIONS)}). "
            "Supply as space-separated list: --positions H1 H2 H3 H4 H5"
        ),
    )
    args = parser.parse_args()
    run(args.port, args.server, args.positions)


if __name__ == "__main__":
    main()
