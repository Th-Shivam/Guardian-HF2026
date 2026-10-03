"""Errors raised by URL verification."""


class UrlVerificationError(Exception):
    """Base class for every URL-verification failure."""


class SerpApiError(UrlVerificationError):
    """The SerpApi lookup could not be completed.

    Raised for a missing key, a transport failure, a non-2xx response, or an
    error object in the payload. Callers treat verification as best-effort:
    a message is never dropped because a lookup failed.
    """
