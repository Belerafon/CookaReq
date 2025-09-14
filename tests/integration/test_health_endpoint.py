"""Tests for health endpoint."""
import pytest

pytestmark = pytest.mark.integration

def test_health_endpoint_returns_ok():
    from fastapi.testclient import TestClient

    from app.mcp.server import app

    client = TestClient(app)
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
