from openai import OpenAI, OpenAIError

from app.config import get_settings
from app.providers.base import ProviderError


class OpenAICompatProvider:
    """Talks to any OpenAI-compatible /v1/chat/completions endpoint.

    The `openai` SDK is used as a transport, not as a commitment: pointing
    `base_url` elsewhere reaches Azure, OpenRouter, Together, Groq, vLLM, or
    Ollama with no code change. Only providers with a genuinely different wire
    format need a sibling of this file.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.name = settings.ai_provider
        self.model = settings.openai_model
        self._client = OpenAI(
            api_key=settings.openai_api_key or "missing",
            base_url=settings.openai_base_url,
            timeout=settings.ai_timeout_seconds,
            # One retry inside the SDK for transient transport failures. The
            # service layer's own retry is for *unusable content*, which is a
            # different failure and needs a different prompt.
            max_retries=1,
        )

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Deliberately not response_format=json_schema. Strict
                # structured output is the least portable part of this API and
                # is unsupported by most compatible endpoints, while the parser
                # already has to tolerate malformed batches. The portable path
                # and the robust path are the same path.
                temperature=1.0,
                max_tokens=700,
            )
        except OpenAIError as exc:
            raise ProviderError(str(exc)) from exc

        if not response.choices:
            raise ProviderError("provider returned no choices")

        return response.choices[0].message.content or ""
