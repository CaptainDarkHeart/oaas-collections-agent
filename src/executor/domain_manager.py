"""Resend domain management for per-SME custom email domains.

Handles:
- Registering customer domains with Resend
- Retrieving DNS records for configuration
- Checking and triggering domain verification
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import resend

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DomainCreateResult:
    success: bool
    domain_id: str | None = None
    dns_records: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class DomainStatusResult:
    success: bool
    status: str = "not_started"
    records: list[dict] = field(default_factory=list)
    error: str | None = None


class ResendDomainManager:
    """Wraps the Resend Domains API for custom email domain setup."""

    def __init__(self) -> None:
        resend.api_key = settings.resend_api_key

    def create_domain(self, domain_name: str) -> DomainCreateResult:
        """Register a domain with Resend. Returns domain ID and DNS records."""
        try:
            result = resend.Domains.create({"name": domain_name})
            records = result.get("records", [])
            return DomainCreateResult(
                success=True,
                domain_id=result["id"],
                dns_records=records,
            )
        except Exception as e:
            logger.exception("Failed to create domain %s", domain_name)
            return DomainCreateResult(success=False, error=str(e))

    def verify_domain(self, domain_id: str) -> DomainStatusResult:
        """Trigger verification and return current status."""
        try:
            resend.Domains.verify(domain_id)
            return self.get_domain_status(domain_id)
        except Exception as e:
            logger.exception("Failed to verify domain %s", domain_id)
            return DomainStatusResult(success=False, error=str(e))

    def get_domain_status(self, domain_id: str) -> DomainStatusResult:
        """Check current domain verification status."""
        try:
            domain = resend.Domains.get(domain_id)
            records = domain.get("records", [])
            return DomainStatusResult(
                success=True,
                status=domain.get("status", "not_started"),
                records=records,
            )
        except Exception as e:
            logger.exception("Failed to get domain status %s", domain_id)
            return DomainStatusResult(success=False, error=str(e))

    def delete_domain(self, domain_id: str) -> bool:
        """Remove a domain from Resend."""
        try:
            resend.Domains.remove(domain_id)
            return True
        except Exception:
            logger.exception("Failed to delete domain %s", domain_id)
            return False
