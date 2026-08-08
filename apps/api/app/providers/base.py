from typing import Protocol


class ProviderError(Exception):
    """The provider did not return a usable response.

    Wraps every vendor exception — timeouts, rate limits, 5xx, malformed
    payloads — so nothing above this layer imports a vendor's exception types.
    Swapping providers must not ripple into error handling.
    """


class SuggestionProvider(Protocol):
    """The entire surface a model provider has to implement.

    Everything that makes a *good* suggestion — prompt construction, topic
    rotation, the avoid-list, length and content validation — lives outside
    this seam, in app.services.suggestions. A provider only turns two strings
    into one string, which is why adding Anthropic or Gemini later is one file
    rather than a refactor.
    """

    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...
