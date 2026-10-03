"""Live URL verification.

Given URLs already extracted by the offline analyser, this asks SerpApi what
the open web reports about each distinct domain and returns that as
:class:`UrlEvidence` — the second half of Guardian's evidence, alongside the
deterministic text signals.

Design rules, matching the rest of the pipeline:

* **Best-effort.** Failed or budget-limited lookups carry an ``error`` and no
  results. Unconfigured deployments do not construct a verifier at all.
* **No verdict.** This collects and trims evidence. Deciding safe vs. scam is a
  later, separate layer.
* **Deterministic inputs.** Domains are deduplicated and queried in first-seen
  order, so the same message always produces the same set of lookups.
"""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import urlsplit

from app.core.logging import get_logger
from app.core.sentry import capture_exception
from app.services.url.errors import SerpApiError
from app.services.url.models import UrlEvidence
from app.services.url.serpapi import SerpApiClient

logger = get_logger(__name__)


class UrlVerifier:
    """Collect live search evidence for the domains in a message."""

    def __init__(
        self,
        client: SerpApiClient,
        *,
        results_per_domain: int = 5,
        max_domains: int = 5,
    ) -> None:
        if not 1 <= results_per_domain <= 10 or max_domains < 1:
            raise ValueError("URL verification requires 1–10 results and a positive domain budget.")
        self._client = client
        self._results_per_domain = results_per_domain
        self._max_domains = max_domains

    def verify(self, targets: list[tuple[str, str]]) -> list[UrlEvidence]:
        """Gather evidence for ``targets`` — ``(url, domain)`` pairs.

        Reuses the offline analyser's URLs/domains; the wire boundary only
        sanitizes hostnames so credentials and search operators cannot leak
        into a query. Each domain gets at most one lookup per message, even
        on failure. Results remain in the original URL order.
        """
        evidence: list[UrlEvidence] = []
        cache: dict[str, UrlEvidence] = {}
        attempted = 0

        for url, raw_domain in targets:
            try:
                domain = _query_domain(raw_domain)
            except ValueError:
                evidence.append(
                    UrlEvidence(
                        url=url,
                        domain=raw_domain,
                        query="",
                        error="URL does not contain a searchable public domain or IP address.",
                    )
                )
                continue

            if domain not in cache:
                item = UrlEvidence(url=url, domain=domain, query=build_query(domain))
                if attempted >= self._max_domains:
                    item = item.model_copy(update={"error": "Per-message domain lookup limit reached."})
                else:
                    attempted += 1
                    try:
                        results = self._client.search(item.query, limit=self._results_per_domain)
                        item = item.model_copy(update={"results": results})
                    except SerpApiError as exc:
                        # Client errors are sanitized; do not log target URLs,
                        # domains, query strings, or provider response bodies.
                        capture_exception(exc)
                        logger.warning("URL verification unavailable: %s", exc)
                        item = item.model_copy(update={"error": str(exc)})
                cache[domain] = item

            evidence.append(cache[domain].model_copy(update={"url": url}))

        logger.info(
            "URL verification: %d lookup(s), %d URL(s) with search evidence",
            attempted,
            sum(1 for item in evidence if item.consulted),
        )
        return evidence


def build_query(domain: str) -> str:
    """The search query used to look up a domain.

    Asks directly about the domain plus reputation words, which surfaces
    scam-advisory pages, forum warnings and threat feeds in one pass.
    """
    return f'"{domain}" (scam OR phishing OR fraud OR review)'


def _query_domain(domain: str) -> str:
    """Sanitize an already-extracted authority, without changing offline rules."""
    parsed = urlsplit(f"//{domain}")
    if not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Invalid domain.")
    # In particular, user:password@host must only send host to the provider.
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    host = host.removeprefix("www.")
    try:
        address = ip_address(host)
    except ValueError:
        labels = host.split(".")
        if len(host) > 253 or len(labels) < 2 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            raise ValueError("Invalid domain.") from None
        return host
    if not address.is_global:
        raise ValueError("Private IP addresses are not sent to search providers.")
    return str(address)
