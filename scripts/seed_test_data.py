"""Create test SME and invoices for development.

Usage:
    python -m scripts.seed_test_data
"""

from datetime import date, timedelta
from decimal import Decimal

from src.db.models import (
    AccountingPlatform,
    Contact,
    ContactSource,
    Database,
    Invoice,
    SME,
)


def seed() -> None:
    db = Database()

    # Create a test SME
    sme = SME(
        company_name="Acme Digital Ltd",
        contact_email="owner@acmedigital.co.uk",
        contact_phone="+447700900123",
        accounting_platform=AccountingPlatform.CSV,
        discount_authorised=True,
        max_discount_percent=Decimal("3"),
    )
    db.create_sme(sme)
    print(f"Created SME: {sme.company_name} ({sme.id})")

    # Create test invoices with varying overdue periods
    test_invoices = [
        {
            "invoice_number": "INV-2025-001",
            "debtor_company": "BigCorp International",
            "amount": Decimal("7500.00"),
            "due_date": date.today() - timedelta(days=65),
            "contact_name": "Jane Smith",
            "contact_email": "jane.smith@bigcorp.example.com",
            "contact_role": "AP Manager",
        },
        {
            "invoice_number": "INV-2025-002",
            "debtor_company": "MegaTech Solutions",
            "amount": Decimal("3200.00"),
            "due_date": date.today() - timedelta(days=72),
            "contact_name": "Tom Brown",
            "contact_email": "tom.brown@megatech.example.com",
            "contact_role": "Finance Director",
        },
        {
            "invoice_number": "INV-2025-003",
            "debtor_company": "Global Services Ltd",
            "amount": Decimal("12000.00"),
            "due_date": date.today() - timedelta(days=90),
            "contact_name": "Sarah Johnson",
            "contact_email": "s.johnson@globalservices.example.com",
            "contact_role": "CFO",
        },
        {
            "invoice_number": "INV-2025-004",
            "debtor_company": "Enterprise Holdings",
            "amount": Decimal("4800.00"),
            "due_date": date.today() - timedelta(days=61),
            "contact_name": "Mike Davis",
            "contact_email": "m.davis@enterprise.example.com",
            "contact_role": "Accounts Payable",
        },
        {
            "invoice_number": "INV-2025-005",
            "debtor_company": "StartupCo",
            "amount": Decimal("1500.00"),
            "due_date": date.today() - timedelta(days=120),
            "contact_name": "Alex Turner",
            "contact_email": "alex@startupco.example.com",
            "contact_role": "CEO",
        },
        {
            "invoice_number": "INV-TEST-STEWART",
            "debtor_company": "Confusion & Joy",
            "amount": Decimal("6500.00"),
            "due_date": date.today() - timedelta(days=90),
            "contact_name": "Stewart Rogers",
            "contact_email": "stewart.rogers@gmail.com",
            "contact_role": "Director",
        },
    ]

    for inv_data in test_invoices:
        invoice = Invoice(
            sme_id=sme.id,
            invoice_number=inv_data["invoice_number"],
            debtor_company=inv_data["debtor_company"],
            amount=inv_data["amount"],
            due_date=inv_data["due_date"],
        )
        db.create_invoice(invoice)

        contact = Contact(
            invoice_id=invoice.id,
            name=inv_data["contact_name"],
            email=inv_data["contact_email"],
            role=inv_data["contact_role"],
            is_primary=True,
            source=ContactSource.CSV_UPLOAD,
        )
        db.create_contact(contact)

        days = (date.today() - inv_data["due_date"]).days
        print(f"  Invoice {inv_data['invoice_number']}: {inv_data['debtor_company']} — {days} days overdue")

    print(f"\nSeeded {len(test_invoices)} test invoices for {sme.company_name}")


if __name__ == "__main__":
    seed()
