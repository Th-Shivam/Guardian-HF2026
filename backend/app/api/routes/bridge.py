"""Authenticated Baileys hand-off; all analysis stays in the existing pipeline."""

from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_message_processor
from app.schemas.bridge import BridgeMessage, BridgeReply
from app.services.processing import InvalidMessageError, MessageProcessor

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
_ACTION_LABELS = {
    "english": "Recommended action",
    "hindi": "सुझाया गया कदम",
    "hinglish": "Agla surakshit kadam",
}


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

    return BridgeReply(
        message_id=processed.message.message_id,
        reply=(
            f"Guardian — {assessment.risk_level} RISK\n\n"
            f"{assessment.short_user_explanation}\n\n"
            f"{_ACTION_LABELS[assessment.response_language]}: {assessment.recommended_action}"
        ),
    )
