"""Variable timing engine to avoid bot-like contact patterns.

Key rules from the spec:
- Never ping every 24 hours
- Randomise send times within business-hours windows (9:00-17:30)
- Never contact the same person twice in one day
- Example rhythm: 9:15 AM Tuesday, then 4:45 PM Thursday
- Max 30 cold emails per day per inbox
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from src.db.models import InvoicePhase
from src.strategist.state_machine import PHASE_FOLLOWUPS, PHASE_SCHEDULE

# Business hours window (UK time)
BUSINESS_START = time(9, 0)
BUSINESS_END = time(17, 30)

# Maximum emails per inbox per day (Instantly best practice)
MAX_EMAILS_PER_INBOX_PER_DAY = 30

# Minimum gap between contacts to the same person (hours)
MIN_CONTACT_GAP_HOURS = 24


def schedule_next_send(
    phase: InvoicePhase,
    phase_start_date: date,
    interactions_in_phase: int,
    last_contact_at: datetime | None = None,
) -> datetime | None:
    """Calculate the next send time for an invoice.

    Returns None if all follow-ups for this phase have been exhausted.

    Args:
        phase: Current invoice phase.
        phase_start_date: Date the current phase started.
        interactions_in_phase: Number of outbound messages already sent in this phase.
        last_contact_at: Timestamp of the last outbound to this contact.
    """
    followups = PHASE_FOLLOWUPS.get(phase)
    if not followups or interactions_in_phase >= len(followups):
        return None  # All follow-ups sent for this phase

    day_offset = followups[interactions_in_phase]
    target_date = phase_start_date + timedelta(days=day_offset)

    # If target date is in the past, schedule for today or tomorrow
    today = date.today()
    if target_date < today:
        target_date = today

    # Skip weekends
    target_date = _next_business_day(target_date)

    # Generate a random time within business hours
    send_time = _random_business_time()
    scheduled = datetime.combine(target_date, send_time)

    # Enforce minimum gap from last contact
    if last_contact_at:
        min_next = last_contact_at + timedelta(hours=MIN_CONTACT_GAP_HOURS)
        if scheduled < min_next:
            # Push to the next business day
            next_day = _next_business_day(target_date + timedelta(days=1))
            scheduled = datetime.combine(next_day, _random_business_time())

    return scheduled


def schedule_phase_escalation(
    current_phase: InvoicePhase,
    phase_start_date: date,
    accelerated: bool = False,
) -> date | None:
    """Calculate when to escalate to the next phase if no response.

    Returns None if the phase has no scheduled escalation (e.g., Phase 4 ends in human review).
    """
    schedule = PHASE_SCHEDULE.get(current_phase)
    if not schedule:
        return None

    duration = schedule["duration"]
    if accelerated:
        duration = max(1, duration - 2)

    escalation_date = phase_start_date + timedelta(days=duration)
    return _next_business_day(escalation_date)


def _next_business_day(d: date) -> date:
    """Advance to the next weekday if d falls on a weekend."""
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d += timedelta(days=1)
    return d


def _random_business_time() -> time:
    """Generate a random time within business hours.

    Avoids round numbers (e.g., 9:00, 10:00) to appear more human.
    Clusters around mid-morning (10-11) and mid-afternoon (14-16)
    as these are peak email-reading times.
    """
    # Weighted distribution: favour mid-morning and mid-afternoon
    # 30% chance: 9:15-10:30  (early morning)
    # 35% chance: 10:30-12:00 (mid-morning peak)
    # 10% chance: 12:00-14:00 (lunch — lower weight)
    # 25% chance: 14:00-17:00 (afternoon peak)
    roll = random.random()

    if roll < 0.30:
        hour = random.randint(9, 10)
        minute_range = (15, 59) if hour == 9 else (0, 30)
    elif roll < 0.65:
        hour = random.randint(10, 11)
        minute_range = (30, 59) if hour == 10 else (0, 59)
    elif roll < 0.75:
        hour = random.randint(12, 13)
        minute_range = (0, 59)
    else:
        hour = random.randint(14, 16)
        minute_range = (0, 59) if hour < 16 else (0, 30)

    minute = random.randint(*minute_range)
    return time(hour, minute)


def is_within_daily_limit(emails_sent_today: int) -> bool:
    """Check if we're within the daily send limit per inbox."""
    return emails_sent_today < MAX_EMAILS_PER_INBOX_PER_DAY


def can_contact_today(last_contact_at: datetime | None) -> bool:
    """Check if enough time has passed since the last contact."""
    if last_contact_at is None:
        return True
    gap = datetime.utcnow() - last_contact_at
    return gap >= timedelta(hours=MIN_CONTACT_GAP_HOURS)
