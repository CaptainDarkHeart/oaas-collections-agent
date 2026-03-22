"""Hard-coded guardrails for the Strategist brain.

These constraints are enforced in code, not just in prompts,
to prevent hallucination of unauthorised offers or language.
"""

from dataclasses import dataclass

# Words the agent must never use in Phase 1
PHASE_1_BANNED_WORDS = frozenset({
    "overdue", "late", "debt", "owed", "collections",
    "legal", "lawyer", "court", "solicitor",
})

# The strongest language permitted at any phase
MAX_ESCALATION_LANGUAGE = "external compliance partner"

# Discount limits by phase
PHASE_DISCOUNT_LIMITS: dict[int, float] = {
    1: 0.0,   # No discounts in Phase 1
    2: 2.0,   # Max 2% for payment within 48h
    3: 3.0,   # Max 3% for payment within 24h (requires pre-auth)
    4: 0.0,   # No discounts in Phase 4
}

# Maximum email word counts by phase
PHASE_MAX_WORDS: dict[int, int] = {
    1: 120,
    2: 100,
    3: 110,
    4: 80,
}

# Classifications that require immediate agent pause
PAUSE_CLASSIFICATIONS = frozenset({"DISPUTE", "HOSTILE"})

# Maximum voice message duration in seconds
MAX_VOICE_MESSAGE_SECONDS = 30


@dataclass(frozen=True)
class DiscountOffer:
    """Validated discount offer that has passed all guardrails."""

    percentage: float
    payment_window_hours: int
    phase: int
    sme_authorised: bool

    def is_valid(self) -> bool:
        phase_limit = PHASE_DISCOUNT_LIMITS.get(self.phase, 0.0)
        if self.percentage > phase_limit:
            return False
        if self.percentage > 0 and not self.sme_authorised:
            return False
        return True
