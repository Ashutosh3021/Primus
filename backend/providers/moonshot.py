"""
Moonshot provider implementation for Primus.
"""

from backend.providers.openai_base import OpenAICompatibleProvider
from backend.providers.base import ProviderCapabilities


class MoonshotProvider(OpenAICompatibleProvider):
    """Provider for Moonshot (Kimi)."""

    def __init__(self, api_key: str, model: str):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.moonshot.cn/v1"
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=False,
            supports_streaming=True,
            supports_function_calling=True,
            supports_audio=False
        )
