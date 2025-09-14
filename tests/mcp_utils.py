"""Utilities for MCP-related tests."""

import time
from http.client import HTTPConnection


def _request(port, headers=None):
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/health", headers=headers or {})
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def _try_request(port, headers=None) -> bool:
    try:
        _request(port, headers=headers)
    except ConnectionRefusedError:
        return False
    return True


def _wait_until_ready(port, headers=None):
    for _ in range(50):
        if _try_request(port, headers=headers):
            return
        time.sleep(0.1)
