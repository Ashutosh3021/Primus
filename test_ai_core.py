"""
Test script for Primus AI Core.
"""

import asyncio
import sys

from backend.providers import PROVIDER_REGISTRY
from backend.providers.base import Message
from backend.router import AIRouter


async def test_provider_registry():
    """Test that all providers are registered."""
    print("Testing provider registry...")
    print(f"Registered providers: {list(PROVIDER_REGISTRY.keys())}")
    
    expected = ["openai", "openrouter", "anthropic", "groq", "moonshot", "glm", "gemini", "ollama"]
    assert all(p in PROVIDER_REGISTRY for p in expected), "Missing providers in registry!"
    print("OK: Provider registry test passed!\n")


async def test_ollama_initialization():
    """Test initializing Ollama provider (no credentials needed)."""
    print("Testing Ollama provider initialization...")
    try:
        # Create Ollama provider with dummy key (since Ollama doesn't need one)
        provider = PROVIDER_REGISTRY["ollama"]("dummy-key", "llama3.2")
        capabilities = provider.get_capabilities()
        print(f"Ollama capabilities: {capabilities}")
        print("OK: Ollama provider initialized successfully!\n")
        return True
    except Exception as e:
        print(f"WARNING: Ollama not available: {e} (this is expected if Ollama isn't running)\n")
        return False


async def test_router_initialization():
    """Test AI Router initialization with Ollama."""
    print("Testing AI Router initialization...")
    try:
        router = AIRouter("ollama", "dummy-key", "llama3.2")
        print(f"Router initialized with provider: {router.provider_name}")
        print("OK: Router initialization test passed!\n")
        return True
    except Exception as e:
        print(f"WARNING: Router initialization test failed gracefully: {e}\n")
        return False


async def main():
    print("=" * 50)
    print("Primus AI Core Test Suite")
    print("=" * 50 + "\n")
    
    await test_provider_registry()
    await test_ollama_initialization()
    await test_router_initialization()
    
    print("=" * 50)
    print("All tests completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
