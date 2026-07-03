"""
GLM (Zhipu AI) provider implementation for Primus.
"""

from backend.providers.openai_base import OpenAICompatibleProvider
from backend.providers.base import ProviderCapabilities


class GLMProvider(OpenAICompatibleProvider):
    """Provider for GLM (Zhipu AI)."""

    def __init__(self, api_key: str, model: str):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://open.bigmodel.cn/api/paas/v4"
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=True,
            supports_streaming=True,
            supports_function_calling=True,
            supports_audio=False
        )
