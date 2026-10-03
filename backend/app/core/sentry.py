"""Optional Sentry tracing; only approved metadata leaves this process."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import sentry_sdk
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("guardian.sentry")
_enabled = False
_SAFE_DATA = {
    "input_type", "operation", "provider", "model", "success", "url_count",
    "gen_ai.operation.name", "gen_ai.agent.name", "gen_ai.tool.name",
    "gen_ai.provider.name", "gen_ai.request.model", "error.type",
}
_SAFE_NAMES = {
    "guardian.request", "invoke_agent Guardian", "guardian.message_normalization",
    "guardian.signal_analysis", "execute_tool url_verification", "guardian.gemma_reasoning",
    "guardian.response_formatting",
}
_SPAN_FIELDS = {
    "trace_id", "span_id", "parent_span_id", "op", "status", "origin",
    "start_timestamp", "timestamp",
}


def _safe_span(span: dict[str, Any]) -> dict[str, Any]:
    safe = {key: value for key, value in span.items() if key in _SPAN_FIELDS}
    safe["data"] = {key: value for key, value in span.get("data", {}).items() if key in _SAFE_DATA}
    if "description" in span:
        safe["description"] = span["description"] if span["description"] in _SAFE_NAMES else "guardian.operation"
    return safe


def _scrub_event(event: dict[str, Any], _: Any) -> dict[str, Any]:
    """Allowlist payload fields, not just common secret-key names."""
    safe = {key: event[key] for key in (
        "event_id", "timestamp", "start_timestamp", "type", "platform", "level", "sdk",
    ) if key in event}
    safe["contexts"] = {"trace": _safe_span(event.get("contexts", {}).get("trace", {}))}
    if event.get("type") == "transaction":
        name = event.get("transaction")
        safe["transaction"] = name if name in _SAFE_NAMES else "guardian.request"
        safe["spans"] = [_safe_span(span) for span in event.get("spans", [])]
    if "exception" in event:
        values = []
        for exc in event["exception"].get("values", []):
            # Exception messages, locals, source snippets and absolute paths can
            # contain message content, credentials or personal information.
            frames = [{key: frame[key] for key in ("module", "function", "lineno", "in_app")
                       if key in frame} | {"filename": Path(frame.get("filename", "unknown")).name}
                      for frame in exc.get("stacktrace", {}).get("frames", [])]
            values.append({"type": exc.get("type", "GuardianError"),
                           "value": "Guardian operation failed (details omitted)",
                           "stacktrace": {"frames": frames}})
        safe["exception"] = {"values": values}
    return safe


def init_sentry(dsn: str) -> bool:
    """An absent or invalid DSN must not prevent Guardian from starting."""
    global _enabled
    if _enabled or not dsn.strip():
        return _enabled
    try:
        sentry_sdk.init(
            dsn=dsn.strip(),
            traces_sample_rate=1.0,
            trace_lifecycle="static",
            stream_gen_ai_spans=False,  # Keep all spans behind the scrubber below.
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            include_source_context=False,
            max_breadcrumbs=0,
            default_integrations=False,  # No HTTP, AI-content or logging auto-capture.
            auto_session_tracking=False,
            trace_propagation_targets=[],
            debug=False,
            before_send=_scrub_event,
            before_send_transaction=_scrub_event,
        )
        _enabled = True
    except Exception:
        logger.warning("Sentry initialization failed; continuing without tracing.")
    return _enabled


def capture_exception(exc: BaseException) -> None:
    if _enabled:
        sentry_sdk.capture_exception(exc)


def set_success(span: Any, success: bool) -> None:
    span.set_data("success", success)
    span.set_status("ok" if success else "internal_error")


@contextmanager
def guardian_span(name: str, op: str, *, data: dict[str, Any] | None = None) -> Iterator[Any]:
    with sentry_sdk.start_span(op=op, name=name) as span:
        for key, value in (data or {}).items():
            if key in _SAFE_DATA:
                span.set_data(key, value)
        try:
            yield span
        except Exception:
            set_success(span, False)
            raise


def input_type(text: str, *, has_url: bool = False) -> str:
    """Inspect the existing bridge markers, never retain the text."""
    if "[Image OCR" in text:
        return "image"
    if "[Voice transcription]" in text:
        return "voice"
    return "url" if has_url or "http://" in text.lower() or "https://" in text.lower() else "text"


class GuardianTracingMiddleware:
    """Trace the complete ASGI request/response without inspecting its body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in (
            "/api/bridge/messages", "/api/whatsapp/webhook",
        ):
            await self.app(scope, receive, send)
            return
        with sentry_sdk.isolation_scope():
            # Continue only trace IDs from the bridge, not arbitrary baggage.
            headers = {"sentry-trace": value.decode("latin-1") for key, value in scope["headers"]
                       if key.lower() == b"sentry-trace"}
            transaction = sentry_sdk.continue_trace(headers, op="http.server", name="guardian.request")
            with sentry_sdk.start_transaction(transaction=transaction) as root:
                status = 500

                async def traced_send(message: Message) -> None:
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                    await send(message)

                try:
                    await self.app(scope, receive, traced_send)
                except Exception as exc:
                    set_success(root, False)
                    capture_exception(exc)
                    raise
                else:
                    set_success(root, status < 400)
