"""A thin client over SerpApi's search endpoint.

SerpApi (https://serpapi.com) runs a real web search and returns the engine's
results as JSON. We use it to ask "what does the open web say about this
domain?" — the question a reputation list cannot answer for a fresh phishing
domain. This module owns the HTTP call and nothing else: it knows how to turn
a query into :class:`SearchHit` objects, and it never decides whether anything
is a scam.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.url.errors import SerpApiError
from app.services.url.models import SearchHit

#: SerpApi's search endpoint. Fixed by the provider.
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

#: Snippets are cut to this many characters so evidence stays scannable and
#: cheap to store. SerpApi snippets are already short; this only trims outliers.
_MAX_SNIPPET = 300


class SerpApiClient:
    """Run live web searches through SerpApi.

    Holds one thread-safe, keep-alive :class:`httpx.Client`, shared across
    requests and closed by the application lifespan. Suspicious links and
    search-result pages are never fetched.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = SERPAPI_ENDPOINT,
        timeout: float = 10.0,
    ) -> None:
        if not api_key.strip():
            raise SerpApiError("SerpApi key is not configured.")
        self._api_key = api_key.strip()
        self._endpoint = endpoint
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        """Run one search and return up to ``limit`` organic results.

        Raises:
            SerpApiError: on a transport failure, a non-2xx response, or an
                ``error`` object in the payload (bad key, quota, etc.).
        """
        if not 1 <= limit <= 10:
            raise ValueError("Search result limit must be between 1 and 10.")

        # Keep results from one page and cap them locally; no pagination or
        # additional requests are needed to produce a concise evidence list.
        params = {
            "engine": "google",
            "q": query,
            "api_key": self._api_key,
            "hl": "en",
            "safe": "active",
            "nfpr": "1",  # prefer the domain's exact spelling
        }

        try:
            response = self._client.get(self._endpoint, params=params)
        except httpx.TimeoutException:
            raise SerpApiError("SerpApi request timed out.") from None
        except httpx.HTTPError:
            # Exception text can contain the request URL, including the key.
            raise SerpApiError("SerpApi request failed.") from None

        if response.status_code != 200:
            # Neither response bodies nor provider error messages are safe to
            # echo: they may contain credentials or the original query.
            raise SerpApiError(f"SerpApi returned HTTP {response.status_code}.")

        try:
            payload = response.json()
        except ValueError:
            raise SerpApiError("SerpApi returned a non-JSON response.") from None
        if not isinstance(payload, dict):
            raise SerpApiError("SerpApi returned an invalid response structure.")
        if payload.get("error"):
            raise SerpApiError("SerpApi could not complete the search.")

        metadata = payload.get("search_metadata", {})
        if not isinstance(metadata, dict) or metadata.get("status") not in (None, "Success"):
            raise SerpApiError("SerpApi search did not complete successfully.")
        raw_results = payload.get("organic_results", [])
        if not isinstance(raw_results, list):
            raise SerpApiError("SerpApi returned invalid organic results.")

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for raw in raw_results:
            hit = self._to_hit(raw)
            if hit is None or hit.url in seen:
                continue
            seen.add(hit.url)
            hits.append(hit)
            if len(hits) == limit:
                break
        return hits

    @staticmethod
    def _to_hit(raw: Any) -> SearchHit | None:
        """Map usable organic results, tolerating missing optional fields."""
        if not isinstance(raw, dict):
            return None
        link = _text(raw.get("link"))
        try:
            parsed = urlsplit(link)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return None
        except ValueError:
            return None
        title = _text(raw.get("title")) or link
        snippet = _text(raw.get("snippet")) or _text(raw.get("description"))
        if len(snippet) > _MAX_SNIPPET:
            snippet = snippet[: _MAX_SNIPPET - 1].rstrip() + "…"
        return SearchHit(
            title=title,
            url=link,
            snippet=snippet,
            source=_text(raw.get("source")) or parsed.hostname,
        )

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._client.close()


def _text(value: Any) -> str:
    """Keep provider text only, with compact whitespace and no invented content."""
    return " ".join(value.split()) if isinstance(value, str) else ""
