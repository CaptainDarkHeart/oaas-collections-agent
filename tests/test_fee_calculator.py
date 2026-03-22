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
