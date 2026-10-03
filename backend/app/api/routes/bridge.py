"""Authenticated Baileys hand-off; all analysis stays in the existing pipeline."""

import re
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_message_processor
from app.schemas.bridge import BridgeMessage, BridgeReply
from app.services.processing import InvalidMessageError, MessageProcessor

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
_REPLY_COPY = {
    "english": {
        "why": "Why",
        "action": "What to do",
        "uncertain": "I couldn't confirm whether this message is genuine.",
        "pause": "Pause and check before acting.",
        "verify": (
            "For money, OTP, password, PIN or login requests: don't pay or share details "
            "through this message/link. Verify through the organisation's official app, "
            "a website you open yourself, or a trusted official phone number."
        ),
    },
    "hindi": {
        "why": "क्यों",
        "action": "क्या करें",
        "uncertain": "यह संदेश असली है या नहीं, इसकी पुष्टि नहीं हो सकी।",
        "pause": "कुछ करने से पहले रुककर जाँच करें।",
        "verify": (
            "पैसे, OTP, पासवर्ड, PIN या लॉगिन जानकारी माँगने पर इस संदेश/लिंक से "
            "भुगतान या जानकारी साझा न करें। संस्था के आधिकारिक ऐप, खुद खोली गई "
            "वेबसाइट या उसके भरोसेमंद आधिकारिक फोन नंबर से पुष्टि करें।"
        ),
    },
    "hinglish": {
        "why": "Kyun",
        "action": "Kya karein",
        "uncertain": "Yeh message asli hai ya nahi, iski pushti nahi ho paayi.",
        "pause": "Kuch karne se pehle ruk kar check karein.",
        "verify": (
            "Paise, OTP, password, PIN ya login details maange jaayen toh is message/link "
            "se payment ya details share na karein. Organisation ke official app, khud "
            "kholi hui website ya uske bharosemand official phone number se confirm karein."
        ),
    },
}


def _brief(text: str, limit: int, fallback: str) -> str:
    """Prefer complete sentences instead of truncating a safety instruction."""
    text = " ".join(text.split())
    if re.search(r"(?:100|१००)\s*(?:[%％]|per\s*cent|प्रतिशत)", text, re.IGNORECASE):
        return fallback
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?।])\s+", text):
        if len(" ".join([*kept, sentence])) > limit:
            break
        kept.append(sentence)
    return " ".join(kept) or fallback


def require_bridge_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Fail closed unless the bridge and this app share a strong secret."""
    expected = request.app.state.settings.whatsapp_bridge_token.get_secret_value().strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="WhatsApp bridge is not configured.")
    if credentials is None or not compare_digest(
        credentials.credentials.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid bridge credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/messages",
    response_model=BridgeReply,
    dependencies=[Depends(require_bridge_token)],
    summary="Analyze a normalized WhatsApp message and return its reply",
)
def receive_bridge_message(
    message: BridgeMessage,
    processor: Annotated[MessageProcessor, Depends(get_message_processor)],
) -> BridgeReply:
    """Call the existing pipeline once; format only its generated assessment."""
    try:
        processed = processor.process_with_analysis(message)
    except InvalidMessageError:
        raise HTTPException(status_code=422, detail="Message could not be processed.") from None

    assessment = processed.risk_assessment
    if assessment is None:
        # No invented assessment when inference is disabled or fails. The
        # bridge may send a transport-level availability notice, not a verdict.
        raise HTTPException(status_code=503, detail="Guardian could not produce a risk assessment.")

    copy = _REPLY_COPY[assessment.response_language]
    why = _brief(assessment.short_user_explanation, 240, copy["uncertain"])
    action = _brief(assessment.recommended_action, 180, copy["pause"])
    # The conditional reminder covers sensitive requests in every language,
    # without adding detection rules or changing the assessment. Confidence is
    # a model estimate, so omit percentages and raw evidence from the reply.
    return BridgeReply(
        message_id=processed.message.message_id,
        reply=(
            f"*Guardian — {assessment.risk_level} RISK*\n\n"
            f"*{copy['why']}*\n{why}\n\n"
            f"*{copy['action']}*\n{action}\n{copy['verify']}"
        ),
    )
