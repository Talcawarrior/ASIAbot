"""
Smoke tests — verify the full stack (API + Dashboard) works end-to-end.

Run after bot is started: python -m pytest tests/test_smoke.py -v
"""

import os

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8091"


@pytest.fixture(scope="module")
def bot_running():
    """Check if bot is already running, skip if not."""
    try:
        r = requests.get(f"{BASE_URL}/api/status", timeout=5)
        if r.status_code == 200:
            yield True
            return
    except requests.ConnectionError:
        pass

    pytest.skip("Bot is not running on port 8091. Start with: python main.py run")


class TestAPIEndpoints:
    """Verify all critical API endpoints return valid responses."""

    def test_status_endpoint(self, bot_running):
        """GET /api/status should return 200 with portfolio data."""
        r = requests.get(f"{BASE_URL}/api/status", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "total_pnl" in data or "portfolio" in data, (
            f"Status response missing expected fields: {list(data.keys())}"
        )

    def test_health_check(self, bot_running):
        """GET /api/health-check should return 200."""
        r = requests.get(f"{BASE_URL}/api/health-check", timeout=10)
        assert r.status_code == 200

    def test_signals_endpoint(self, bot_running):
        """GET /api/signals should return 200 (may be slow)."""
        r = requests.get(f"{BASE_URL}/api/signals", timeout=30)
        assert r.status_code == 200

    def test_history_endpoint(self, bot_running):
        """GET /api/history should return 200."""
        r = requests.get(f"{BASE_URL}/api/history", timeout=10)
        assert r.status_code == 200

    def test_equity_curve(self, bot_running):
        """GET /api/equity-curve should return 200."""
        r = requests.get(f"{BASE_URL}/api/equity-curve", timeout=10)
        assert r.status_code == 200

    def test_weights_endpoint(self, bot_running):
        """GET /api/asi/weights should return 200 with model weights."""
        r = requests.get(f"{BASE_URL}/api/asi/weights", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict), "Weights should be a dictionary"

    def test_slippage_endpoint(self, bot_running):
        """GET /api/slippage should return 200 (may be slow)."""
        r = requests.get(f"{BASE_URL}/api/slippage", timeout=30)
        assert r.status_code == 200


class TestDashboard:
    """Verify the dashboard is served correctly."""

    def test_dashboard_loads(self, bot_running):
        """GET / should return HTML (dashboard or fallback)."""
        r = requests.get(f"{BASE_URL}/", timeout=10)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", ""), "Root should return HTML"

    def test_dashboard_not_fallback(self, bot_running):
        """Dashboard should NOT show the 'build required' fallback message."""
        r = requests.get(f"{BASE_URL}/", timeout=10)
        assert r.status_code == 200
        # If dashboard is built, it should NOT contain the fallback message
        assert "Build gerekli" not in r.text, (
            "Dashboard is showing fallback 'Build gerekli' message. Run: npx next build"
        )


class TestPortBinding:
    """Verify bot binds to the correct port."""

    def test_port_8091(self, bot_running):
        """Bot should be listening on port 8091."""
        r = requests.get(f"{BASE_URL}/api/status", timeout=5)
        assert r.status_code == 200, "Cannot reach bot on port 8091"
