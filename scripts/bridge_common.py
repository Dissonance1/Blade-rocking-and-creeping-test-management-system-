"""
Shared helpers for the hardware bridge scripts (``dti_bridge.py``,
``weighing_bridge.py``).

Both bridges run standalone on the operator's Windows machine, POST readings
to the backend over HTTP(S), and need to tolerate the backend not being up
yet when the bridge starts — hence the shared session/reachability helpers.
"""

from __future__ import annotations

import logging
import time

import requests
import urllib3

log = logging.getLogger(__name__)


def build_session(insecure_ssl: bool) -> requests.Session:
    """Create the ``requests.Session`` used to talk to the backend.

    TLS verification is on by default; ``--insecure-ssl`` is the documented,
    explicit opt-in for the self-signed cert used on the LAN server.
    """
    session = requests.Session()
    if insecure_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log.warning(
            "[http ] SSL certificate verification DISABLED (--insecure-ssl) — "
            "only use this against the documented self-signed LAN server cert"
        )
        session.verify = False
    return session


def wait_until_reachable(session: requests.Session, server: str, retry_interval_s: int = 5) -> None:
    """Block (retrying forever) until ``server`` responds to /health."""
    attempt = 0
    while True:
        attempt += 1
        try:
            r = session.get(server.rstrip("/") + "/health", timeout=5)
            log.info("[http ] server reachable — status %s", r.status_code)
            return
        except requests.RequestException as exc:
            log.warning(
                "[http ] cannot reach server at %s (attempt %d): %s — retrying in %ds\n"
                "  • Is the server running?  (docker compose ps)\n"
                "  • Is the URL correct?  Try http://localhost or https://<server-ip>",
                server, attempt, exc, retry_interval_s,
            )
            time.sleep(retry_interval_s)
