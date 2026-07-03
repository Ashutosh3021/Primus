"""
Ollama provider implementation for Primus.
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


class OllamaProvider(BaseProvider):
    """Provider for Ollama (local models)."""

    def __init__(self, api_key: str, model: str, base_url: str = "http://localhost:11434/api"):
        super().__init__(api_key, model)
        self.base_url = base_url.rstrip("/")
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=300.0  # Longer timeout for local models
            )
        return self._client

    def _build_messages_payload(self, messages: List[Message]) -> List[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def get_capabilities(self) -> ProviderCapabilities:
        # Ollama capabilities depend on the model, we'll set sensible defaults
        return ProviderCapabilities(
            supports_vision=False,
            supports_streaming=True,
            supports_function_calling=False,
            supports_audio=False
        )

    @retry(
        stop=stop_after_attempt(2),
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
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
            
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting chat completion from Ollama", extra={"model": self.model})
            response = await client.post("/chat", json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            completion = ChatCompletion(
                content=data["message"]["content"],
                model=data["model"],
                provider="OllamaProvider",
                finish_reason=data.get("done_reason") if data.get("done") else None
            )
            
            logger.info(f"Received chat completion from Ollama", extra={"model": data["model"]})
            return completion
            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Ollama", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Ollama", exc_info=True)
            raise ProviderError(f"Provider error: {str(e)}") from e

    @retry(
        stop=stop_after_attempt(2),
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
            "stream": True,
            "options": {
                "temperature": temperature
            }
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
            
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting streaming chat completion from Ollama", extra={"model": self.model})
            async with client.stream("POST", "/chat", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line:
                        import json
                        try:
                            data = json.loads(line)
                            
                            if "message" in data and "content" in data["message"]:
                                yield ChatCompletionChunk(
                                    content=data["message"]["content"],
                                    model=data.get("model")
                                )
                            
                            if data.get("done"):
                                yield ChatCompletionChunk(
                                    finish_reason=data.get("done_reason")
                                )
                                
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Ollama", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Ollama", exc_info=True)
            raise ProviderError(f"Provider error: {str(e)}") from e

    async def validate_credentials(self) -> bool:
        try:
            # Check if Ollama is running and the model exists
            client = await self._get_client()
            response = await client.get("/tags")
            if response.status_code != 200:
                return False
                
            data = response.json()
            for model in data.get("models", []):
                if model.get("name") == self.model or model.get("name").startswith(f"{self.model}:"):
                    return True
            return False
            
        except Exception:
            return False
