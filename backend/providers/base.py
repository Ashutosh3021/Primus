"""
Base provider interface and classes for Primus AI Core.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional


@dataclass
class Message:
    """Represents a chat message."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ProviderCapabilities:
    """Describes what a provider supports."""
    supports_vision: bool = False
    supports_streaming: bool = False
    supports_function_calling: bool = False
    supports_audio: bool = False


@dataclass
class ChatCompletion:
    """Represents a chat completion response."""
    content: str
    model: str
    provider: str
    usage: Optional[dict] = None
    finish_reason: Optional[str] = None


@dataclass
class ChatCompletionChunk:
    """Represents a single chunk of a streaming chat completion."""
    content: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None


class BaseProvider(ABC):
    """Base interface for all AI providers."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = None

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ChatCompletion:
        """
        Get a single chat completion from the provider.

        Args:
            messages: List of chat messages
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific arguments

        Returns:
            ChatCompletion object with the response
        """
        pass

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """
        Get a streaming chat completion from the provider.

        Args:
            messages: List of chat messages
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific arguments

        Yields:
            ChatCompletionChunk objects as they arrive
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """
        Get the capabilities of this provider.

        Returns:
            ProviderCapabilities object
        """
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """
        Validate that the credentials (API key, model, etc.) are valid.

        Returns:
            True if credentials are valid, False otherwise
        """
        pass
