"""
Weighing machine bridge — run this on Windows (NOT in Docker/WSL).

Reads weight from a serial COM port and POSTs each reading to the
Blade Rocking backend so every open browser tab auto-fills the weight field.

Primary scale (this deployment):
    Adam Equipment iScale i-04, 0.1 g resolution, RS-232 output — default COM6

Usage:
    python weighing_bridge.py                          # COM6, server = http://localhost
    python weighing_bridge.py --port COM3              # different port
    python weighing_bridge.py --server https://192.168.1.50 --insecure-ssl  # remote server, self-signed cert

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
from bridge_common import wait_until_reachable as _wait_until_reachable

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

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_PORT   = "COM3"
DEFAULT_SERVER = "http://localhost"
PUSH_PATH      = "/api/v1/weighing/push"
BAUD_RATES     = [9600, 4800, 2400, 19200, 38400]
RETRY_INTERVAL_S = 5
_WEIGHT_RE     = re.compile(r"\d+\.?\d*")


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


def _connect(port: str):
    """Open the port, retrying forever until it succeeds.

    The scale is often powered on well after this bridge is started (or
    loses power mid-session), so a failed attempt must keep retrying rather
    than giving up — otherwise the bridge process exits and never notices
    when the scale comes back.
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
            "  • Is the device plugged in and powered on?\n"
            "  • Is the COM port correct?  (Run: python -m serial.tools.list_ports)\n"
            "  • Is another application (e.g. the scale software) using the port?",
            port, RETRY_INTERVAL_S,
        )
        time.sleep(RETRY_INTERVAL_S)


# ─── Main loop ────────────────────────────────────────────────────────────────

def _read_next_weight(ser: serial.Serial, port: str, last_weight):
    """Read and parse one line from the scale.

    Returns ``(ser, weight)`` — ``ser`` is a freshly reconnected handle if the
    port needed to be reopened; ``weight`` is ``None`` when there's nothing
    new to post this iteration (caller should just loop again).
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
        return _connect(port), None

    if not raw:
        time.sleep(0.05)
        return ser, None

    decoded = raw.decode("ascii", errors="ignore").strip()
    if not decoded:
        return ser, None

    weight = _parse_weight(decoded)
    if weight is None or weight == last_weight:
        return ser, None
    return ser, weight


def _post_weight(session: requests.Session, push_url: str, weight: float) -> None:
    try:
        resp = session.post(push_url, json={"value": weight}, timeout=3)
        if resp.status_code == 200:
            log.info("[http ] ✓ accepted (%.4f)", weight)
        else:
            log.warning("[http ] server returned %d: %s", resp.status_code, resp.text[:120])
    except requests.RequestException as exc:
        log.warning("[http ] POST failed: %s", exc)


def run(port: str, server: str, insecure_ssl: bool = False) -> None:
    push_url = server.rstrip("/") + PUSH_PATH
    log.info("[http ] push URL → %s", push_url)

    # Verify the server is reachable before opening the serial port — retry
    # forever rather than exiting, since the backend may come up after this
    # bridge is started.
    session = _build_session(insecure_ssl)
    _wait_until_reachable(session, server, RETRY_INTERVAL_S)

    ser = _connect(port)

    last_weight = None
    log.info("[ready] reading weight — Ctrl+C to stop")

    try:
        while True:
            ser, weight = _read_next_weight(ser, port, last_weight)
            if weight is None:
                continue

            last_weight = weight
            log.info("[scale] %.4f  →  posting …", weight)
            _post_weight(session, push_url, weight)

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
  python weighing_bridge.py
  python weighing_bridge.py --port COM3
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
        "--insecure-ssl", action="store_true",
        help=(
            "Disable TLS certificate verification. Only needed when --server "
            "is the documented self-signed cert on the LAN server; verified "
            "by default."
        ),
    )
    args = parser.parse_args()
    run(args.port, args.server, args.insecure_ssl)


if __name__ == "__main__":
    main()
