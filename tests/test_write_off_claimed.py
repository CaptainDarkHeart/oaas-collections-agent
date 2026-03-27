"""Tests for the write-off claimed flow.

Covers:
- Classifier recognises write-off claims
- State machine pauses and saves pre-claim phase
- Alerts sent to SME (Slack + email)
- Dashboard: confirm write-off marks invoice as written_off
- Dashboard: deny write-off resumes at Phase 3 minimum
- Resume floors at Phase 3 regardless of where we were
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from src.dashboard.app import app
from src.db.models import Classification, InvoicePhase, InvoiceStatus

client = TestClient(app, headers={"Authorization": "Basic dXNlcjp0ZXN0"})


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestWriteOffClaimedStateMachine:
    def test_write_off_claimed_pauses_and_saves_phase(self):
        from src.strategist.state_machine import handle_classification

        db = MagicMock()
        invoice_id = uuid4()

        result = handle_classification(
            Classification.WRITE_OFF_CLAIMED,
            InvoicePhase.PHASE_2,
            invoice_id,
            db,
        )

        assert result.action == "pause"
        assert result.new_phase == InvoicePhase.WRITE_OFF_CLAIMED
        assert result.new_status == InvoiceStatus.PAUSED

        update = db.update_invoice.call_args[0][1]
        assert update["current_phase"] == InvoicePhase.WRITE_OFF_CLAIMED.value
        assert update["status"] == InvoiceStatus.PAUSED.value
        assert update["pre_write_off_phase"] == InvoicePhase.PHASE_2.value
        assert update["write_off_claimed_at"] is not None

    def test_write_off_claimed_in_phase_3_saves_phase_3(self):
        from src.strategist.state_machine import handle_classification

        db = MagicMock()
        invoice_id = uuid4()

        result = handle_classification(
            Classification.WRITE_OFF_CLAIMED,
            InvoicePhase.PHASE_3,
            invoice_id,
            db,
        )

        update = db.update_invoice.call_args[0][1]
        assert update["pre_write_off_phase"] == InvoicePhase.PHASE_3.value


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestWriteOffClaimedNotifications:
    def test_write_off_claimed_triggers_alerts(self):
        """process_inbound_reply with WRITE_OFF_CLAIMED should alert Slack + SME."""
        from src.main import process_inbound_reply

        invoice_id = uuid4()
        contact_id = uuid4()
        sme_id = uuid4()

        db = MagicMock()
        db.get_invoice.return_value = {
            "id": str(invoice_id),
            "sme_id": str(sme_id),
            "invoice_number": "INV-WO",
            "debtor_company": "Dodgy Co",
            "current_phase": "2",
            "status": "active",
        }
        db.get_sme.return_value = {
            "id": str(sme_id),
            "company_name": "Test SME",
            "contact_email": "owner@sme.com",
        }

        with patch("src.main.classify_response") as mock_classify, \
             patch("src.main.handle_classification") as mock_handle, \
             patch("src.main.slack_webhook") as mock_slack, \
             patch("src.main.email_alerts") as mock_email:

            mock_classify.return_value = (
                Classification.WRITE_OFF_CLAIMED,
                "Debtor claims invoice was written off",
            )
            mock_handle.return_value = MagicMock(
                action="pause",
                new_phase=InvoicePhase.WRITE_OFF_CLAIMED,
                new_status=InvoiceStatus.PAUSED,
                message="WRITE-OFF CLAIMED",
            )

            process_inbound_reply(
                db=db,
                email_client=MagicMock(),
                invoice_id=invoice_id,
                contact_id=contact_id,
                reply_text="We were told this invoice had been written off last year.",
            )

            mock_slack.notify_write_off_claimed.assert_called_once()
            call_args = mock_slack.notify_write_off_claimed.call_args[0]
            assert call_args[0] == "INV-WO"
            assert call_args[1] == "Dodgy Co"

            mock_email.alert_write_off_claimed.assert_called_once()
            # alert is called with keyword args; check via call_args
            call = mock_email.alert_write_off_claimed.call_args
            all_args = {**call[1]} if call[1] else {}
            # keyword args include invoice_number and debtor_company
            assert all_args.get("invoice_number") == "INV-WO" or "INV-WO" in str(call)


# ---------------------------------------------------------------------------
# Dashboard actions
# ---------------------------------------------------------------------------


def _full_invoice(phase="write_off_claimed", pre_phase="2", sme_id=None):
    """Return a full invoice dict accepted by the dashboard."""
    from datetime import date, timedelta
    return {
        "id": str(uuid4()),
        "sme_id": str(sme_id or uuid4()),
        "invoice_number": "INV-WO",
        "debtor_company": "Dodgy Co",
        "amount": "10000.00",
        "currency": "GBP",
        "due_date": (date.today() - timedelta(days=30)).isoformat(),
        "current_phase": phase,
        "status": "paused",
        "created_at": "2026-01-01T00:00:00",
        "resolved_at": None,
        "fee_charged": False,
        "fee_amount": None,
        "payment_link_url": None,
        "first_contacted_at": "2026-03-01T10:00:00",
        "write_off_claimed_at": "2026-03-20T10:00:00",
        "pre_write_off_phase": pre_phase,
    }


class TestConfirmWriteOff:
    @patch("src.dashboard.app._db")
    def test_confirm_write_off_marks_written_off(self, mock_db_fn):
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = _full_invoice()
        db.get_sme.return_value = {"id": str(uuid4()), "company_name": "SME"}

        invoice_id = str(uuid4())
        resp = client.post(f"/invoices/{invoice_id}/confirm-write-off")

        assert resp.status_code in (200, 303)
        update = db.update_invoice.call_args[0][1]
        assert update["status"] == InvoiceStatus.WRITTEN_OFF.value
        assert update["current_phase"] == InvoicePhase.RESOLVED.value
        assert update["resolved_at"] is not None

    @patch("src.dashboard.app._db")
    def test_confirm_write_off_invoice_not_found_does_not_crash(self, mock_db_fn):
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = None

        invoice_id = str(uuid4())
        resp = client.post(f"/invoices/{invoice_id}/confirm-write-off")
        # Dashboard returns 404 when invoice not found — that's correct behaviour
        assert resp.status_code in (200, 303, 404)
        db.update_invoice.assert_not_called()


class TestDenyWriteOff:
    @patch("src.dashboard.app._db")
    def test_deny_resumes_at_phase_3_when_was_phase_1(self, mock_db_fn):
        """If debtor lied and we were in Phase 1, we should resume at Phase 3."""
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = _full_invoice(pre_phase="1")

        invoice_id = str(uuid4())
        resp = client.post(f"/invoices/{invoice_id}/deny-write-off")

        assert resp.status_code in (200, 303)
        update = db.update_invoice.call_args[0][1]
        assert update["status"] == InvoiceStatus.ACTIVE.value
        assert update["current_phase"] == "3"  # floored at Phase 3
        assert update["write_off_claimed_at"] is None

    @patch("src.dashboard.app._db")
    def test_deny_resumes_at_phase_4_when_was_phase_4(self, mock_db_fn):
        """If we were already in Phase 4, stay in Phase 4."""
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = _full_invoice(pre_phase="4")

        invoice_id = str(uuid4())
        resp = client.post(f"/invoices/{invoice_id}/deny-write-off")

        update = db.update_invoice.call_args[0][1]
        assert update["current_phase"] == "4"

    @patch("src.dashboard.app._db")
    def test_deny_resumes_at_phase_3_when_no_pre_phase(self, mock_db_fn):
        """If pre_write_off_phase is missing, default to Phase 3."""
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = _full_invoice(pre_phase=None)

        invoice_id = str(uuid4())
        resp = client.post(f"/invoices/{invoice_id}/deny-write-off")

        update = db.update_invoice.call_args[0][1]
        assert update["current_phase"] == InvoicePhase.PHASE_3.value

    @patch("src.dashboard.app._db")
    def test_deny_clears_write_off_fields(self, mock_db_fn):
        """Deny should clear write_off_claimed_at and pre_write_off_phase."""
        db = MagicMock()
        mock_db_fn.return_value = db
        db.get_invoice.return_value = _full_invoice(pre_phase="3")

        invoice_id = str(uuid4())
        client.post(f"/invoices/{invoice_id}/deny-write-off")

        update = db.update_invoice.call_args[0][1]
        assert update["write_off_claimed_at"] is None
        assert update["pre_write_off_phase"] is None


# ---------------------------------------------------------------------------
# Classifier prompt includes write_off_claimed
# ---------------------------------------------------------------------------


class TestClassifierPrompt:
    def test_prompt_includes_write_off_claimed_category(self):
        from pathlib import Path

        prompt = (
            Path(__file__).parent.parent
            / "src/strategist/prompts/classifier.txt"
        ).read_text()

        assert "WRITE_OFF_CLAIMED" in prompt
        assert "written off" in prompt.lower()

    def test_write_off_claimed_in_valid_classifications(self):
        from src.strategist.response_classifier import VALID_CLASSIFICATIONS

        assert "WRITE_OFF_CLAIMED" in VALID_CLASSIFICATIONS
