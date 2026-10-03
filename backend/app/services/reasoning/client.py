"""Real Gemma inference over an OpenAI-compatible Chat Completions API."""

from __future__ import annotations

from typing import Any, Literal

import httpx

from app.services.reasoning.errors import ReasoningProviderError

GemmaProvider = Literal["openrouter", "openai_compatible"]
ResponseFormat = Literal["json_schema", "json_object"]


class GemmaClient:
    """One shared HTTP pool; no model substitution, retries, or fake responses."""

    def __init__(
        self,
        *,
        provider: GemmaProvider,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
        max_tokens: int = 1024,
        response_format: ResponseFormat = "json_schema",
    ) -> None:
        if provider not in ("openrouter", "openai_compatible"):
            raise ValueError("Unsupported Gemma provider.")
        if response_format not in ("json_schema", "json_object"):
            raise ValueError("Unsupported Gemma response format.")
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._response_format = response_format
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        headers = {"Accept": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        self._client = httpx.Client(headers=headers, timeout=timeout, follow_redirects=False)

    @property
    def provider(self) -> GemmaProvider:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: str, schema: dict[str, Any]) -> str:
        """Return only a completed assistant response; never log sensitive data."""
        response_format: dict[str, Any] = {"type": self._response_format}
        if self._response_format == "json_schema":
            response_format["json_schema"] = {
                "name": "guardian_risk_assessment",
                "strict": True,
                "schema": schema,
            }
        payload: dict[str, Any] = {
            "model": self._model,
            # Gemma 3 expects instructions within the first user turn.
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "stream": False,
            "response_format": response_format,
        }
        if self._provider == "openrouter":
            # Route only to hosts of the chosen Gemma model that support these
            # parameters; never fall back to another model or weaker format.
            payload["provider"] = {"require_parameters": True}

        try:
            response = self._client.post(self._endpoint, json=payload)
        except httpx.TimeoutException:
            raise ReasoningProviderError("Gemma request timed out.") from None
        except httpx.HTTPError:
            raise ReasoningProviderError("Gemma request failed.") from None
        if response.status_code != 200:
            raise ReasoningProviderError(f"Gemma provider returned HTTP {response.status_code}.")
        # Bound parsing of unexpected upstream responses independently of the
        # requested generation token budget. Never echo a raw response body.
        if len(response.content) > 256_000:
            raise ReasoningProviderError("Gemma provider returned an oversized response.")
        try:
            body = response.json()
        except ValueError:
            raise ReasoningProviderError("Gemma provider returned non-JSON data.") from None
        if not isinstance(body, dict) or body.get("error"):
            raise ReasoningProviderError("Gemma provider could not complete the request.")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ReasoningProviderError("Gemma provider returned no usable completion.")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise ReasoningProviderError("Gemma did not return a complete assessment.")
        message = choice.get("message")
        if (
            not isinstance(message, dict)
            or message.get("role") != "assistant"
            or message.get("refusal")
            or message.get("tool_calls")
        ):
            raise ReasoningProviderError("Gemma did not return an assessment.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ReasoningProviderError("Gemma returned an empty assessment.")
        return content

    def close(self) -> None:
        """Release connections when the application shuts down."""
        self._client.close()
