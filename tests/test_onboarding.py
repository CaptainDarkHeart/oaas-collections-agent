"""Tests for SME onboarding API and dashboard page."""

from __future__ import annotations

import os
from uuid import UUID

import pytest

# Ensure demo mode
os.environ.pop("SUPABASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from src.dashboard.app import (  # noqa: E402
    _DEMO_INVOICES,
    _DEMO_SMES,
    app,
)

# Provide basic auth header (password is empty so any credentials work)
client = TestClient(app, headers={"Authorization": "Basic dXNlcjp0ZXN0"})


@pytest.fixture(autouse=True)
def _clear_demo_data():
    """Reset demo data between tests."""
    _DEMO_INVOICES.clear()
    _DEMO_SMES.clear()
    yield
    _DEMO_INVOICES.clear()
    _DEMO_SMES.clear()


class TestOnboardPage:
    def test_get_onboard_returns_form(self):
        resp = client.get("/onboard")
        assert resp.status_code == 200
        assert "Add New Client" in resp.text
        assert "company_name" in resp.text
        assert "contact_email" in resp.text
        assert "accounting_platform" in resp.text
        assert "discount_authorised" in resp.text
        assert "max_discount_percent" in resp.text

    def test_post_onboard_creates_sme_and_redirects(self):
        resp = client.post(
            "/onboard",
            data={
                "company_name": "Test Corp",
                "contact_email": "test@corp.com",
                "contact_phone": "+447700000000",
                "accounting_platform": "xero",
                "max_discount_percent": "5",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/domain?new=true" in resp.headers["location"]
        # Verify SME was created
        assert len(_DEMO_SMES) >= 1
        sme = list(_DEMO_SMES.values())[-1]
        assert sme["company_name"] == "Test Corp"
        assert sme["contact_email"] == "test@corp.com"

    def test_post_onboard_without_optional_fields(self):
        resp = client.post(
            "/onboard",
            data={
                "company_name": "Minimal Ltd",
                "contact_email": "min@test.com",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_dashboard_shows_onboarded_flash(self):
        resp = client.get("/?onboarded=true")
        assert resp.status_code == 200
        assert "New client onboarded successfully" in resp.text


class TestSmeApi:
    def test_post_api_smes_creates_sme(self):
        resp = client.post(
            "/api/smes",
            json={
                "company_name": "API Corp",
                "contact_email": "api@corp.com",
                "contact_phone": "+441234567890",
                "accounting_platform": "quickbooks",
                "discount_authorised": True,
                "max_discount_percent": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_name"] == "API Corp"
        assert data["contact_email"] == "api@corp.com"
        # ID should be a valid UUID
        UUID(data["id"])

    def test_post_api_smes_defaults(self):
        resp = client.post(
            "/api/smes",
            json={
                "company_name": "Default Corp",
                "contact_email": "default@corp.com",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_name"] == "Default Corp"

    def test_get_api_sme_by_id(self):
        # Create first
        create_resp = client.post(
            "/api/smes",
            json={
                "company_name": "Fetch Corp",
                "contact_email": "fetch@corp.com",
            },
        )
        sme_id = create_resp.json()["id"]

        resp = client.get(f"/api/smes/{sme_id}")
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "Fetch Corp"

    def test_get_api_sme_not_found(self):
        resp = client.get("/api/smes/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_patch_api_sme(self):
        # Create first
        create_resp = client.post(
            "/api/smes",
            json={
                "company_name": "Patch Corp",
                "contact_email": "patch@corp.com",
            },
        )
        sme_id = create_resp.json()["id"]

        resp = client.patch(
            f"/api/smes/{sme_id}",
            json={"company_name": "Updated Corp", "discount_authorised": True},
        )
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "Updated Corp"
        assert resp.json()["discount_authorised"] is True

    def test_patch_api_sme_not_found(self):
        resp = client.patch(
            "/api/smes/00000000-0000-0000-0000-000000000000",
            json={"company_name": "Nope"},
        )
        assert resp.status_code == 404

    def test_list_api_smes(self):
        # Create two SMEs
        client.post("/api/smes", json={"company_name": "A", "contact_email": "a@a.com"})
        client.post("/api/smes", json={"company_name": "B", "contact_email": "b@b.com"})

        resp = client.get("/api/smes")
        assert resp.status_code == 200
        names = [s["company_name"] for s in resp.json()]
        assert "A" in names
        assert "B" in names


class TestNavLinks:
    def test_nav_has_add_client_link(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'href="/onboard"' in resp.text
        assert "Add Client" in resp.text

    def test_nav_has_reports_link(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'href="/reports"' in resp.text
        assert "Reports" in resp.text
