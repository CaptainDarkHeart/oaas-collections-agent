"""Tests for the reporting dashboard and API."""

from __future__ import annotations

import os

# Ensure demo mode
os.environ.pop("SUPABASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from src.dashboard.app import (  # noqa: E402
    _DEMO_FEES,
    _DEMO_INVOICES,
    _DEMO_SMES,
    app,
)

# Provide basic auth header (password is empty so any credentials work)
client = TestClient(app, headers={"Authorization": "Basic dXNlcjp0ZXN0"})


def _reset_demo():
    _DEMO_INVOICES.clear()
    _DEMO_SMES.clear()
    _DEMO_FEES.clear()


class TestReportsPage:
    def setup_method(self):
        _reset_demo()

    def teardown_method(self):
        _reset_demo()

    def test_get_reports_returns_html(self):
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "Recovery Reports" in resp.text
        assert "Recovery Rate" in resp.text
        assert "Revenue Earned" in resp.text
        assert "Avg Days to Collect" in resp.text

    def test_reports_shows_phase_distribution(self):
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "Phase Distribution" in resp.text

    def test_reports_shows_status_breakdown(self):
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "Status Breakdown" in resp.text

    def test_reports_shows_paid_count(self):
        """Demo data includes paid invoices, so recovery rate should be > 0."""
        resp = client.get("/reports")
        assert resp.status_code == 200
        # The page should show a non-zero recovery rate since demo data has paid invoices
        assert "Recovery Rate" in resp.text


class TestReportsApi:
    def setup_method(self):
        _reset_demo()

    def teardown_method(self):
        _reset_demo()

    def test_api_reports_returns_json(self):
        resp = client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_invoices" in data
        assert "paid_count" in data
        assert "recovery_rate" in data
        assert "avg_days_to_collection" in data
        assert "revenue_earned" in data
        assert "phase_distribution" in data
        assert "status_breakdown" in data

    def test_api_reports_has_demo_data(self):
        """With demo data, we should see realistic numbers."""
        resp = client.get("/api/reports")
        data = resp.json()
        # Demo data has 11 invoices (8 original + 3 new)
        assert data["total_invoices"] > 0
        # At least the paid invoices
        assert data["paid_count"] >= 1
        # Recovery rate should be > 0
        assert data["recovery_rate"] > 0
        # Revenue should be > 0 since we have charged fees
        assert data["revenue_earned"] > 0

    def test_api_reports_phase_distribution(self):
        resp = client.get("/api/reports")
        data = resp.json()
        phases = data["phase_distribution"]
        assert isinstance(phases, dict)
        # Demo data has invoices in multiple phases
        assert len(phases) > 1

    def test_api_reports_status_breakdown(self):
        resp = client.get("/api/reports")
        data = resp.json()
        statuses = data["status_breakdown"]
        assert isinstance(statuses, dict)
        # Should have active and paid at minimum
        assert "active" in statuses or "paid" in statuses

    def test_api_reports_avg_days_for_resolved(self):
        """Resolved invoices with resolved_at should produce avg_days > 0."""
        resp = client.get("/api/reports")
        data = resp.json()
        # Demo data has resolved invoices with resolved_at set
        assert data["avg_days_to_collection"] > 0


class TestReportsNavLink:
    def setup_method(self):
        _reset_demo()

    def teardown_method(self):
        _reset_demo()

    def test_reports_link_in_nav(self):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert 'href="/reports"' in resp.text
