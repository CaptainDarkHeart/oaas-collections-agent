"""Tests for the Resend domain management wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.executor.domain_manager import ResendDomainManager


@pytest.fixture
def manager():
    with patch("src.executor.domain_manager.resend"):
        return ResendDomainManager()


class TestCreateDomain:
    def test_create_domain_success(self, manager):
        mock_records = [
            {"type": "TXT", "name": "example.com", "value": "v=spf1 include:resend.com ~all"},
            {"type": "CNAME", "name": "resend._domainkey.example.com", "value": "resend.domainkey.resend.dev"},
        ]
        with patch("src.executor.domain_manager.resend.Domains.create") as mock_create:
            mock_create.return_value = {"id": "dom_123", "records": mock_records}
            result = manager.create_domain("example.com")

        assert result.success is True
        assert result.domain_id == "dom_123"
        assert len(result.dns_records) == 2
        assert result.error is None

    def test_create_domain_failure(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.create") as mock_create:
            mock_create.side_effect = Exception("API error")
            result = manager.create_domain("bad.com")

        assert result.success is False
        assert result.domain_id is None
        assert "API error" in result.error


class TestVerifyDomain:
    def test_verify_domain_verified(self, manager):
        with (
            patch("src.executor.domain_manager.resend.Domains.verify"),
            patch("src.executor.domain_manager.resend.Domains.get") as mock_get,
        ):
            mock_get.return_value = {"status": "verified", "records": []}
            result = manager.verify_domain("dom_123")

        assert result.success is True
        assert result.status == "verified"

    def test_verify_domain_pending(self, manager):
        with (
            patch("src.executor.domain_manager.resend.Domains.verify"),
            patch("src.executor.domain_manager.resend.Domains.get") as mock_get,
        ):
            mock_get.return_value = {"status": "pending", "records": []}
            result = manager.verify_domain("dom_123")

        assert result.success is True
        assert result.status == "pending"

    def test_verify_domain_failure(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.verify") as mock_verify:
            mock_verify.side_effect = Exception("Not found")
            result = manager.verify_domain("bad_id")

        assert result.success is False
        assert "Not found" in result.error


class TestGetDomainStatus:
    def test_get_status(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.get") as mock_get:
            mock_get.return_value = {
                "status": "pending",
                "records": [{"type": "TXT", "name": "x", "value": "y", "status": "verified"}],
            }
            result = manager.get_domain_status("dom_123")

        assert result.success is True
        assert result.status == "pending"
        assert len(result.records) == 1

    def test_get_status_failure(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.get") as mock_get:
            mock_get.side_effect = Exception("Boom")
            result = manager.get_domain_status("bad")

        assert result.success is False


class TestDeleteDomain:
    def test_delete_success(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.remove"):
            assert manager.delete_domain("dom_123") is True

    def test_delete_failure(self, manager):
        with patch("src.executor.domain_manager.resend.Domains.remove") as mock_rm:
            mock_rm.side_effect = Exception("Nope")
            assert manager.delete_domain("bad") is False
