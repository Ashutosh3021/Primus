"""
Providers package for Primus AI Core.
"""

from typing import Dict, Type

from backend.providers.base import BaseProvider
from backend.providers.openai import OpenAIProvider
from backend.providers.openrouter import OpenRouterProvider
from backend.providers.anthropic import AnthropicProvider
from backend.providers.groq import GroqProvider
from backend.providers.moonshot import MoonshotProvider
from backend.providers.glm import GLMProvider
from backend.providers.gemini import GeminiProvider
from backend.providers.ollama import OllamaProvider

# Registry mapping provider names to their classes
PROVIDER_REGISTRY: Dict[str, Type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
    "moonshot": MoonshotProvider,
    "glm": GLMProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider
}

__all__ = [
    "BaseProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "AnthropicProvider",
    "GroqProvider",
    "MoonshotProvider",
    "GLMProvider",
    "GeminiProvider",
    "OllamaProvider",
    "PROVIDER_REGISTRY"
]
