"""Tests for the variable cadence engine."""

from datetime import UTC, date, datetime, timedelta

from src.db.models import InvoicePhase
from src.executor.cadence import (
    BUSINESS_END,
    BUSINESS_START,
    MAX_EMAILS_PER_INBOX_PER_DAY,
    _next_business_day,
    _random_business_time,
    can_contact_today,
    is_within_daily_limit,
    schedule_next_send,
    schedule_phase_escalation,
)


class TestRandomBusinessTime:
    def test_within_business_hours(self):
        for _ in range(100):
            t = _random_business_time()
            assert t >= BUSINESS_START
            assert t <= BUSINESS_END


class TestNextBusinessDay:
    def test_weekday_unchanged(self):
        # Monday
        monday = date(2026, 3, 23)
        assert _next_business_day(monday) == monday

    def test_saturday_moves_to_monday(self):
        saturday = date(2026, 3, 28)
        result = _next_business_day(saturday)
        assert result.weekday() == 0  # Monday
        assert result == date(2026, 3, 30)

    def test_sunday_moves_to_monday(self):
        sunday = date(2026, 3, 29)
        result = _next_business_day(sunday)
        assert result.weekday() == 0
        assert result == date(2026, 3, 30)


class TestScheduleNextSend:
    def test_first_send_returns_today_or_later(self):
        result = schedule_next_send(
            phase=InvoicePhase.PHASE_1,
            phase_start_date=date.today(),
            interactions_in_phase=0,
        )
        assert result is not None
        assert result.date() >= date.today()

    def test_exhausted_followups_returns_none(self):
        result = schedule_next_send(
            phase=InvoicePhase.PHASE_1,
            phase_start_date=date.today() - timedelta(days=10),
            interactions_in_phase=3,
        )
        assert result is None

    def test_respects_min_contact_gap(self):
        recent = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=2)
        result = schedule_next_send(
            phase=InvoicePhase.PHASE_1,
            phase_start_date=date.today(),
            interactions_in_phase=0,
            last_contact_at=recent,
        )
        assert result is not None
        # Should be pushed to at least 24h after last contact
        assert result > recent + timedelta(hours=23)


class TestSchedulePhaseEscalation:
    def test_phase_1_escalation_date(self):
        start = date(2026, 3, 23)  # Monday
        result = schedule_phase_escalation(InvoicePhase.PHASE_1, start)
        assert result is not None
        # 5 days from Monday = Saturday → pushed to Monday March 30
        assert result == date(2026, 3, 30)

    def test_accelerated_shortens_duration(self):
        start = date(2026, 3, 23)
        normal = schedule_phase_escalation(InvoicePhase.PHASE_1, start, accelerated=False)
        fast = schedule_phase_escalation(InvoicePhase.PHASE_1, start, accelerated=True)
        assert fast < normal

    def test_human_review_returns_none(self):
        assert schedule_phase_escalation(InvoicePhase.HUMAN_REVIEW, date.today()) is None


class TestDailyLimits:
    def test_under_limit(self):
        assert is_within_daily_limit(0) is True
        assert is_within_daily_limit(29) is True

    def test_at_limit(self):
        assert is_within_daily_limit(MAX_EMAILS_PER_INBOX_PER_DAY) is False


class TestCanContactToday:
    def test_never_contacted(self):
        assert can_contact_today(None) is True

    def test_contacted_recently(self):
        recent = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=2)
        assert can_contact_today(recent) is False

    def test_contacted_long_ago(self):
        old = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=25)
        assert can_contact_today(old) is True
