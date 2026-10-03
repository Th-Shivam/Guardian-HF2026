"""The internal message-processing service.

Everything that arrives from any transport funnels through here before it is
stored or answered. Normalisation and offline signal detection run first;
optional live URL verification enriches that analysis with search evidence.
Configured Gemma reasoning then turns these observations into a risk assessment.

Deliberately independent of WhatsApp and FastAPI: this module imports neither,
so it can be exercised on its own and driven by anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.processing.errors import InvalidMessageError
from app.services.processing.models import GuardianMessage
from app.services.reasoning.errors import ReasoningError

if TYPE_CHECKING:  # annotation only; the real import happens lazily below
    from app.services.analysis import AnalysisResult, SignalAnalyzer
    from app.services.reasoning import GemmaReasoner, RiskAssessment
    from app.services.url import UrlVerifier

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProcessedMessage:
    """A message, its evidence, and a real Gemma assessment when available."""

    message: GuardianMessage
    analysis: AnalysisResult
    risk_assessment: RiskAssessment | None = None
    reasoning_error: str = "Gemma reasoning is disabled."


class MessageProcessor:
    """Validates and normalises inbound messages, then runs signal analysis.

    The offline analyser and URL verifier are reused unchanged. Gemma consumes
    their combined result after evidence collection, never in place of it.
    Clients are injected and owned by the caller, not created per message.
    """

    def __init__(
        self,
        analyzer: SignalAnalyzer | None = None,
        *,
        url_verifier: UrlVerifier | None = None,
        reasoner: GemmaReasoner | None = None,
    ) -> None:
        # Imported here, not at module scope: the analysis package imports this
        # one, so a top-level import would close the loop and fail at startup.
        from app.services.analysis import SignalAnalyzer

        self._analyzer = analyzer or SignalAnalyzer()
        self._url_verifier = url_verifier
        self._reasoner = reasoner

    def process(self, message: GuardianMessage) -> GuardianMessage:
        """Validate, normalise, and analyse one inbound message.

        Args:
            message: A structurally valid message, as produced by a provider
                adapter.

        Returns:
            The same message with normalised text and a UTC timestamp.

        Raises:
            InvalidMessageError: the message broke a business rule — an empty
                body, or a timestamp with no timezone to trust.
        """
        return self.process_with_analysis(message).message

    def process_with_analysis(self, message: GuardianMessage) -> ProcessedMessage:
        """Return the message, existing evidence, and a configured Gemma assessment.

        This is the evidence-bearing pipeline entry point. ``process`` retains
        its original message-only return contract for existing callers. Failed
        lookups remain explicit errors in ``analysis.url_evidence``; neither
        failed nor empty searches imply that a link is safe. Unavailable or
        invalid reasoning leaves ``risk_assessment`` unset with a diagnostic
        ``reasoning_error``; it never fabricates a verdict or drops evidence.
        """
        normalized = self._normalize(message)
        result = self._analyzer.analyze(normalized)
        if self._url_verifier is not None and result.url_analyses:
            evidence = self._url_verifier.verify(
                [(item.url, item.domain) for item in result.url_analyses]
            )
            result = result.model_copy(update={"url_evidence": evidence})

        assessment = None
        reasoning_error = "Gemma reasoning is disabled."
        if self._reasoner is not None:
            try:
                assessment = self._reasoner.assess(normalized, result)
                reasoning_error = ""
            except ReasoningError as exc:
                reasoning_error = str(exc)
                logger.warning("Gemma reasoning unavailable: %s", exc)

        # Log identifiers, provenance, and a signal summary only. Neither the
        # message, search evidence, nor generated explanation belongs in logs.
        logger.info(
            "Guardian received message %s from %s via %s: %d URL(s), signals=[%s]",
            normalized.message_id,
            normalized.sender_id,
            normalized.source,
            len(result.urls),
            ", ".join(signal.type.value for signal in result.signals),
        )
        return ProcessedMessage(
            message=normalized,
            analysis=result,
            risk_assessment=assessment,
            reasoning_error=reasoning_error,
        )

    @staticmethod
    def _normalize(message: GuardianMessage) -> GuardianMessage:
        """Apply the pipeline's normalization rules or raise."""
        text = message.text.strip()
        if not text:
            raise InvalidMessageError(
                f"Message {message.message_id!r} has an empty body; nothing to process."
            )

        received_at = message.received_at
        if received_at.tzinfo is None:
            # Guessing a timezone would silently corrupt the audit trail later.
            raise InvalidMessageError(
                f"Message {message.message_id!r} has a naive timestamp; refusing to guess a timezone."
            )

        return message.model_copy(
            update={"text": text, "received_at": received_at.astimezone(timezone.utc)}
        )
