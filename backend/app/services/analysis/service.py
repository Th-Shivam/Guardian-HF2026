"""The signal analyser.

Runs the deterministic rules over a message and collects what fired. Stateless
and side-effect free: same message in, same result out, every time.
"""

from app.services.analysis.models import AnalysisResult, DetectedSignal, SignalType
from app.services.analysis.signals import RULES
from app.services.analysis.urls import analyze_url, extract_urls, shortener_hosts
from app.services.processing.models import GuardianMessage


class SignalAnalyzer:
    """Detects suspicious signals in a message. Rule-based, no LLM, no network."""

    def analyze(self, message: GuardianMessage) -> AnalysisResult:
        """Report the URLs and suspicious signals in ``message``.

        Pure analysis: it extracts evidence and explains it, and deliberately
        stops short of any safe/scam decision.
        """
        text = message.text
        urls = extract_urls(text)
        url_analyses = [analyze_url(url) for url in urls]

        signals = [
            DetectedSignal(type=rule.type, explanation=rule.explanation)
            for rule in RULES
            if rule.pattern.search(text)
        ]

        hosts = shortener_hosts(urls)
        if hosts:
            signals.append(
                DetectedSignal(
                    type=SignalType.SUSPICIOUS_URL,
                    explanation=(
                        "Uses a shortened link that hides its real destination: "
                        f"{', '.join(hosts)}."
                    ),
                )
            )

        return AnalysisResult(
            message_id=message.message_id,
            urls=urls,
            url_analyses=url_analyses,
            signals=signals,
        )
