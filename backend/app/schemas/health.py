"""Schemas for the metadata and health endpoints."""

from pydantic import BaseModel, Field


class ServiceInfo(BaseModel):
    """Basic identity of the running service."""

    name: str = Field(examples=["Guardian"])
    description: str = Field(examples=["WhatsApp-first AI safety assistant."])
    version: str = Field(examples=["0.1.0"])
    docs_url: str = Field(examples=["/docs"])


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: str = Field(examples=["ok"])
    env: str = Field(examples=["development"])
    version: str = Field(examples=["0.1.0"])
