"""Tests for OAuth2 helpers (Xero and QuickBooks)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from src.db.models import AccountingPlatform
from src.sentry.oauth import (
    decrypt_token,
    encrypt_token,
    exchange_code,
    generate_auth_url,
    get_xero_tenant_id,
    refresh_access_token,
)

# Use a real Fernet key for encryption tests
_TEST_FERNET_KEY = Fernet.generate_key().decode()


class TestGenerateAuthUrl:
    @patch("src.sentry.oauth.settings")
    def test_xero_auth_url(self, mock_settings):
        mock_settings.xero_client_id = "xero-client-123"
        mock_settings.oauth_redirect_base_url = "https://app.example.com"

        sme_id = uuid4()
        url = generate_auth_url(AccountingPlatform.XERO, sme_id, state="csrf-token")

        assert url.startswith("https://login.xero.com/identity/connect/authorize")
        assert "client_id=xero-client-123" in url
        assert "redirect_uri=https://app.example.com/oauth/xero/callback" in url
        assert "state=csrf-token" in url
        assert "accounting.transactions.read" in url
        assert "offline_access" in url

    @patch("src.sentry.oauth.settings")
    def test_quickbooks_auth_url(self, mock_settings):
        mock_settings.quickbooks_client_id = "qb-client-456"
        mock_settings.oauth_redirect_base_url = "https://app.example.com"

        sme_id = uuid4()
        url = generate_auth_url(AccountingPlatform.QUICKBOOKS, sme_id, state="csrf-token")

        assert url.startswith("https://appcenter.intuit.com/connect/oauth2")
        assert "client_id=qb-client-456" in url
        assert "redirect_uri=https://app.example.com/oauth/quickbooks/callback" in url
        assert "state=csrf-token" in url
        assert "com.intuit.quickbooks.accounting" in url

    @patch("src.sentry.oauth.settings")
    def test_unsupported_platform_raises(self, mock_settings):
        with pytest.raises(ValueError, match="OAuth not supported"):
            generate_auth_url(AccountingPlatform.CSV, uuid4(), state="s")


class TestTokenEncryption:
    @patch("src.sentry.oauth.settings")
    def test_encrypt_decrypt_roundtrip(self, mock_settings):
        mock_settings.token_encryption_key = _TEST_FERNET_KEY

        original = "my-secret-access-token-abc123"
        encrypted = encrypt_token(original)

        assert encrypted != original
        assert decrypt_token(encrypted) == original

    @patch("src.sentry.oauth.settings")
    def test_different_tokens_produce_different_ciphertext(self, mock_settings):
        mock_settings.token_encryption_key = _TEST_FERNET_KEY

        enc1 = encrypt_token("token-one")
        enc2 = encrypt_token("token-two")
        assert enc1 != enc2


class TestExchangeCode:
    @patch("src.sentry.oauth.requests.post")
    @patch("src.sentry.oauth.settings")
    def test_xero_exchange_code(self, mock_settings, mock_post):
        mock_settings.xero_client_id = "xero-id"
        mock_settings.xero_client_secret = "xero-secret"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = exchange_code(
            AccountingPlatform.XERO,
            code="auth-code-123",
            redirect_uri="https://app.example.com/oauth/xero/callback",
        )

        assert result["access_token"] == "new-access"
        # Verify the correct Xero token URL was called
        call_args = mock_post.call_args
        assert "identity.xero.com/connect/token" in call_args.args[0]
        assert call_args.kwargs["data"]["grant_type"] == "authorization_code"
        assert call_args.kwargs["data"]["code"] == "auth-code-123"

    @patch("src.sentry.oauth.requests.post")
    @patch("src.sentry.oauth.settings")
    def test_quickbooks_exchange_code(self, mock_settings, mock_post):
        mock_settings.quickbooks_client_id = "qb-id"
        mock_settings.quickbooks_client_secret = "qb-secret"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "qb-access",
            "refresh_token": "qb-refresh",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = exchange_code(
            AccountingPlatform.QUICKBOOKS,
            code="qb-auth-code",
            redirect_uri="https://app.example.com/oauth/quickbooks/callback",
        )

        assert result["access_token"] == "qb-access"
        call_args = mock_post.call_args
        assert "oauth.platform.intuit.com" in call_args.args[0]

    @patch("src.sentry.oauth.requests.post")
    @patch("src.sentry.oauth.settings")
    def test_exchange_code_unsupported_platform(self, mock_settings, mock_post):
        with pytest.raises(ValueError, match="OAuth not supported"):
            exchange_code(AccountingPlatform.CSV, code="x", redirect_uri="x")


class TestRefreshAccessToken:
    @patch("src.sentry.oauth.requests.post")
    @patch("src.sentry.oauth.settings")
    def test_xero_refresh(self, mock_settings, mock_post):
        mock_settings.xero_client_id = "xero-id"
        mock_settings.xero_client_secret = "xero-secret"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "refreshed-access",
            "refresh_token": "refreshed-refresh",
            "expires_in": 1800,
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = refresh_access_token(AccountingPlatform.XERO, "old-refresh-token")

        assert result["access_token"] == "refreshed-access"
        call_args = mock_post.call_args
        assert call_args.kwargs["data"]["grant_type"] == "refresh_token"
        assert call_args.kwargs["data"]["refresh_token"] == "old-refresh-token"

    @patch("src.sentry.oauth.requests.post")
    @patch("src.sentry.oauth.settings")
    def test_quickbooks_refresh(self, mock_settings, mock_post):
        mock_settings.quickbooks_client_id = "qb-id"
        mock_settings.quickbooks_client_secret = "qb-secret"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "qb-refreshed",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = refresh_access_token(AccountingPlatform.QUICKBOOKS, "qb-old-refresh")

        assert result["access_token"] == "qb-refreshed"
        call_args = mock_post.call_args
        assert "oauth.platform.intuit.com" in call_args.args[0]


class TestGetXeroTenantId:
    @patch("src.sentry.oauth.requests.get")
    def test_returns_first_tenant_id(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"tenantId": "tenant-abc-123", "tenantType": "ORGANISATION"},
        ]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        tenant_id = get_xero_tenant_id("access-token-xyz")

        assert tenant_id == "tenant-abc-123"
        call_args = mock_get.call_args
        assert "api.xero.com/connections" in call_args.args[0]
        assert "Bearer access-token-xyz" in call_args.kwargs["headers"]["Authorization"]

    @patch("src.sentry.oauth.requests.get")
    def test_no_connections_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match="No Xero organisations"):
            get_xero_tenant_id("access-token-xyz")
