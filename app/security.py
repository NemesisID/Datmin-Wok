"""Kata sandi, ID eksternal, CSRF, dan pembatas percobaan login."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

OPENALEX_ID_RE = re.compile(r"^A\d+$")
SCHOLAR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Kata sandi tidak boleh kosong.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def parse_scholar_id(value: str) -> str | None:
    """Terima URL profil Scholar atau ID mentah. Kosong berarti tidak ada."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("http"):
        query = parse_qs(urlparse(raw).query)
        candidates = query.get("user") or []
        candidate = candidates[0].strip() if candidates else ""
    else:
        candidate = raw.removeprefix("user=").strip()
    if not SCHOLAR_ID_RE.fullmatch(candidate):
        raise ValueError(
            "ID Scholar harus 6 sampai 32 karakter huruf, angka, minus, atau garis bawah."
        )
    return candidate


def normalize_openalex_id(value: str) -> str:
    raw = (value or "").strip()
    raw = raw.removeprefix("https://openalex.org/").removeprefix("http://openalex.org/")
    raw = raw.removeprefix("openalex:").strip()
    if not OPENALEX_ID_RE.fullmatch(raw):
        raise ValueError("ID OpenAlex harus berbentuk A diikuti angka, misalnya A5056916903.")
    return raw


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_ok(expected: str | None, received: str | None) -> bool:
    if not expected or not received:
        return False
    return hmac.compare_digest(str(expected), str(received))


class LoginRateLimiter:
    """Batas percobaan login per kunci, disimpan di memori proses."""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        cutoff = self.clock() - self.window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return attempts

    def allowed(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key)) < self.max_attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(self.clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
