"""Tests for the CSV importer parsing and validation."""

from src.sentry.csv_importer import parse_csv

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
