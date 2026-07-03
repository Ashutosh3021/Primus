"""
Google Gemini provider implementation for Primus.
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


class GeminiProvider(BaseProvider):
    """Provider for Google Gemini."""

    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _get_endpoint(self, stream: bool = False) -> str:
        endpoint_type = "streamGenerateContent" if stream else "generateContent"
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{endpoint_type}?key={self.api_key}"

    def _convert_messages(self, messages: List[Message]) -> dict:
        """Convert messages to Gemini format."""
        contents = []
        
        for msg in messages:
            if msg.role == "system":
                # Gemini handles system messages via system_instruction
                continue
                
            role = "user" if msg.role == "user" else "model"
            
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}]
            })
            
        payload = {"contents": contents}
        
        # Check if there's a system message to add
        system_message = next((msg for msg in messages if msg.role == "system"), None)
        if system_message:
            payload["systemInstruction"] = {"parts": [{"text": system_message.content}]}
            
        return payload

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
        
        payload = self._convert_messages(messages)
        
        generation_config = {"temperature": temperature}
        if max_tokens:
            generation_config["maxOutputTokens"] = max_tokens
            
        payload["generationConfig"] = generation_config
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting chat completion from Gemini", extra={"model": self.model})
            response = await client.post(self._get_endpoint(), json=payload)
            response.raise_for_status()
            
            data = response.json()
            candidate = data["candidates"][0]
            content = candidate["content"]["parts"][0]["text"]
            
            completion = ChatCompletion(
                content=content,
                model=self.model,
                provider="GeminiProvider",
                usage=data.get("usageMetadata"),
                finish_reason=candidate.get("finishReason")
            )
            
            logger.info(f"Received chat completion from Gemini", extra={"model": self.model})
            return completion
            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Gemini", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Gemini", exc_info=True)
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
        
        payload = self._convert_messages(messages)
        
        generation_config = {"temperature": temperature}
        if max_tokens:
            generation_config["maxOutputTokens"] = max_tokens
            
        payload["generationConfig"] = generation_config
        payload.update(kwargs)
        
        try:
            logger.info(f"Requesting streaming chat completion from Gemini", extra={"model": self.model})
            async with client.stream("POST", self._get_endpoint(stream=True), json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line:
                        import json
                        try:
                            data = json.loads(line)
                            
                            if "candidates" in data and data["candidates"]:
                                candidate = data["candidates"][0]
                                if "content" in candidate and "parts" in candidate["content"]:
                                    part = candidate["content"]["parts"][0]
                                    if "text" in part:
                                        yield ChatCompletionChunk(
                                            content=part["text"],
                                            model=self.model
                                        )
                                if "finishReason" in candidate:
                                    yield ChatCompletionChunk(
                                        finish_reason=candidate["finishReason"]
                                    )
                                    
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.HTTPStatusError as e:
            error_logger.error(f"HTTP error in Gemini", exc_info=True)
            raise ProviderError(f"HTTP error: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            error_logger.error(f"Error in Gemini", exc_info=True)
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
