import pytest

from app.security import (
    LoginRateLimiter,
    csrf_ok,
    hash_password,
    normalize_openalex_id,
    parse_scholar_id,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    stored = hash_password("kata sandi panjang")
    assert stored.startswith("scrypt$")
    assert verify_password("kata sandi panjang", stored)
    assert not verify_password("kata sandi lain", stored)


def test_password_hash_rejects_malformed_value() -> None:
    assert not verify_password("apa saja", "bukan-hash")
    assert not verify_password("apa saja", "")


def test_scholar_id_from_url_and_raw() -> None:
    url = "https://scholar.google.com/citations?hl=en&user=AbC123xyz_9"
    assert parse_scholar_id(url) == "AbC123xyz_9"
    assert parse_scholar_id("AbC123xyz_9") == "AbC123xyz_9"
    assert parse_scholar_id("") is None
    with pytest.raises(ValueError):
        parse_scholar_id("https://scholar.google.com/citations?hl=en")


def test_scholar_id_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        parse_scholar_id("https://scholar.google.com/citations?user=abc")


def test_openalex_id_normalization() -> None:
    assert normalize_openalex_id("A5056916903") == "A5056916903"
    assert normalize_openalex_id("https://openalex.org/A5056916903") == "A5056916903"
    with pytest.raises(ValueError):
        normalize_openalex_id("W123")


def test_csrf_comparison() -> None:
    assert csrf_ok("abc", "abc")
    assert not csrf_ok("abc", "abd")
    assert not csrf_ok(None, "abc")
    assert not csrf_ok("abc", None)


def test_rate_limiter_blocks_after_five_failures() -> None:
    now = [1000.0]
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=900, clock=lambda: now[0])
    for _ in range(5):
        assert limiter.allowed("1.2.3.4")
        limiter.record_failure("1.2.3.4")
    assert not limiter.allowed("1.2.3.4")
    assert limiter.allowed("5.6.7.8")

    now[0] += 901
    assert limiter.allowed("1.2.3.4")


def test_rate_limiter_reset() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)
    limiter.record_failure("ip")
    assert not limiter.allowed("ip")
    limiter.reset("ip")
    assert limiter.allowed("ip")
