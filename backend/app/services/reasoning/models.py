"""Validated, evidence-grounded risk assessments returned by Gemma."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Reason = Annotated[str, Field(min_length=1, max_length=500)]
EvidenceId = Annotated[str, Field(min_length=1, max_length=150)]


class RiskAssessment(BaseModel):
    """A cautious risk estimate, never proof that a message is safe or a scam.

    Evidence IDs are JSON pointers into the message/analysis payload supplied
    to Gemma. The reasoning service also verifies that every pointer exists.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, str_strip_whitespace=True)

    response_language: Literal["english", "hindi", "hinglish"] = Field(
        description=(
            "Response style inferred from the buffered message/OCR content: English, "
            "Hindi in Devanagari, or Hinglish in Roman script. Default to english "
            "when there is insufficient language context."
        ),
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        description="Estimated risk given the supplied evidence; LOW does not mean verified safe."
    )
    confidence: float = Field(
        ge=0,
        lt=1,
        allow_inf_nan=False,
        description="Model-estimated confidence from 0 inclusive to 1 exclusive; not calibrated probability.",
    )
    reasons: list[Reason] = Field(
        min_length=1,
        max_length=6,
        description=(
            "Concise reasons in response_language, grounded only in the provided "
            "message, signals, and evidence."
        ),
    )
    evidence_used: list[EvidenceId] = Field(
        min_length=1,
        max_length=20,
        description="JSON pointers identifying the supplied evidence actually used, not invented sources.",
    )
    recommended_action: str = Field(
        min_length=1,
        max_length=600,
        description=(
            "A safe next step in response_language; independently verify money, "
            "credential, and OTP requests."
        ),
    )
    short_user_explanation: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Brief, plain-language explanation in response_language that acknowledges "
            "uncertainty and avoids certainty claims."
        ),
    )
