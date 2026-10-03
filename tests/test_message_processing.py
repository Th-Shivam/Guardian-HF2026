"""Unit tests for the internal message pipeline, without HTTP or WhatsApp.

The processor is the transport-independent core, so these tests import nothing
from ``app.schemas.whatsapp``, ``app.api``, or FastAPI.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.processing import (
    GuardianMessage,
    InvalidMessageError,
    MessageProcessor,
)

MessageFactory = Callable[..., GuardianMessage]


@pytest.fixture
def processor() -> MessageProcessor:
    return MessageProcessor()


@pytest.fixture
def guardian_message() -> MessageFactory:
    """Factory for a valid internal message; override any field per test."""

    def _build(**overrides: object) -> GuardianMessage:
        fields: dict[str, object] = {
            "message_id": "msg-1",
            "sender_id": "user-1",
            "text": "Your account is locked, verify at http://bit.ly/x",
            "received_at": datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
            "source": "whatsapp",
        }
        fields.update(overrides)
        return GuardianMessage(**fields)

    return _build


# --------------------------------------------------------------------------
# Valid message
# --------------------------------------------------------------------------


def test_valid_message_is_returned_unchanged(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    message = guardian_message()

    assert processor.process(message) == message


def test_processing_logs_the_message(
    processor: MessageProcessor,
    guardian_message: MessageFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        processor.process(guardian_message(message_id="msg-42", sender_id="user-7"))

    record = caplog.records[-1]
    assert "msg-42" in record.message
    assert "user-7" in record.message


def test_processing_does_not_log_the_body(
    processor: MessageProcessor,
    guardian_message: MessageFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Content may be malicious; it should not be copied into our logs."""
    secret = "verify at http://phishing.example/steal"

    with caplog.at_level("INFO"):
        processor.process(guardian_message(text=secret))

    assert secret not in caplog.text


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def test_surrounding_whitespace_is_trimmed(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    result = processor.process(guardian_message(text="  claim your prize\n"))

    assert result.text == "claim your prize"


def test_inner_whitespace_is_preserved(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    """Only surrounding whitespace is touched; the body is otherwise ours to keep."""
    result = processor.process(guardian_message(text="  line one\nline two  "))

    assert result.text == "line one\nline two"


def test_non_utc_timestamp_is_converted_to_utc(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    plus_five = timezone(timedelta(hours=5))
    message = guardian_message(received_at=datetime(2023, 11, 15, 3, 13, 20, tzinfo=plus_five))

    result = processor.process(message)

    assert result.received_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_normalisation_returns_a_new_object(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    """Messages are immutable records, so normalising must not mutate in place."""
    message = guardian_message(text="  padded  ")

    result = processor.process(message)

    assert message.text == "  padded  "
    assert result is not message


# --------------------------------------------------------------------------
# Empty message
# --------------------------------------------------------------------------


@pytest.mark.parametrize("body", ["", "   ", "\n\t  \n"])
def test_empty_body_is_rejected(
    processor: MessageProcessor, guardian_message: MessageFactory, body: str
) -> None:
    with pytest.raises(InvalidMessageError, match="empty body"):
        processor.process(guardian_message(text=body))


def test_error_names_the_offending_message(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    with pytest.raises(InvalidMessageError, match="msg-9"):
        processor.process(guardian_message(message_id="msg-9", text=""))


def test_naive_timestamp_is_rejected(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    with pytest.raises(InvalidMessageError, match="naive timestamp"):
        processor.process(guardian_message(received_at=datetime(2023, 11, 14, 22, 13, 20)))


# --------------------------------------------------------------------------
# Missing required fields
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["message_id", "sender_id", "text", "received_at", "source"],
)
def test_missing_required_field_is_rejected(missing: str) -> None:
    fields: dict[str, object] = {
        "message_id": "msg-1",
        "sender_id": "user-1",
        "text": "hello",
        "received_at": datetime(2023, 11, 14, tzinfo=timezone.utc),
        "source": "whatsapp",
    }
    del fields[missing]

    with pytest.raises(ValidationError) as exc_info:
        GuardianMessage(**fields)

    assert [error["loc"] for error in exc_info.value.errors()] == [(missing,)]


def test_no_fields_at_all_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GuardianMessage()


def test_unknown_field_is_rejected() -> None:
    """The internal shape is a contract; a mapping typo should fail loudly."""
    with pytest.raises(ValidationError):
        GuardianMessage(
            message_id="msg-1",
            sender_id="user-1",
            text="hello",
            received_at=datetime(2023, 11, 14, tzinfo=timezone.utc),
            source="whatsapp",
            unexpected="boom",
        )


def test_message_is_immutable(guardian_message: MessageFactory) -> None:
    message = guardian_message()

    with pytest.raises(ValidationError):
        message.text = "changed"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Provider independence
# --------------------------------------------------------------------------


def test_processor_needs_no_provider(
    processor: MessageProcessor, guardian_message: MessageFactory
) -> None:
    """The core only ever sees GuardianMessage — no adapter, no HTTP."""
    result = processor.process(guardian_message(source="cli"))

    assert result.source == "cli"
    assert isinstance(result, GuardianMessage)


def test_processing_package_imports_neither_whatsapp_nor_fastapi() -> None:
    """Guard the dependency direction for real, in a fresh interpreter.

    Importing the pipeline in a clean process and checking ``sys.modules`` is
    what proves independence — a stray import inside any of these modules would
    show up here even though this test file never mentions it.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    # ``pythonpath = backend`` from pytest.ini is a pytest-only setting, so the
    # child process needs the path passed explicitly.
    backend = Path(__file__).resolve().parents[1] / "backend"
    env = {**os.environ, "PYTHONPATH": str(backend)}

    probe = (
        "import sys;"
        "import app.services.processing as p;"
        "p.MessageProcessor();"
        "bad = sorted(m for m in sys.modules if m.startswith(('fastapi','app.services.whatsapp','app.schemas.whatsapp','app.api')));"
        "print(bad)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", f"pipeline pulled in: {result.stdout.strip()}"
