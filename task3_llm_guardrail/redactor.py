from __future__ import annotations

import re

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9._%+-])"
)
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")


def luhn_valid(candidate: str) -> bool:
    digits = [int(ch) for ch in candidate if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False

    total = 0
    parity = len(digits) % 2

    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    return total % 10 == 0


def redact_text(text: str) -> str:
    text = EMAIL_RE.sub("[REDACTED]", text)
    text = SSN_RE.sub("[REDACTED]", text)

    def replace_card(match: re.Match[str]) -> str:
        value = match.group(0)
        return "[REDACTED]" if luhn_valid(value) else value

    return CARD_RE.sub(replace_card, text)


class StreamingPIIRedactor:
    """Bounded-memory streaming redactor.

    A small carry buffer is retained so sensitive values split across provider
    chunks are considered together before being released.

    `carry_size` is deliberately configurable because the correct value is a
    policy/latency trade-off. This assessment uses 160 characters, far smaller
    than a full LLM response while comfortably covering the demonstrated PII
    formats.
    """

    def __init__(self, carry_size: int = 160):
        if carry_size < 32:
            raise ValueError("carry_size must be at least 32")
        self.carry_size = carry_size
        self._buffer = ""

    @property
    def buffered_chars(self) -> int:
        return len(self._buffer)

    def push(self, text: str) -> str:
        self._buffer += text

        if len(self._buffer) <= self.carry_size:
            return ""

        # Keep a bounded suffix. Because redaction replacements change length,
        # redact only the original prefix that is being released.
        release_at = len(self._buffer) - self.carry_size

        # If a *complete* sensitive match straddles our release boundary, move
        # the boundary back to the beginning of that match.
        for pattern in (EMAIL_RE, SSN_RE, CARD_RE):
            for match in pattern.finditer(self._buffer):
                if match.start() < release_at < match.end():
                    release_at = min(release_at, match.start())

        if release_at <= 0:
            return ""

        prefix = self._buffer[:release_at]
        self._buffer = self._buffer[release_at:]
        return redact_text(prefix)

    def flush(self) -> str:
        result = redact_text(self._buffer)
        self._buffer = ""
        return result
