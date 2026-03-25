"""Tests for the CSV importer parsing and validation."""

from unittest.mock import MagicMock
from uuid import uuid4

from src.sentry.csv_importer import import_csv, parse_csv

VALID_CSV = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,+447700900123,INV-001,7500.00,2025-12-01
MegaTech,Tom Brown,tom@megatech.com,,INV-002,3200,2025-11-15
"""

MISSING_COLUMNS_CSV = """company,name,email
BigCorp,Jane,jane@bigcorp.com
"""

INVALID_ROWS_CSV = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,not_a_number,2025-12-01
BigCorp,Jane Smith,invalid-email,,INV-002,5000,2025-12-01
BigCorp,Jane Smith,jane@bigcorp.com,,INV-003,5000,not-a-date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-004,-100,2025-12-01
"""

FUTURE_DATE_CSV = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,5000,2099-12-01
"""


class TestParseCSV:
    def test_valid_csv(self):
        rows, errors = parse_csv(VALID_CSV)
        assert len(rows) == 2
        assert len(errors) == 0
        assert rows[0]["debtor_company"] == "BigCorp"
        assert rows[0]["invoice_number"] == "INV-001"

    def test_missing_required_columns(self):
        rows, errors = parse_csv(MISSING_COLUMNS_CSV)
        assert len(rows) == 0
        assert len(errors) == 1
        assert "Missing required columns" in errors[0].message

    def test_invalid_amount(self):
        rows, errors = parse_csv(INVALID_ROWS_CSV)
        # Each invalid row should produce at least one error
        assert len(errors) >= 3

    def test_future_due_date(self):
        rows, errors = parse_csv(FUTURE_DATE_CSV)
        assert len(rows) == 0
        assert any("future" in e.message.lower() for e in errors)

    def test_empty_csv(self):
        rows, errors = parse_csv("")
        assert len(rows) == 0
        assert len(errors) == 1

    def test_bytes_input(self):
        rows, errors = parse_csv(VALID_CSV.encode("utf-8"))
        assert len(rows) == 2

    def test_bom_handling(self):
        bom_csv = "\ufeff" + VALID_CSV
        rows, errors = parse_csv(bom_csv)
        assert len(rows) == 2

    def test_commas_in_amount(self):
        csv_data = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,"7,500.00",2025-12-01
"""
        rows, errors = parse_csv(csv_data)
        assert len(rows) == 1
        assert rows[0]["amount"] == "7,500.00"

    def test_whitespace_handling(self):
        csv_data = """debtor_company , contact_name , contact_email , contact_phone , invoice_number , amount , due_date
  BigCorp  , Jane Smith , jane@bigcorp.com ,, INV-001 , 7500 , 2025-12-01
"""
        rows, errors = parse_csv(csv_data)
        assert len(rows) == 1
        assert rows[0]["debtor_company"] == "BigCorp"


class TestImportCSVDuplicateDetection:
    """Tests for CSV import duplicate detection against existing DB records."""

    def test_existing_invoice_in_db_is_skipped(self):
        """An invoice that already exists in the DB should be skipped on re-upload."""
        sme_id = uuid4()

        csv_data = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,7500.00,2025-12-01
MegaTech,Tom Brown,tom@megatech.com,,INV-002,3200,2025-11-15
"""

        mock_db = MagicMock()
        # INV-001 already exists in the DB
        mock_db.list_all_invoices.return_value = [
            {"invoice_number": "INV-001", "id": str(uuid4()), "sme_id": str(sme_id)},
        ]
        mock_db.create_invoice.return_value = {"id": str(uuid4())}
        mock_db.create_contact.return_value = {"id": str(uuid4())}

        result = import_csv(csv_data, sme_id, mock_db)

        # INV-001 should be skipped, INV-002 should be created
        assert result.invoices_created == 1
        assert result.skipped == 1
        # Only one invoice and one contact created
        assert mock_db.create_invoice.call_count == 1
        assert mock_db.create_contact.call_count == 1

    def test_no_existing_invoices_all_created(self):
        """When no invoices exist in DB, all CSV rows are imported."""
        sme_id = uuid4()

        csv_data = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,7500.00,2025-12-01
MegaTech,Tom Brown,tom@megatech.com,,INV-002,3200,2025-11-15
"""

        mock_db = MagicMock()
        mock_db.list_all_invoices.return_value = []
        mock_db.create_invoice.return_value = {"id": str(uuid4())}
        mock_db.create_contact.return_value = {"id": str(uuid4())}

        result = import_csv(csv_data, sme_id, mock_db)

        assert result.invoices_created == 2
        assert result.skipped == 0

    def test_within_batch_dedup_still_works(self):
        """Duplicate invoice numbers within the same CSV are still caught."""
        sme_id = uuid4()

        csv_data = """debtor_company,contact_name,contact_email,contact_phone,invoice_number,amount,due_date
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,7500.00,2025-12-01
BigCorp,Jane Smith,jane@bigcorp.com,,INV-001,7500.00,2025-12-01
"""

        mock_db = MagicMock()
        mock_db.list_all_invoices.return_value = []
        mock_db.create_invoice.return_value = {"id": str(uuid4())}
        mock_db.create_contact.return_value = {"id": str(uuid4())}

        result = import_csv(csv_data, sme_id, mock_db)

        assert result.invoices_created == 1
        assert result.skipped == 1
