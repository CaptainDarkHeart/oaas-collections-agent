"""Tests for retry/backoff utilities."""

from __future__ import annotations

from unittest.mock import patch

import requests

from src.utils.retry import resilient_session, with_retry


class TestResilientSession:
    """Tests for the resilient_session factory."""

    def test_returns_requests_session(self):
        session = resilient_session()
        assert isinstance(session, requests.Session)

    def test_http_adapter_mounted(self):
        session = resilient_session(retries=5, backoff_factor=0.5)
        # Both http and https should have adapters with retry config
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")
        assert http_adapter.max_retries.total == 5
        assert http_adapter.max_retries.backoff_factor == 0.5
        assert https_adapter.max_retries.total == 5

    def test_status_forcelist_configured(self):
        session = resilient_session(status_forcelist=(429, 503))
        adapter = session.get_adapter("https://example.com")
        assert 429 in adapter.max_retries.status_forcelist
        assert 503 in adapter.max_retries.status_forcelist
        assert 500 not in adapter.max_retries.status_forcelist

    def test_default_parameters(self):
        session = resilient_session()
        adapter = session.get_adapter("https://example.com")
        assert adapter.max_retries.total == 3
        assert adapter.max_retries.backoff_factor == 1.0
        assert set(adapter.max_retries.status_forcelist) == {429, 500, 502, 503, 504}


class TestWithRetry:
    """Tests for the @with_retry decorator."""

    def test_succeeds_on_first_attempt(self):
        call_count = 0

        @with_retry(max_attempts=3, backoff_factor=0.0)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count == 1

    @patch("src.utils.retry.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        call_count = 0

        @with_retry(max_attempts=3, backoff_factor=0.01, retryable_exceptions=(ValueError,))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "recovered"

        result = flaky()
        assert result == "recovered"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("src.utils.retry.time.sleep")
    def test_raises_after_max_attempts(self, mock_sleep):
        call_count = 0

        @with_retry(max_attempts=2, backoff_factor=0.01, retryable_exceptions=(RuntimeError,))
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("permanent")

        try:
            always_fails()
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "permanent" in str(e)

        assert call_count == 2

    def test_non_retryable_exception_raises_immediately(self):
        call_count = 0

        @with_retry(max_attempts=3, backoff_factor=0.0, retryable_exceptions=(ValueError,))
        def wrong_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        try:
            wrong_error()
            assert False, "Should have raised"
        except TypeError:
            pass

        assert call_count == 1

    @patch("src.utils.retry.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        call_count = 0

        @with_retry(max_attempts=4, backoff_factor=1.0, retryable_exceptions=(ValueError,))
        def fail_three_times():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise ValueError("fail")
            return "ok"

        fail_three_times()
        # Backoff: 1.0 * 2^0 = 1.0, 1.0 * 2^1 = 2.0, 1.0 * 2^2 = 4.0
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0, 4.0]
