"""
AI Router for selecting and routing to the correct provider.
"""

from typing import List, Optional

from backend.providers import BaseProvider, PROVIDER_REGISTRY
from backend.providers.base import ChatCompletion, Message
from backend.exceptions import ConfigInvalidError
from backend.logger import get_errors_logger, get_ai_requests_logger

logger = get_errors_logger(__name__)
ai_logger = get_ai_requests_logger(__name__)


class AIRouter:
    """Routes AI requests to the appropriate provider."""

    def __init__(self, provider_name: str, api_key: str, model: str):
        self.provider_name = provider_name.lower()
        
        if self.provider_name not in PROVIDER_REGISTRY:
            raise ConfigInvalidError(
                f"Unknown provider: {provider_name}. Available providers: {list(PROVIDER_REGISTRY.keys())}"
            )
            
        provider_class = PROVIDER_REGISTRY[self.provider_name]
        self.provider: BaseProvider = provider_class(api_key, model)
        
        ai_logger.info(f"Initialized AIRouter with provider: {provider_name}, model: {model}")

    async def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ChatCompletion:
        """
        Send a chat request to the provider.

        Args:
            messages: List of chat messages
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific arguments

        Returns:
            ChatCompletion with the response
        """
        ai_logger.info("Routing chat request to provider", extra={
            "provider": self.provider_name,
            "model": self.provider.model
        })
        return await self.provider.chat_completion(messages, temperature, max_tokens, **kwargs)

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        Send a streaming chat request to the provider.

        Args:
            messages: List of chat messages
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific arguments

        Yields:
            ChatCompletionChunk objects as they arrive
        """
        ai_logger.info("Routing streaming chat request to provider", extra={
            "provider": self.provider_name,
            "model": self.provider.model
        })
        async for chunk in self.provider.chat_completion_stream(messages, temperature, max_tokens, **kwargs):
            yield chunk

    def get_capabilities(self):
        """Get the capabilities of the current provider."""
        return self.provider.get_capabilities()

    async def validate(self) -> bool:
        """Validate that the provider credentials are valid."""
        return await self.provider.validate_credentials()
