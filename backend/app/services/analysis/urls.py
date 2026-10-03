"""URL extraction and lexical risk analysis.

Lives beside the analyser because signal detection is its only consumer today.
When ``services/url/`` grows real network behaviour (redirect expansion,
reputation), that package will own anything that touches the wire; this stays
purely lexical — no I/O, no guessing. Every judgement here is made by reading
the link's text, so the same URL always reads the same way.
"""

import re

from app.services.analysis.models import UrlAnalysis, UrlSignalType

# Matches links that announce themselves with a scheme or a ``www.`` prefix.
# Bare hostnames ("bit.ly/x" with no scheme) are intentionally not matched:
# detecting them reliably means a TLD list and a pile of false positives, which
# is not worth it for a first, deterministic pass.
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]{}\"']+", re.IGNORECASE)

# Punctuation that is almost always sentence trailing, not part of the URL.
_TRAILING = ".,;:!?\"'>)]}"

# Hosts whose whole purpose is to hide the real destination behind a redirect.
_SHORTENERS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "rebrand.ly",
        "cutt.ly",
        "rb.gy",
        "shorturl.at",
        "tiny.cc",
        "bit.do",
        "t.ly",
        "lnkd.in",
        "trib.al",
        "adf.ly",
        "s.id",
        "shorte.st",
    }
)

# Distinctive brand tokens scammers register look-alike domains for. Kept
# distinctive on purpose: short or generic words ("bank", "ups", "meta") match
# too many legitimate domains as substrings, so they are left out.
_BRANDS = frozenset(
    {
        "paypal",
        "amazon",
        "apple",
        "microsoft",
        "google",
        "netflix",
        "facebook",
        "instagram",
        "whatsapp",
        "fedex",
        "usps",
        "paytm",
        "phonepe",
        "icici",
        "hdfc",
        "mastercard",
        "chase",
        "coinbase",
        "binance",
        "walmart",
        "ebay",
        "linkedin",
        "dropbox",
        "wellsfargo",
        "citibank",
    }
)

# Two-level public suffixes, so the registrable label of "paypal.co.uk" is read
# as "paypal", not "co". Not exhaustive — just the ones worth not tripping over.
_TWO_LEVEL_TLDS = frozenset(
    {
        "co.uk",
        "org.uk",
        "gov.uk",
        "ac.uk",
        "co.in",
        "co.jp",
        "co.nz",
        "co.za",
        "com.au",
        "com.br",
        "com.mx",
        "com.sg",
        "com.hk",
    }
)

# TLDs disproportionately common in throwaway phishing domains.
_RISKY_TLDS = frozenset(
    {
        "zip",
        "mov",
        "xyz",
        "top",
        "tk",
        "ml",
        "ga",
        "cf",
        "gq",
        "work",
        "click",
        "link",
        "loan",
        "country",
        "review",
        "party",
        "win",
        "bid",
        "gdn",
    }
)


def extract_urls(text: str) -> list[str]:
    """Return every URL in ``text``, in order, de-duplicated case-insensitively."""
    seen: dict[str, str] = {}
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_TRAILING)
        key = url.lower()
        if url and key not in seen:
            seen[key] = url
    return list(seen.values())


def _host(url: str) -> str:
    """The bare hostname of a URL, lowercased and without a ``www.`` prefix."""
    host = url.split("://", 1)[-1]
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    return host[4:].lower() if host.lower().startswith("www.") else host.lower()


def shortener_hosts(urls: list[str]) -> list[str]:
    """Return the distinct shortener hosts among ``urls``, sorted."""
    return sorted({h for url in urls if (h := _host(url)) in _SHORTENERS})


def _strip_port(host: str) -> str:
    """Drop a trailing ``:port`` from a hostname, leaving IPv6 literals alone."""
    if host.startswith("["):  # bracketed IPv6, e.g. [::1]:8080 — leave as-is
        return host
    return host.rsplit(":", 1)[0] if re.search(r":\d+$", host) else host


def _is_ip_literal(domain: str) -> bool:
    """True if ``domain`` is a raw IPv4/IPv6 address rather than a name."""
    if domain.startswith("["):  # [2001:db8::1]
        return True
    octets = domain.split(".")
    return len(octets) == 4 and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)


def _main_label(domain: str) -> str:
    """The registrable label of a domain, e.g. 'paypal' in 'www.paypal.co.uk'."""
    labels = domain.split(".")
    if len(labels) < 2:
        return domain
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LEVEL_TLDS:
        return labels[-3]
    return labels[-2]


def _impersonated_brand(domain: str) -> str | None:
    """A known brand that appears in ``domain`` without being its real owner.

    Matches brands only as whole dot/hyphen-delimited tokens, so
    'paypal-login.com' and 'paypal.secure.co' are flagged while 'paypal.com'
    and unrelated words that merely contain a brand as a substring are not.
    """
    main = _main_label(domain)
    tokens = set(re.split(r"[.\-]", domain))
    for brand in sorted(_BRANDS):
        if brand in tokens and brand != main:
            return brand
    return None


def _suspicious_patterns(url: str, domain: str) -> list[str]:
    """Lexical red flags in a URL's structure, each as a short phrase."""
    reasons: list[str] = []

    authority = url.split("://", 1)[-1].split("/", 1)[0]
    if "@" in authority:
        reasons.append("hides the real host behind an '@' sign")
    if "xn--" in domain:
        reasons.append("uses punycode that can disguise look-alike characters")
    if len(domain.split(".")) >= 5:
        reasons.append("buries the real domain under many subdomains")
    tld = domain.rsplit(".", 1)[-1]
    if tld in _RISKY_TLDS:
        reasons.append(f"uses the uncommon .{tld} top-level domain")
    if _main_label(domain).count("-") >= 2:
        reasons.append("packs multiple hyphens into the domain name")

    return reasons


def analyze_url(url: str) -> UrlAnalysis:
    """Read one URL and report its lexical risk signals.

    Deterministic and offline: the link is never fetched. The result lists
    which signals fired and a one-line explanation; it reaches no verdict.
    """
    domain = _strip_port(_host(url))
    findings: list[tuple[UrlSignalType, str]] = []

    if not url.lower().startswith("https://"):
        findings.append((UrlSignalType.NO_HTTPS, "is not sent over https"))

    if domain in _SHORTENERS:
        findings.append(
            (UrlSignalType.SHORTENED, f"uses the link shortener {domain!r}, hiding its destination")
        )

    if _is_ip_literal(domain):
        findings.append(
            (UrlSignalType.IP_ADDRESS, "points at a raw IP address instead of a domain name")
        )
    elif (brand := _impersonated_brand(domain)) is not None:
        # Only meaningful for named hosts; an IP cannot imitate a brand.
        findings.append((UrlSignalType.IMPERSONATION, f"domain imitates {brand!r}"))

    for reason in _suspicious_patterns(url, domain):
        findings.append((UrlSignalType.SUSPICIOUS_PATTERN, reason))

    # De-duplicate signal types while preserving the order they were found in.
    signals = list(dict.fromkeys(signal for signal, _ in findings))

    if findings:
        explanation = f"Link to {domain}: " + "; ".join(reason for _, reason in findings) + "."
    else:
        explanation = f"No obvious risk signals in the link to {domain}."

    return UrlAnalysis(url=url, domain=domain, signals=signals, explanation=explanation)
