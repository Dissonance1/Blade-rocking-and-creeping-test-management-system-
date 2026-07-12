"""
DTI (Dial Test Indicator) gauge bridge — run this on Windows (NOT in Docker/WSL).

Reads a dimensional reading from a DTI gauge over RS-232/USB serial and POSTs
each reading to the Blade Rocking backend so the browser auto-fills the correct
height-position field (H1 … Hn) in the measurement form.

The bridge cycles through positions automatically after each captured reading.
The operator physically moves the probe tip to each position, then presses the
gauge's DATA/SEND button.  The bridge associates each incoming reading with the
next position in sequence and broadcasts it to the backend.

Two-station deployment (two gauges, two blades simultaneously):
    Station 1 (e.g. OH Rig 1):
        python dti_bridge.py --port COM1 --station 1
    Station 2 (e.g. OH Rig 2):
        python dti_bridge.py --port COM2 --station 2

    Each browser tab connects to the DTI WebSocket with ?station=1 or ?station=2
    so readings from each gauge only reach the matching measurement form.

Usage:
    python dti_bridge.py                                          # COM7, station 1, H1-H4
    python dti_bridge.py --port COM1 --station 1                 # rig 1
    python dti_bridge.py --port COM2 --station 2                 # rig 2
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
import sys
import time
from pathlib import Path

import requests
import serial
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(_LOG_DIR / "dti_bridge.log", encoding="utf-8")]
if sys.stderr is not None:
    _handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
)
log = logging.getLogger(__name__)

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_PORT     = "COM1"
DEFAULT_SERVER   = "http://localhost"
DEFAULT_STATION  = "1"
PUSH_PATH        = "/api/v1/dti/push"
POSITIONS_PATH   = "/api/v1/dti/positions"
BAUD_RATES       = [9600, 4800, 2400, 19200, 38400]
RETRY_INTERVAL_S = 5

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
    """Open the port at the given baud rate; return Serial or None on error."""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        ser.reset_input_buffer()  # discard any data buffered before we connected
        log.info("[serial] connected to %s @ %d baud", port, baud)
        return ser
    except serial.SerialException as exc:
        log.debug("[serial] %d baud failed: %s", baud, exc)
    return None


def _connect(port: str) -> serial.Serial:
    """Open the port, retrying forever until it succeeds.

    For virtual COM ports (VMux2) just opening at any baud is enough.
    """
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
            "  • Is VMux2 running and configured with this COM port?\n"
            "  • Is the COM port correct?  (Run: python -m serial.tools.list_ports)\n"
            "  • Is another application using the port?",
            port, RETRY_INTERVAL_S,
        )
        time.sleep(RETRY_INTERVAL_S)


# ─── Main loop ────────────────────────────────────────────────────────────────

def run(port: str, server: str, station: str) -> None:
    push_url = server.rstrip("/") + PUSH_PATH
    positions_url = server.rstrip("/") + POSITIONS_PATH
    log.info("[http ] push URL → %s", push_url)
    log.info("[http ] SSL verification disabled (self-signed cert)")
    log.info("[dti  ] station: %s", station)

    session = requests.Session()
    session.verify = False

    attempt = 0
    while True:
        attempt += 1
        try:
            r = session.get(server.rstrip("/") + "/health", timeout=5)
            log.info("[http ] server reachable — status %s", r.status_code)
            break
        except requests.RequestException as exc:
            log.warning(
                "[http ] cannot reach server at %s (attempt %d): %s — retrying in %ds",
                server, attempt, exc, RETRY_INTERVAL_S,
            )
            time.sleep(RETRY_INTERVAL_S)

    ser = _connect(port)

    current_pos = "H1"  # advances via the server's next_position after each accepted reading
    last_value = None             # value of the last accepted reading
    last_accepted = 0.0           # monotonic timestamp of last accepted reading
    DEBOUNCE_S    = 1.5           # ignore a repeat of the SAME value within this window
                                   # (Sylvac BT duplicate-frame quirk — BT latency on the
                                   # second frame is variable, so debounce on value+time,
                                   # not time alone, or a real second reading taken quickly
                                   # gets silently dropped instead of the duplicate)

    log.info("[ready] waiting for DTI reading at position %s — Ctrl+C to stop", current_pos)

    try:
        while True:
            try:
                raw = ser.read_until(b'\r')
            except serial.SerialException as exc:
                log.error("[serial] read error: %s — reconnecting in 5 s …", exc)
                try:
                    ser.close()
                except Exception:
                    pass
                time.sleep(5)
                ser = _connect(port)
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

            # Debounce: Sylvac BT can emit the same frame twice on one DATA press
            now = time.monotonic()
            if value == last_value and now - last_accepted < DEBOUNCE_S:
                log.debug("[dti  ] debounced (%.0f ms since last, same value) — skipping %r", (now - last_accepted) * 1000, decoded)
                continue
            last_value = value
            last_accepted = now

            log.info("[dti  ] %s = %.4f mm  →  posting (station %s) …", current_pos, value, station)

            try:
                resp = session.post(
                    push_url,
                    json={"station": station, "position": current_pos, "value": value},
                    timeout=3,
                )
                if resp.status_code == 200:
                    log.info("[http ] ✓ accepted  value = %.4f", value)
                    try:
                        next_position = resp.json().get("next_position")
                    except ValueError:
                        next_position = None
                    if next_position:
                        current_pos = next_position
                else:
                    log.warning(
                        "[http ] server returned %d: %s",
                        resp.status_code, resp.text[:120],
                    )
            except requests.RequestException as exc:
                log.warning("[http ] POST failed: %s", exc)

            log.info("[dti  ] ready for next reading at position %s — press DATA", current_pos)

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
  python dti_bridge.py --port COM1 --station 1   # rig 1
  python dti_bridge.py --port COM2 --station 2   # rig 2  (separate terminal)
  python dti_bridge.py --port COM4
  python dti_bridge.py --port COM7 --server https://192.168.1.50

Position count is read from the server automatically — it matches however
many rows are in the measurement form at the time of each reading.

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
        "--station", default=DEFAULT_STATION,
        help=(
            f"Station identifier for this rig (default: {DEFAULT_STATION}). "
            "Use --station 1 for rig 1 (COM1) and --station 2 for rig 2 (COM2). "
            "The browser measurement form must connect with the matching ?station= value."
        ),
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Log every raw serial line, including ones skipped as unparseable or debounced.",
    )
    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    run(args.port, args.server, args.station)


if __name__ == "__main__":
    main()
