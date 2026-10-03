"""Result types for suspicious-signal analysis.

Provider-independent and decision-free: a result says *what was observed*
(URLs, signals, and why each fired), never *what to do about it*. The verdict
layer will consume these later.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SignalType(str, Enum):
    """A category of suspicious signal Guardian can detect.

    String-valued so it serialises to a stable, human-readable token. Order
    here is the order signals appear in a result.
    """

    URGENCY = "urgency"
    CREDENTIAL_REQUEST = "credential_request"
    MONEY_REQUEST = "money_request"
    ACCOUNT_THREAT = "account_threat"
    IMPERSONATION = "impersonation"
    SUSPICIOUS_URL = "suspicious_url"


class UrlSignalType(str, Enum):
    """A category of risk signal Guardian can read from a URL's text alone.

    Lexical only: every one of these is decided by looking at the link, never
    by fetching it. No network, no reputation feed.
    """

    NO_HTTPS = "no_https"
    SHORTENED = "shortened"
    IP_ADDRESS = "ip_address"
    IMPERSONATION = "impersonation"
    SUSPICIOUS_PATTERN = "suspicious_pattern"



class DetectedSignal(BaseModel):
    """One signal that fired, with a short reason a person can read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: SignalType
    explanation: str = Field(
        description="Plain-language reason this signal fired.",
        examples=["Pressures you to act urgently or before a deadline."],
    )


class UrlAnalysis(BaseModel):
    """Deterministic, text-only risk read of a single URL.

    Reports *what the link looks like* — scheme, domain, and any lexical red
    flags — and stops there. No fetch, no reputation lookup, and no verdict on
    whether the message is a scam.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(description="The URL exactly as it appeared in the message.")
    domain: str = Field(
        description="The host portion, lowercased, without a 'www.' prefix or port.",
        examples=["paypal-support.com"],
    )
    signals: list[UrlSignalType] = Field(
        default_factory=list,
        description="Risk signals this URL raised, in detection order.",
    )
    explanation: str = Field(
        description="One short, plain-language summary of the signals above.",
        examples=["Link to paypal-support.com: not sent over https; domain imitates 'paypal'."],
    )


class AnalysisResult(BaseModel):
    """What the analyser observed in one message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(description="The message this result describes.")
    urls: list[str] = Field(
        default_factory=list,
        description="Every URL found in the message, in order, de-duplicated.",
    )
    url_analyses: list[UrlAnalysis] = Field(
        default_factory=list,
        description="Per-URL risk analysis, one entry per URL in `urls`, same order.",
    )
    signals: list[DetectedSignal] = Field(
        default_factory=list,
        description="Suspicious signals that fired, each with an explanation.",
    )
