from task3_llm_guardrail.redactor import StreamingPIIRedactor, redact_text


def test_email_redacted():
    assert redact_text("Email alice@example.com now") == "Email [REDACTED] now"


def test_ssn_redacted():
    assert redact_text("SSN 123-45-6789.") == "SSN [REDACTED]."


def test_luhn_valid_card_redacted():
    assert redact_text("Card 4111 1111 1111 1111.") == "Card [REDACTED]."


def test_random_16_digit_identifier_not_redacted_if_luhn_invalid():
    original = "ID 4111 1111 1111 1112"
    assert redact_text(original) == original


def test_cross_chunk_email_redaction():
    redactor = StreamingPIIRedactor(carry_size=64)
    output = []
    output.append(redactor.push("A" * 80 + " Email alice@exa"))
    output.append(redactor.push("mple.com finished. " + "B" * 80))
    output.append(redactor.flush())
    joined = "".join(output)

    assert "alice@example.com" not in joined
    assert "[REDACTED]" in joined


def test_cross_chunk_ssn_redaction():
    redactor = StreamingPIIRedactor(carry_size=64)
    output = []
    output.append(redactor.push("A" * 80 + " SSN 123-"))
    output.append(redactor.push("45-6789 done. " + "B" * 80))
    output.append(redactor.flush())
    joined = "".join(output)

    assert "123-45-6789" not in joined
    assert "[REDACTED]" in joined


def test_memory_is_bounded_during_long_stream():
    redactor = StreamingPIIRedactor(carry_size=64)

    for _ in range(1000):
        redactor.push("ordinary-output-with-spaces " * 2)
        # A match crossing the boundary can temporarily pull the boundary back,
        # but normal text remains close to the configured carry size.
        assert redactor.buffered_chars <= 128

    redactor.flush()
    assert redactor.buffered_chars == 0
