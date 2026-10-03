"""Reasoning failures with safe messages, never provider response bodies."""


class ReasoningError(Exception):
    """No trustworthy structured assessment could be produced."""


class ReasoningProviderError(ReasoningError):
    """The configured Gemma endpoint could not complete the request."""


class InvalidAssessmentError(ReasoningError):
    """Gemma returned invalid JSON, an invalid schema, or unknown evidence IDs."""


class ReasoningInputError(ReasoningError):
    """The supplied analysis does not match the message or exceeds the input budget."""
