"""Suspicious-signal analysis.

Rule-based, deterministic, explainable. Given a :class:`GuardianMessage` it
reports which scam signals fire and every URL it found. It makes **no** final
safe/scam decision and talks to **no** network or model — that is deliberate,
and later layers build on top of this evidence.

    GuardianMessage -> SignalAnalyzer -> AnalysisResult
"""

from app.services.analysis.models import (
    AnalysisResult,
    DetectedSignal,
    SignalType,
    UrlAnalysis,
    UrlSignalType,
)
from app.services.analysis.service import SignalAnalyzer

__all__ = [
    "AnalysisResult",
    "DetectedSignal",
    "SignalAnalyzer",
    "SignalType",
    "UrlAnalysis",
    "UrlSignalType",
]
