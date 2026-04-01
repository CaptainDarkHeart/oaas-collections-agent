"""Tests for the fee calculator."""

from decimal import Decimal
from uuid import uuid4

from src.billing.fee_calculator import calculate_fee
from src.db.models import FeeStatus, FeeType


class TestFeeCalculator:
    def test_large_invoice_percentage_fee(self):
        fee = calculate_fee(Decimal("7500.00"), str(uuid4()), str(uuid4()))
        assert fee.fee_type == FeeType.PERCENTAGE
        assert fee.fee_amount == Decimal("750.00")
        assert fee.status == FeeStatus.PENDING

    def test_small_invoice_flat_fee(self):
        fee = calculate_fee(Decimal("3000.00"), str(uuid4()), str(uuid4()))
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")

    def test_threshold_boundary_flat_fee(self):
        fee = calculate_fee(Decimal("5000.00"), str(uuid4()), str(uuid4()))
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")

    def test_just_above_threshold_percentage_fee(self):
        fee = calculate_fee(Decimal("5001.00"), str(uuid4()), str(uuid4()))
        assert fee.fee_type == FeeType.PERCENTAGE
        assert fee.fee_amount == Decimal("500.10")

    def test_large_invoice_percentage_calculation(self):
        fee = calculate_fee(Decimal("25000.00"), str(uuid4()), str(uuid4()))
        assert fee.fee_type == FeeType.PERCENTAGE
        assert fee.fee_amount == Decimal("2500.00")

    def test_invoice_amount_recorded(self):
        amount = Decimal("8000.00")
        fee = calculate_fee(amount, str(uuid4()), str(uuid4()))
        assert fee.invoice_amount_recovered == amount


class TestStalledInvoiceFees:
    def test_stalled_60_days_gets_flat_fee_regardless_of_amount(self):
        fee = calculate_fee(Decimal("10000.00"), str(uuid4()), str(uuid4()), days_overdue=60)
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")

    def test_stalled_90_days_gets_flat_fee_regardless_of_amount(self):
        fee = calculate_fee(Decimal("25000.00"), str(uuid4()), str(uuid4()), days_overdue=90)
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")

    def test_stalled_59_days_follows_normal_rules(self):
        fee = calculate_fee(Decimal("10000.00"), str(uuid4()), str(uuid4()), days_overdue=59)
        assert fee.fee_type == FeeType.PERCENTAGE
        assert fee.fee_amount == Decimal("1000.00")

    def test_stalled_0_days_follows_normal_rules(self):
        fee = calculate_fee(Decimal("3000.00"), str(uuid4()), str(uuid4()), days_overdue=0)
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")

    def test_stalled_60_days_small_invoice_also_flat(self):
        fee = calculate_fee(Decimal("3000.00"), str(uuid4()), str(uuid4()), days_overdue=60)
        assert fee.fee_type == FeeType.FLAT
        assert fee.fee_amount == Decimal("500")
