"""
Anthropic provider implementation for Primus.
"""

import httpx
from typing import AsyncGenerator, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.providers.base import (
    BaseProvider, ChatCompletion, ChatCompletionChunk, Message, ProviderCapabilities
)
from backend.logger import get_ai_requests_logger, get_errors_logger
from backend.exceptions import ProviderError

logger = get_ai_requests_logger(__name__)
error_logger = get_errors_logger(__name__)


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic (Claude)."""

    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        self.base_url = "https://api.anthropic.com/v1"
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                timeout=30.0
            )
        return self._client

    def _convert_messages(self, messages: List[Message]) -> tuple[Optional[str], List[dict]]:
        """Convert messages to Anthropic format, extracting system message if present."""
        system_message = None
        anthropic_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})
                
        return system_message, anthropic_messages

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=True,
            supports_streaming=True,
            supports_function_calling=True,
            supports_audio=False
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ChatCompletion:
        client = await self._get_client()
        
        system_message, anthropic_messages = self._convert_messages(messages)
        
        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens else 4096
        }
        
        if system_message:
            payload["system"] = system_message
            
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting chat completion from Anthropic", extra={"model": self.model})
            response = await client.post("/messages", json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            completion = ChatCompletion(
                content=data["content"][0]["text"],
                model=data["model"],
                provider="AnthropicProvider",
                usage=data.get("usage"),
                finish_reason=data.get("stop_reason")
            )
            
            logger.info(f"Received chat completion from Anthropic", extra={"model": data["model"]})
            return completion
            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Anthropic", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Anthropic", exc_info=True)
            raise ProviderError(f"Provider error: {str(e)}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def chat_completion_stream(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        client = await self._get_client()
        
        system_message, anthropic_messages = self._convert_messages(messages)
        
        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens else 4096,
            "stream": True
        }
        
        if system_message:
            payload["system"] = system_message
            
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting streaming chat completion from Anthropic", extra={"model": self.model})
            async with client.stream("POST", "/messages", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        
                        import json
                        try:
                            data = json.loads(data_str)
                            
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                yield ChatCompletionChunk(
                                    content=delta.get("text"),
                                    model=self.model
                                )
                            elif data.get("type") == "message_stop":
                                yield ChatCompletionChunk(
                                    finish_reason="stop"
                                )
                                
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Anthropic", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Anthropic", exc_info=True)
            raise ProviderError(f"Provider error: {str(e)}") from e

    async def validate_credentials(self) -> bool:
        try:
            # Just send a tiny message to check credentials
            await self.chat_completion(
                [Message(role="user", content="Hi")],
                max_tokens=1
            )
            return True
        except Exception:
            return False
