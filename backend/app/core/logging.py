"""Logging setup.

Deliberately thin for now. Structured/JSON logging can replace the formatter
here once Guardian is handling real traffic, without touching call sites.
"""

import logging

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(debug: bool = False) -> None:
    """Configure root logging once, idempotently."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=_LOG_FORMAT,
        force=True,
    )
    # SerpApi authenticates in the query string. HTTPX logs complete request
    # URLs at INFO, and httpcore emits request details at DEBUG; neither should
    # copy credentials or user-supplied domains into application logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name)
