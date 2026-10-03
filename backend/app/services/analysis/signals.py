"""The deterministic signal rules.

Each keyword rule is a compiled, case-insensitive pattern plus the plain-language
explanation shown when it fires. Keeping the rules as data in one list makes the
detector trivial and the behaviour easy to read, review, and extend.

These are heuristics, not proof. A signal means "this pattern is present", which
is evidence for a later verdict — never a verdict itself.
"""

import re
from dataclasses import dataclass

from app.services.analysis.models import SignalType

# Organisations and authorities scammers most often impersonate.
_ORGS = (
    r"bank|paypal|amazon|apple|microsoft|google|netflix|facebook|instagram|"
    r"whatsapp|meta|fedex|dhl|ups|usps|irs|hmrc|hdfc|sbi|icici|axis|paytm|"
    r"phonepe|visa|mastercard|customs|police|court|government|social security|"
    r"medicare|post office|courier|tax (?:office|department)"
)


@dataclass(frozen=True)
class _Rule:
    type: SignalType
    pattern: re.Pattern[str]
    explanation: str


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Order defines the order signals appear in a result.
RULES: tuple[_Rule, ...] = (
    _Rule(
        SignalType.URGENCY,
        _c(
            r"\b(?:urgent(?:ly)?|immediately|right now|as soon as possible|asap|"
            r"act now|last chance|final (?:notice|warning|reminder)|expir(?:e[sd]?|ing)|"
            r"deadline|within \d+\s*(?:hours?|hrs?|minutes?|mins?)|today only|"
            r"limited time|don'?t delay|hurry)\b"
        ),
        "Pressures you to act urgently or before a deadline.",
    ),
    _Rule(
        SignalType.CREDENTIAL_REQUEST,
        _c(
            r"\b(?:otp|one[- ]time (?:password|pin|code)|passwords?|passcode|pin|cvv|"
            r"verification code|security code|2fa|two[- ]factor|"
            r"login (?:details|credentials))\b"
        ),
        "Asks for a one-time code, password, PIN, or other credential.",
    ),
    _Rule(
        SignalType.MONEY_REQUEST,
        _c(
            r"(?:[$₹]\s?\d|\brs\.?\s?\d|\b(?:usd|inr)\b|"
            r"\b(?:pay(?:ment)?|transfer|wire|deposit|refund|invoice|billing|fee|fine|"
            r"penalty|gift\s?card|bitcoin|btc|crypto(?:currency)?|upi|western union|"
            r"bank (?:transfer|details|account))\b)"
        ),
        "Requests money, a payment, or financial details.",
    ),
    _Rule(
        SignalType.ACCOUNT_THREAT,
        _c(
            r"\b(?:suspend(?:ed|ing)?|block(?:ed|ing)?|lock(?:ed|ing)?|"
            r"deactivat(?:e|ed|ing)|disabl(?:e|ed|ing)|terminat(?:e|ed|ing)|"
            r"restrict(?:ed|ing)?|clos(?:e|ed|ing) your account|"
            r"unauthoriz(?:e|ed) (?:access|login|activity))\b"
        ),
        "Threatens to suspend, block, or close an account.",
    ),
    _Rule(
        SignalType.IMPERSONATION,
        _c(
            rf"(?:\b(?:this is|we are|we're|i am|i'm|on behalf of|official|from)\b"
            rf"[^.]{{0,30}}\b(?:{_ORGS})\b)"
            rf"|(?:\b(?:{_ORGS})\b\s+(?:support|security|"
            rf"customer (?:care|service|support)|help\s?desk|team|department|"
            rf"representative|official))"
        ),
        "Claims to represent a known organisation or authority.",
    ),
)
