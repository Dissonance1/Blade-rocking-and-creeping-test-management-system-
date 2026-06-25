"""
Weighing machine serial-port service.

Reads weight data from a serial port (Bluetooth or USB scale) and
yields new readings as they arrive.  Non-blocking: serial I/O runs in
a thread-pool executor so the async event loop is never blocked.

Configuration (via environment variables or .env):
    WEIGHING_COM_PORT   Serial device path (default: /dev/ttyS5, which is COM6 in WSL)
    WEIGHING_ENABLED    Set to "false" to disable hardware integration (default: true)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# COM6 on Windows maps to /dev/ttyS5 in WSL / Linux
COM_PORT: str = os.getenv("WEIGHING_COM_PORT", "/dev/ttyS5")
ENABLED: bool = os.getenv("WEIGHING_ENABLED", "true").lower() not in ("false", "0", "no")
BAUD_RATES: list[int] = [9600, 4800, 2400, 19200, 38400]
_WEIGHT_RE = re.compile(r"\d+\.?\d*")


def _parse_weight(raw: str) -> float | None:
    """Extract the largest number from a raw serial line (the weight value)."""
    numbers = _WEIGHT_RE.findall(raw.strip())
    if numbers:
        return max(float(n) for n in numbers)
    return None


def _open_serial(port: str, baud: int):
    """Open serial port synchronously — called via run_in_executor."""
    import serial  # imported lazily so startup doesn't fail if pyserial is missing
    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=2,
    )


def _readline_sync(ser) -> bytes:
    """Read one line from the serial port synchronously."""
    return ser.readline()


async def weight_stream() -> AsyncGenerator[float, None]:
    """
    Async generator that yields new weight readings from the scale.

    - Tries each baud rate in BAUD_RATES until a response is received.
    - Yields only when the weight value changes (stable reading).
    - On serial error, stops — the caller (WebSocket endpoint) handles reconnection.
    - If WEIGHING_ENABLED=false or the port can't be opened, the generator
      returns immediately (no yields).
    """
    if not ENABLED:
        logger.info("weighing_disabled")
        return

    loop = asyncio.get_event_loop()
    ser = None

    for baud in BAUD_RATES:
        try:
            s = await loop.run_in_executor(None, _open_serial, COM_PORT, baud)
            line = await loop.run_in_executor(None, _readline_sync, s)
            if line:
                ser = s
                logger.info("weighing_connected", port=COM_PORT, baud=baud)
                break
            s.close()
        except Exception as exc:
            logger.debug("weighing_baud_failed", baud=baud, error=str(exc))
            continue

    if ser is None:
        logger.warning("weighing_port_unavailable", port=COM_PORT)
        return

    last_weight: float | None = None
    try:
        while True:
            try:
                raw = await loop.run_in_executor(None, _readline_sync, ser)
                if not raw:
                    await asyncio.sleep(0.05)
                    continue

                decoded = raw.decode("ascii", errors="ignore").strip()
                weight = _parse_weight(decoded)

                if weight is not None and weight != last_weight:
                    last_weight = weight
                    yield weight

            except Exception as exc:
                logger.warning("weighing_read_error", error=str(exc))
                break
    finally:
        try:
            if ser and ser.is_open:
                ser.close()
                logger.info("weighing_disconnected", port=COM_PORT)
        except Exception:
            pass
