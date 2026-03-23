"""Tests for the hard-coded guardrails in constraints.py."""

from src.strategist.constraints import (
    PAUSE_CLASSIFICATIONS,
    PHASE_1_BANNED_WORDS,
    PHASE_DISCOUNT_LIMITS,
    PHASE_MAX_WORDS,
    DiscountOffer,
)


class TestDiscountOffer:
    def test_phase_1_no_discounts(self):
        offer = DiscountOffer(percentage=1.0, payment_window_hours=48, phase=1, sme_authorised=True)
        assert not offer.is_valid()

    def test_phase_1_zero_discount_ok(self):
        offer = DiscountOffer(
            percentage=0.0,
            payment_window_hours=48,
            phase=1,
            sme_authorised=False,
        )
        assert offer.is_valid()

    def test_phase_2_within_limit(self):
        offer = DiscountOffer(percentage=2.0, payment_window_hours=48, phase=2, sme_authorised=True)
        assert offer.is_valid()

    def test_phase_2_exceeds_limit(self):
        offer = DiscountOffer(percentage=2.5, payment_window_hours=48, phase=2, sme_authorised=True)
        assert not offer.is_valid()

    def test_phase_3_within_limit(self):
        offer = DiscountOffer(percentage=3.0, payment_window_hours=24, phase=3, sme_authorised=True)
        assert offer.is_valid()

    def test_phase_3_not_authorised(self):
        offer = DiscountOffer(
            percentage=2.0,
            payment_window_hours=24,
            phase=3,
            sme_authorised=False,
        )
        assert not offer.is_valid()

    def test_phase_4_no_discounts(self):
        offer = DiscountOffer(percentage=1.0, payment_window_hours=48, phase=4, sme_authorised=True)
        assert not offer.is_valid()


class TestConstraintConstants:
    def test_banned_words_include_key_terms(self):
        assert "overdue" in PHASE_1_BANNED_WORDS
        assert "debt" in PHASE_1_BANNED_WORDS
        assert "collections" in PHASE_1_BANNED_WORDS

    def test_pause_classifications(self):
        assert "DISPUTE" in PAUSE_CLASSIFICATIONS
        assert "HOSTILE" in PAUSE_CLASSIFICATIONS
        assert "STALL" not in PAUSE_CLASSIFICATIONS

    def test_phase_word_limits_decrease_toward_phase_4(self):
        assert PHASE_MAX_WORDS[1] > PHASE_MAX_WORDS[4]

    def test_all_phases_have_discount_limits(self):
        for phase in range(1, 5):
            assert phase in PHASE_DISCOUNT_LIMITS
