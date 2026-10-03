"""HTTP dependencies for application-owned services."""

from fastapi import Request

from app.services.processing import MessageProcessor


def get_message_processor(request: Request) -> MessageProcessor:
    """Use the pipeline and HTTP client managed by this app's lifespan."""
    return request.app.state.message_processor
