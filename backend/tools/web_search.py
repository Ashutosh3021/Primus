"""
Web search tool for Primus (using DuckDuckGo).
"""

import httpx
from typing import Optional

from backend.tools.base import (
    BaseTool, ToolRegistry, ToolParam, ToolResult
)


@ToolRegistry.register
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for information using DuckDuckGo"
    params = [
        ToolParam("query", "string", "The search query", required=True),
        ToolParam("num_results", "integer", "Number of results (max 10)", required=False)
    ]

    async def execute(self, query: str, num_results: int = 3, **kwargs) -> ToolResult:
        try:
            # Use DuckDuckGo search API
            params = {
                "q": query,
                "format": "json"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get("https://api.duckduckgo.com/", params=params)
                response.raise_for_status()
                data = response.json()

                # Extract results
                results: list[str] = []
                abstract = data.get("Abstract", "")
                abstract_text = data.get("AbstractText", "")

                if abstract_text:
                    results.append(f"From {abstract}: {abstract_text}")

                related_topics = data.get("RelatedTopics", [])
                for i, topic in enumerate(related_topics[:num_results]):
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append(f"{i+1}. {topic['Text']}")

                if not results:
                    results = [f"No direct results found for '{query}'"]

                return ToolResult(
                    success=True,
                    content="\n".join(results)
                )

        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Search failed: {str(e)}"
            )
