"""Evidence gathered from live URL verification.

These types describe *what the open web says* about a link's domain — nothing
more. They are the raw material for risk analysis, deliberately kept separate
from the offline :mod:`app.services.analysis` signals so the two kinds of
evidence (what the text looks like vs. what the world reports) never blur.
"""

from pydantic import BaseModel, ConfigDict, Field


class SearchHit(BaseModel):
    """One organic search result tied to a queried domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(description="Title of the result, as the source published it.")
    url: str = Field(description="The source page's own URL.")
    snippet: str = Field(
        max_length=300,
        description="Source-provided excerpt, at most 300 characters; empty if unavailable.",
        examples=["Warning: this domain is a known phishing site impersonating PayPal."],
    )
    source: str = Field(
        default="",
        description="Publisher/host the result came from, when the engine provides it.",
        examples=["scamadviser.com"],
    )


class UrlEvidence(BaseModel):
    """Live search evidence collected for a single URL's domain.

    One entry per extracted URL, with a shared lookup for URLs on the same
    domain. Search results are untrusted evidence, not a safety verdict; an
    empty result does not mean a link is safe.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(description="The URL this evidence was gathered for.")
    domain: str = Field(description="Sanitized lookup domain, or the original domain if invalid.")
    query: str = Field(description="Search query prepared for this domain; empty for invalid targets.")
    results: list[SearchHit] = Field(
        default_factory=list,
        description="Relevant results, best-first, capped at the configured limit.",
    )
    error: str = Field(
        default="",
        description="Why the lookup failed or was skipped. Empty on success, including no matches.",
    )

    @property
    def consulted(self) -> bool:
        """True when the lookup actually produced results."""
        return bool(self.results)

    @property
    def sources(self) -> list[str]:
        """Distinct source names/hosts across results, in first-seen order."""
        seen: dict[str, None] = {}
        for hit in self.results:
            if hit.source:
                seen.setdefault(hit.source, None)
        return list(seen)
