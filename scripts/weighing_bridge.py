"""
Weighing machine bridge — run this on Windows (NOT in Docker/WSL).

Reads weight from a serial COM port and POSTs each reading to the
Blade Rocking backend so every open browser tab auto-fills the weight field.

Scales (this deployment):
    Two Adam Equipment iScale i-04, 0.1 g resolution, each connected via an
    RS-232-to-Bluetooth SPP adapter. Only one is ever powered on at a time.
    Windows assigns whichever COM port is free at pairing time, and that
    assignment can shift after a re-pair — so this bridge auto-discovers the
    live scale by its stable Bluetooth MAC address (see KNOWN_SCALES) rather
    than a hard-coded COM port. Whichever scale is actually powered on gets
    picked up automatically; no need to know or care which COM it landed on.

Usage:
    python weighing_bridge.py                          # auto-discover, server = http://localhost
    python weighing_bridge.py --port COM3              # bypass discovery, pin to one port (testing)
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
import serial.tools.list_ports

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

# ─── Known scales ─────────────────────────────────────────────────────────────
# Bluetooth MAC (no separators, as it appears in the Windows serial port hwid)
# → friendly name, for the two scales paired to this OH station PC.
KNOWN_SCALES = {
    "0025020126B1": "iScale-BT-91",
    "00250201225E": "iScale-BT-0111",
}

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_SERVER = "http://localhost"
PUSH_PATH      = "/api/v1/weighing/push"
BAUD_RATES     = [9600, 4800, 2400, 19200, 38400]
RETRY_INTERVAL_S = 5
_WEIGHT_RE     = re.compile(r"\d+\.?\d*")


def _known_scale_ports() -> list[tuple[str, str]]:
    """Resolve each KNOWN_SCALES MAC to its current COM port, if paired/visible.

    Returns a list of (port, label) pairs. A MAC with no matching port isn't
    currently paired/visible to Windows and is skipped — this is normal when
    that scale is simply powered off.
    """
    found = []
    for info in serial.tools.list_ports.comports():
        hwid = (info.hwid or "").upper()
        for mac, label in KNOWN_SCALES.items():
            if mac in hwid:
                found.append((info.device, label))
                break
    return found


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


def _connect(port_override: str | None):
    """Open a scale's port, retrying forever until it succeeds.

    With no override, each attempt re-resolves KNOWN_SCALES to whichever COM
    ports are currently paired/visible and tries all of them — so it doesn't
    matter which scale is powered on, or which COM port Windows assigned it.
    A failed attempt must keep retrying rather than giving up — otherwise the
    bridge process exits and never notices when a scale comes on (or switches
    from one scale to the other).
    """
    attempt = 0
    while True:
        attempt += 1
        candidates = [(port_override, "manual")] if port_override else _known_scale_ports()
        if not candidates:
            log.warning(
                "[serial] no known scale currently paired/visible (attempt %d) — "
                "retrying in %ds. Is a scale powered on?", attempt, RETRY_INTERVAL_S,
            )
        for port, label in candidates:
            log.info("[serial] trying %s (%s), attempt %d …", port, label, attempt)
            for baud in BAUD_RATES:
                ser = _open_port(port, baud)
                if ser:
                    log.info("[serial] %s is active on %s", label, port)
                    return ser
        if candidates:
            log.warning(
                "[serial] no known scale responded — retrying in %ds.\n"
                "  • Is a scale plugged in and powered on?\n"
                "  • Is it paired in Windows Bluetooth settings?\n"
                "  • Is another application (e.g. the scale software) using the port?",
                RETRY_INTERVAL_S,
            )
        time.sleep(RETRY_INTERVAL_S)


# ─── Main loop ────────────────────────────────────────────────────────────────

def _read_next_weight(ser: serial.Serial, port_override: str | None, last_weight):
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
        return _connect(port_override), None

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


def run(port_override: str | None, server: str, insecure_ssl: bool = False) -> None:
    push_url = server.rstrip("/") + PUSH_PATH
    log.info("[http ] push URL → %s", push_url)

    # Verify the server is reachable before opening the serial port — retry
    # forever rather than exiting, since the backend may come up after this
    # bridge is started.
    session = _build_session(insecure_ssl)
    _wait_until_reachable(session, server, RETRY_INTERVAL_S)

    ser = _connect(port_override)

    last_weight = None
    log.info("[ready] reading weight — Ctrl+C to stop")

    try:
        while True:
            ser, weight = _read_next_weight(ser, port_override, last_weight)
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
  python weighing_bridge.py                     # auto-discover a known scale
  python weighing_bridge.py --port COM3         # pin to one port (bypass discovery)
  python weighing_bridge.py --port COM6 --server https://192.168.1.50 --insecure-ssl

To list available COM ports:
  python -m serial.tools.list_ports
""",
    )
    parser.add_argument(
        "--port", default=None,
        help=(
            "Manually pin to a specific Windows COM port, bypassing "
            "auto-discovery by Bluetooth device name. Rarely needed — by "
            "default, whichever scale in KNOWN_SCALES is powered on is "
            "found automatically."
        ),
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
