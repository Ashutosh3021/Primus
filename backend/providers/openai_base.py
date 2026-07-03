"""
Base provider for OpenAI-compatible APIs (OpenAI, OpenRouter, Groq, etc.).
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


class OpenAICompatibleProvider(BaseProvider):
    """
    Base class for providers that implement OpenAI's API (compatible) format.
    """

    def __init__(self, api_key: str, model: str, base_url: str):
        super().__init__(api_key, model)
        self.base_url = base_url.rstrip("/")
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_messages_payload(self, messages: List[Message]) -> List[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def get_capabilities(self) -> ProviderCapabilities:
        # Default capabilities, should be overridden by subclasses if needed
        return ProviderCapabilities(
            supports_vision=False,
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
        
        payload = {
            "model": self.model,
            "messages": self._build_messages_payload(messages),
            "temperature": temperature,
            "stream": False
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting chat completion from {self.__class__.__name__}", extra={"model": self.model})
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            choice = data["choices"][0]
            
            completion = ChatCompletion(
                content=choice["message"]["content"],
                model=data["model"],
                provider=self.__class__.__name__,
                usage=data.get("usage"),
                finish_reason=choice.get("finish_reason")
            )
            
            logger.info(f"Received chat completion", extra={"model": data["model"]})
            return completion
            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in {self.__class__.__name__}", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in {self.__class__.__name__}", exc_info=True)
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
        
        payload = {
            "model": self.model,
            "messages": self._build_messages_payload(messages),
            "temperature": temperature,
            "stream": True
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting streaming chat completion from {self.__class__.__name__}", extra={"model": self.model})
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        
                        if data_str == "[DONE]":
                            break
                            
                        import json
                        try:
                            data = json.loads(data_str)
                            if data.get("choices"):
                                choice = data["choices"][0]
                                delta = choice.get("delta", {})
                                
                                yield ChatCompletionChunk(
                                    content=delta.get("content"),
                                    model=data.get("model"),
                                    finish_reason=choice.get("finish_reason")
                                )
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in {self.__class__.__name__}", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in {self.__class__.__name__}", exc_info=True)
            raise ProviderError(f"Provider error: {str(e)}") from e

    async def validate_credentials(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/models")
            return response.status_code == 200
        except Exception:
            return False
