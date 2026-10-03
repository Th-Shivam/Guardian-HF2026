"""URL verification against live web search.

Where :mod:`app.services.analysis` reads a link's *text*, this package asks
the open web what it *reports* about the link's domain, via SerpApi. The two
are complementary halves of Guardian's evidence and stay deliberately separate:
offline and always-on on one side, live and best-effort on the other.

    (url, domain) pairs -> UrlVerifier -> UrlEvidence

The verifier consumes the pairs the analyser already computed, sanitizes the
outbound domain, and never fetches the suspicious URL itself.
"""

from app.services.url.errors import SerpApiError, UrlVerificationError
from app.services.url.models import SearchHit, UrlEvidence
from app.services.url.serpapi import SerpApiClient
from app.services.url.service import UrlVerifier, build_query

__all__ = [
    "SearchHit",
    "SerpApiClient",
    "SerpApiError",
    "UrlEvidence",
    "UrlVerificationError",
    "UrlVerifier",
    "build_query",
]
