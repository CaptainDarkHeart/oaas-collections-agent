"""Phase progression state machine for invoice collection lifecycle.

Manages the 4-phase escalation sequence and handles response-driven transitions
per the action matrix defined in the spec.

Phase timeline:
    Phase 1 (Days 1-5):  Email only, friendly check-in
    Phase 2 (Days 7-10): Email + voice, internal advocate
    Phase 3 (Days 14-17): Email + voice, loss aversion
    Phase 4 (Day 21+):   Formal email + LinkedIn

Transitions triggered by:
    - Time elapsed with NO_RESPONSE → escalate to next phase
    - Classification of inbound replies → action per matrix
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.db.models import (
    Classification,
    Database,
    InvoicePhase,
    InvoiceStatus,
)

# Phase cadence: maps phase to (days into sequence, phase duration in days)
PHASE_SCHEDULE = {
    InvoicePhase.PHASE_1: {"start_day": 1, "duration": 5},
    InvoicePhase.PHASE_2: {"start_day": 7, "duration": 4},
    InvoicePhase.PHASE_3: {"start_day": 14, "duration": 4},
    InvoicePhase.PHASE_4: {"start_day": 21, "duration": 7},
}

# Follow-up schedule within each phase (days after phase start)
PHASE_FOLLOWUPS = {
    InvoicePhase.PHASE_1: [0, 2, 4],  # Day 1, 3, 5
    InvoicePhase.PHASE_2: [0, 3],  # Day 7, 10
    InvoicePhase.PHASE_3: [0, 3],  # Day 14, 17
    InvoicePhase.PHASE_4: [0, 2],  # Day 21, 23
}


@dataclass
class TransitionResult:
    """Result of processing a state transition."""

    action: str  # send_message, pause, escalate_phase, redirect, monitor, human_review
    new_phase: InvoicePhase | None = None
    new_status: InvoiceStatus | None = None
    message: str = ""
    accelerated: bool = False  # True if cadence is accelerated due to STALL


def handle_classification(
    classification: Classification,
    current_phase: InvoicePhase,
    invoice_id: UUID,
    db: Database,
) -> TransitionResult:
    """Process an inbound reply classification and determine the next action.

    Implements the action matrix from the spec.
    """
    if classification == Classification.PROMISE_TO_PAY:
        db.update_invoice(
            invoice_id,
            {
                "status": InvoiceStatus.ACTIVE.value,
            },
        )
        return TransitionResult(
            action="monitor",
            message="Send thank-you + calendar reminder for promised date. "
            "Re-engage with Phase 2 tone if payment not received by date + 3 days.",
        )

    if classification == Classification.PAYMENT_PENDING:
        return TransitionResult(
            action="send_message",
            message="Request check/transfer reference number for social accountability. "
            "Follow up in 3 business days.",
        )

    if classification == Classification.DISPUTE:
        db.update_invoice(
            invoice_id,
            {
                "current_phase": InvoicePhase.DISPUTED.value,
                "status": InvoiceStatus.DISPUTED.value,
            },
        )
        return TransitionResult(
            action="pause",
            new_phase=InvoicePhase.DISPUTED,
            new_status=InvoiceStatus.DISPUTED,
            message="DISPUTED — agent paused. Human intervention required.",
        )

    if classification == Classification.REDIRECT:
        return TransitionResult(
            action="redirect",
            new_phase=InvoicePhase.PHASE_1,
            message="Add new contact to sequence at Phase 1.",
        )

    if classification == Classification.STALL:
        return TransitionResult(
            action="send_message",
            accelerated=True,
            message="Acknowledge stall, continue current phase on accelerated timeline (-2 days).",
        )

    if classification == Classification.HOSTILE:
        db.update_invoice(
            invoice_id,
            {
                "current_phase": InvoicePhase.HUMAN_REVIEW.value,
                "status": InvoiceStatus.PAUSED.value,
            },
        )
        return TransitionResult(
            action="pause",
            new_phase=InvoicePhase.HUMAN_REVIEW,
            new_status=InvoiceStatus.PAUSED,
            message="HOSTILE — agent paused. Do NOT respond. Human review required.",
        )

    if classification == Classification.NO_RESPONSE:
        return _escalate_phase(current_phase, invoice_id, db)

    return TransitionResult(action="monitor", message="Unknown classification — monitoring.")


def _escalate_phase(
    current_phase: InvoicePhase,
    invoice_id: UUID,
    db: Database,
) -> TransitionResult:
    """Move to the next phase on NO_RESPONSE."""
    phase_order = [
        InvoicePhase.PHASE_1,
        InvoicePhase.PHASE_2,
        InvoicePhase.PHASE_3,
        InvoicePhase.PHASE_4,
    ]

    if current_phase not in phase_order:
        return TransitionResult(action="monitor", message="Invoice not in active phase sequence.")

    idx = phase_order.index(current_phase)

    if idx >= len(phase_order) - 1:
        # End of Phase 4 — flag for human review
        db.update_invoice(
            invoice_id,
            {
                "current_phase": InvoicePhase.HUMAN_REVIEW.value,
                "status": InvoiceStatus.PAUSED.value,
            },
        )
        return TransitionResult(
            action="human_review",
            new_phase=InvoicePhase.HUMAN_REVIEW,
            new_status=InvoiceStatus.PAUSED,
            message="Phase 4 exhausted with no response. Flagged for human review.",
        )

    next_phase = phase_order[idx + 1]
    db.update_invoice(invoice_id, {"current_phase": next_phase.value})

    return TransitionResult(
        action="escalate_phase",
        new_phase=next_phase,
        message=f"No response — escalating from {current_phase.value} to Phase {next_phase.value}.",
    )


def should_escalate(
    current_phase: InvoicePhase,
    last_outbound_at: datetime | None,
    accelerated: bool = False,
) -> bool:
    """Check if enough time has passed to escalate to the next phase.

    Args:
        current_phase: The invoice's current phase.
        last_outbound_at: Timestamp of the last outbound message.
        accelerated: If True, reduce the phase duration by 2 days (STALL response).
    """
    if current_phase not in PHASE_SCHEDULE:
        return False

    if last_outbound_at is None:
        return True  # Never contacted — start immediately

    schedule = PHASE_SCHEDULE[current_phase]
    duration = schedule["duration"]
    if accelerated:
        duration = max(1, duration - 2)

    elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_outbound_at).days
    return elapsed >= duration


def get_next_followup_day(
    current_phase: InvoicePhase,
    interactions_in_phase: int,
) -> int | None:
    """Get the next follow-up day offset within the current phase.

    Returns None if all follow-ups for this phase have been sent.
    """
    followups = PHASE_FOLLOWUPS.get(current_phase, [])
    if interactions_in_phase >= len(followups):
        return None
    return followups[interactions_in_phase]
