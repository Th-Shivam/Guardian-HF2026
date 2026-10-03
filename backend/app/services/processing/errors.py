"""Domain errors for the message-processing layer.

Transport-agnostic on purpose: nothing here imports FastAPI or a provider
adapter, so the pipeline behaves the same whether it is driven by a webhook, a
CLI, or a test.
"""


class ProcessingError(Exception):
    """Base class for every message-processing failure."""


class InvalidMessageError(ProcessingError):
    """A message failed a business rule and cannot be processed further.

    Raised for problems the internal model itself does not police — an empty
    body, a timestamp with no timezone. Distinct from a pydantic
    ``ValidationError``, which means the message could not even be built.
    """
