"""Ground Gemma's structured risk estimate in Guardian's existing evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.services.reasoning.client import GemmaClient
from app.services.reasoning.errors import InvalidAssessmentError, ReasoningInputError
from app.services.reasoning.models import RiskAssessment
from app.services.reasoning.prompts import build_prompt

if TYPE_CHECKING:
    from app.services.analysis import AnalysisResult
    from app.services.processing.models import GuardianMessage


class GemmaReasoner:
    """Consume existing analysis without extracting URLs or detecting signals."""

    def __init__(self, client: GemmaClient, *, max_input_chars: int = 60_000) -> None:
        if max_input_chars < 1:
            raise ValueError("Gemma input budget must be positive.")
        self._client = client
        self._max_input_chars = max_input_chars

    @property
    def provider(self) -> str:
        return self._client.provider

    @property
    def model(self) -> str:
        return self._client.model

    def assess(self, message: GuardianMessage, analysis: AnalysisResult) -> RiskAssessment:
        """Return a validated model response or an explicit reasoning failure.

        No silent truncation, JSON repair, defaults, or heuristic risk fallback:
        callers must not mistake unavailable reasoning for a LOW assessment.
        """
        if analysis.message_id != message.message_id:
            raise ReasoningInputError("Analysis does not belong to this message.")
        prompt = build_prompt(message, analysis)
        if len(prompt.content) > self._max_input_chars:
            raise ReasoningInputError("Gemma input exceeds the configured character budget.")
        content = self._client.complete(prompt.content, prompt.json_schema)
        try:
            assessment = RiskAssessment.model_validate_json(content)
        except ValidationError:
            # Pydantic errors include input values, which can contain secrets
            # or hostile text. Never log or expose the validation detail.
            raise InvalidAssessmentError("Gemma returned an invalid risk assessment.") from None
        if any(reference not in prompt.evidence_ids for reference in assessment.evidence_used):
            raise InvalidAssessmentError("Gemma cited evidence that was not supplied.")
        return assessment
