"""OAuth2 helpers for Xero and QuickBooks direct integrations.

Handles:
- Building authorisation URLs with correct scopes
- Exchanging authorisation codes for token pairs
- Refreshing expired access tokens
- Fetching the Xero tenant ID after initial OAuth
- Encrypting / decrypting tokens at rest (Fernet)
"""

from __future__ import annotations

import base64
import logging
from uuid import UUID

import requests
from cryptography.fernet import Fernet

from src.config import settings
from src.db.models import AccountingPlatform

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform-specific OAuth constants
# ---------------------------------------------------------------------------

_XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
_XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
_XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
_XERO_SCOPES = (
    "openid profile email "
    "accounting.transactions.read accounting.contacts.read "
    "offline_access"
)

_QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
_QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_QB_SCOPES = "com.intuit.quickbooks.accounting"


# ---------------------------------------------------------------------------
# Token encryption
# ---------------------------------------------------------------------------


def encrypt_token(token: str) -> str:
    """Encrypt a token string using Fernet symmetric encryption.

    Args:
        token: The plaintext token to encrypt.

    Returns:
        The encrypted token as a URL-safe base64 string.
    """
    f = Fernet(settings.token_encryption_key.encode())
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted token string.

    Args:
        encrypted: The encrypted token (URL-safe base64).

    Returns:
        The original plaintext token.
    """
    f = Fernet(settings.token_encryption_key.encode())
    return f.decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# Auth URL generation
# ---------------------------------------------------------------------------


def generate_auth_url(platform: AccountingPlatform, sme_id: UUID, state: str) -> str:
    """Build the OAuth2 authorisation URL for the given platform.

    Args:
        platform: The accounting platform (XERO or QUICKBOOKS).
        sme_id: The SME initiating the connection (encoded in redirect).
        state: An opaque CSRF / state token.

    Returns:
        The full authorisation URL to redirect the user to.
    """
    redirect_uri = f"{settings.oauth_redirect_base_url}/oauth/{platform.value}/callback"

    if platform == AccountingPlatform.XERO:
        return (
            f"{_XERO_AUTH_URL}"
            f"?response_type=code"
            f"&client_id={settings.xero_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={_XERO_SCOPES}"
            f"&state={state}"
        )

    if platform == AccountingPlatform.QUICKBOOKS:
        return (
            f"{_QB_AUTH_URL}"
            f"?response_type=code"
            f"&client_id={settings.quickbooks_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={_QB_SCOPES}"
            f"&state={state}"
        )

    raise ValueError(f"OAuth not supported for platform: {platform}")


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Build a Basic auth header value from client credentials."""
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def exchange_code(platform: AccountingPlatform, code: str, redirect_uri: str) -> dict:
    """Exchange an authorisation code for access + refresh tokens.

    Args:
        platform: The accounting platform.
        code: The authorisation code from the OAuth callback.
        redirect_uri: The redirect URI used in the original auth request.

    Returns:
        The raw token response dict (access_token, refresh_token, expires_in, etc.).

    Raises:
        requests.exceptions.HTTPError: If the token request fails.
    """
    if platform == AccountingPlatform.XERO:
        token_url = _XERO_TOKEN_URL
        auth_header = _basic_auth_header(settings.xero_client_id, settings.xero_client_secret)
    elif platform == AccountingPlatform.QUICKBOOKS:
        token_url = _QB_TOKEN_URL
        auth_header = _basic_auth_header(
            settings.quickbooks_client_id, settings.quickbooks_client_secret
        )
    else:
        raise ValueError(f"OAuth not supported for platform: {platform}")

    resp = requests.post(
        token_url,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def refresh_access_token(platform: AccountingPlatform, refresh_token: str) -> dict:
    """Use a refresh token to obtain a new access token.

    Args:
        platform: The accounting platform.
        refresh_token: The current refresh token.

    Returns:
        The raw token response dict with new access_token (and possibly new refresh_token).

    Raises:
        requests.exceptions.HTTPError: If the refresh request fails.
    """
    if platform == AccountingPlatform.XERO:
        token_url = _XERO_TOKEN_URL
        auth_header = _basic_auth_header(settings.xero_client_id, settings.xero_client_secret)
    elif platform == AccountingPlatform.QUICKBOOKS:
        token_url = _QB_TOKEN_URL
        auth_header = _basic_auth_header(
            settings.quickbooks_client_id, settings.quickbooks_client_secret
        )
    else:
        raise ValueError(f"OAuth not supported for platform: {platform}")

    resp = requests.post(
        token_url,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Xero tenant ID
# ---------------------------------------------------------------------------


def get_xero_tenant_id(access_token: str) -> str:
    """Fetch the Xero tenant (organisation) ID after OAuth.

    Calls GET https://api.xero.com/connections and returns the tenantId
    of the first connected organisation.

    Args:
        access_token: A valid Xero access token.

    Returns:
        The tenant ID string.

    Raises:
        requests.exceptions.HTTPError: If the API call fails.
        ValueError: If no connections are returned.
    """
    resp = requests.get(
        _XERO_CONNECTIONS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()

    connections = resp.json()
    if not connections:
        raise ValueError("No Xero organisations connected for this token")

    tenant_id = connections[0]["tenantId"]
    logger.info("Resolved Xero tenant ID: %s", tenant_id)
    return tenant_id
