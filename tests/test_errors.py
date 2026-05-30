"""Tests for errors.py — pure response classification, no aiohttp."""

from __future__ import annotations

from conftest import load_module

errors = load_module("errors")


# --------------------------------------------------------------------------- #
# parse_retry_after
# --------------------------------------------------------------------------- #


def test_parse_retry_after_seconds():
    assert errors.parse_retry_after("30") == 30


def test_parse_retry_after_zero():
    assert errors.parse_retry_after("0") == 0


def test_parse_retry_after_none():
    assert errors.parse_retry_after(None) is None


def test_parse_retry_after_invalid_string():
    assert errors.parse_retry_after("later") is None


def test_parse_retry_after_negative_clamped_to_none():
    assert errors.parse_retry_after("-5") is None


def test_parse_retry_after_floating_point_truncated():
    assert errors.parse_retry_after("12.7") == 12


# --------------------------------------------------------------------------- #
# classify_response
# --------------------------------------------------------------------------- #


def test_classify_200_returns_none():
    assert errors.classify_response(200, None) is None


def test_classify_204_returns_none():
    assert errors.classify_response(204, None) is None


def test_classify_401_returns_auth_error():
    exc = errors.classify_response(401, None)
    assert isinstance(exc, errors.MieleMoveAuthError)


def test_classify_403_returns_auth_error():
    exc = errors.classify_response(403, None)
    assert isinstance(exc, errors.MieleMoveAuthError)


def test_classify_429_returns_rate_limit_error_with_retry_after():
    exc = errors.classify_response(429, "60")
    assert isinstance(exc, errors.MieleMoveRateLimitError)
    assert exc.retry_after == 60


def test_classify_429_without_retry_after_header():
    exc = errors.classify_response(429, None)
    assert isinstance(exc, errors.MieleMoveRateLimitError)
    assert exc.retry_after is None


def test_classify_500_returns_generic_api_error():
    exc = errors.classify_response(500, None)
    assert isinstance(exc, errors.MieleMoveApiError)
    assert not isinstance(exc, errors.MieleMoveAuthError)
    assert not isinstance(exc, errors.MieleMoveRateLimitError)


def test_classify_404_returns_generic_api_error():
    exc = errors.classify_response(404, None)
    assert isinstance(exc, errors.MieleMoveApiError)


def test_rate_limit_error_is_api_error_subclass():
    assert issubclass(errors.MieleMoveRateLimitError, errors.MieleMoveApiError)


def test_auth_error_is_api_error_subclass():
    assert issubclass(errors.MieleMoveAuthError, errors.MieleMoveApiError)
