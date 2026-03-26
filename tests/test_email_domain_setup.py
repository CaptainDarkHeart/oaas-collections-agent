"""Tests for email domain setup dashboard routes and per-SME domain usage."""

from __future__ import annotations

import os

import pytest

# Ensure demo mode
os.environ.pop("SUPABASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from src.dashboard.app import (  # noqa: E402
    _DEMO_EMAIL_DOMAINS,
    _DEMO_INVOICES,
    _DEMO_SMES,
    app,
)

client = TestClient(app, headers={"Authorization": "Basic dXNlcjp0ZXN0"})


@pytest.fixture(autouse=True)
def _clear_demo_data():
    _DEMO_INVOICES.clear()
    _DEMO_SMES.clear()
    _DEMO_EMAIL_DOMAINS.clear()
    yield
    _DEMO_INVOICES.clear()
    _DEMO_SMES.clear()
    _DEMO_EMAIL_DOMAINS.clear()


def _create_sme(name: str = "Test Corp", email: str = "test@corp.com") -> str:
    """Create an SME via API and return its ID."""
    resp = client.post("/api/smes", json={"company_name": name, "contact_email": email})
    return resp.json()["id"]


class TestDomainPageNoDomain:
    def test_shows_registration_form(self):
        sme_id = _create_sme()
        resp = client.get(f"/sme/{sme_id}/domain")
        assert resp.status_code == 200
        assert "Connect Email Domain" in resp.text
        assert "domain_name" in resp.text
        assert "Register Domain" in resp.text

    def test_shows_new_flash(self):
        sme_id = _create_sme()
        resp = client.get(f"/sme/{sme_id}/domain?new=true")
        assert resp.status_code == 200
        assert "Client onboarded successfully" in resp.text

    def test_returns_404_for_unknown_sme(self):
        resp = client.get("/sme/00000000-0000-0000-0000-000000000000/domain")
        assert resp.status_code == 404


class TestDomainRegistration:
    def test_register_creates_domain_record(self):
        sme_id = _create_sme()
        resp = client.post(
            f"/sme/{sme_id}/domain",
            data={"domain_name": "mail.testcorp.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/sme/{sme_id}/domain" in resp.headers["location"]

        # Domain record should exist
        assert sme_id in _DEMO_EMAIL_DOMAINS
        domain = _DEMO_EMAIL_DOMAINS[sme_id]
        assert domain["domain_name"] == "mail.testcorp.com"
        assert domain["status"] == "pending"
        assert len(domain["dns_records"]) > 0

    def test_shows_dns_records_after_registration(self):
        sme_id = _create_sme()
        client.post(f"/sme/{sme_id}/domain", data={"domain_name": "mail.testcorp.com"})
        resp = client.get(f"/sme/{sme_id}/domain")
        assert resp.status_code == 200
        assert "DNS Configuration Required" in resp.text
        assert "mail.testcorp.com" in resp.text
        assert "Verify Domain" in resp.text

    def test_duplicate_registration_redirects(self):
        sme_id = _create_sme()
        client.post(f"/sme/{sme_id}/domain", data={"domain_name": "mail.testcorp.com"})
        # Second attempt should just redirect
        resp = client.post(
            f"/sme/{sme_id}/domain",
            data={"domain_name": "other.domain.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # Should still have the original domain
        assert _DEMO_EMAIL_DOMAINS[sme_id]["domain_name"] == "mail.testcorp.com"


class TestDomainVerification:
    def test_verify_marks_as_verified_in_demo(self):
        sme_id = _create_sme()
        client.post(f"/sme/{sme_id}/domain", data={"domain_name": "mail.testcorp.com"})

        resp = client.post(f"/sme/{sme_id}/domain/verify", follow_redirects=False)
        assert resp.status_code == 303
        assert "verified=true" in resp.headers["location"]

        domain = _DEMO_EMAIL_DOMAINS[sme_id]
        assert domain["status"] == "verified"
        assert domain["verified_at"] is not None

    def test_verified_page_shows_success(self):
        sme_id = _create_sme()
        client.post(f"/sme/{sme_id}/domain", data={"domain_name": "mail.testcorp.com"})
        client.post(f"/sme/{sme_id}/domain/verify")

        resp = client.get(f"/sme/{sme_id}/domain?verified=true")
        assert resp.status_code == 200
        assert "Domain Verified" in resp.text
        assert "Domain verified!" in resp.text

    def test_verified_shows_sending_email(self):
        sme_id = _create_sme()
        client.post(f"/sme/{sme_id}/domain", data={"domain_name": "mail.testcorp.com"})
        client.post(f"/sme/{sme_id}/domain/verify")

        resp = client.get(f"/sme/{sme_id}/domain")
        assert resp.status_code == 200
        assert "alex@mail.testcorp.com" in resp.text


class TestOnboardFlowIntoDomainSetup:
    def test_onboard_redirects_to_domain_page(self):
        resp = client.post(
            "/onboard",
            data={"company_name": "Flow Corp", "contact_email": "flow@corp.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/domain?new=true" in location
        assert "/sme/" in location
