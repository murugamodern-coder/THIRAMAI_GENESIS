"""
Research agent using DuckDuckGo search for autonomous information gathering.
"""

from __future__ import annotations

import logging
from typing import Any

from duckduckgo_search import DDGS

_LOG = logging.getLogger(__name__)


class ResearchAgent:
    """Autonomous research agent using DuckDuckGo."""
    
    def __init__(self) -> None:
        self.ddgs = DDGS()
    
    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """
        Perform web search using DuckDuckGo.
        
        Returns list of search results with title, url, and snippet.
        """
        try:
            results = []
            for result in self.ddgs.text(query, max_results=max_results):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", ""),
                    "source": "duckduckgo"
                })
            return results
        except Exception as exc:
            _LOG.error("DuckDuckGo search failed: %s", exc)
            return []
    
    def research_topic(self, topic: str, depth: int = 3) -> dict[str, Any]:
        """
        Perform deep research on a topic.
        
        Returns structured research results.
        """
        # Primary search
        primary_results = self.search(f"{topic} overview", max_results=depth)
        
        # Related searches
        related_results = []
        if primary_results:
            related_queries = [
                f"{topic} latest developments",
                f"{topic} challenges and solutions",
                f"{topic} trends and predictions"
            ]
            for query in related_queries:
                related_results.extend(self.search(query, max_results=depth//2))
        
        return {
            "topic": topic,
            "primary_results": primary_results,
            "related_results": related_results,
            "total_sources": len(primary_results) + len(related_results)
        }


# Global instance
research_agent = ResearchAgent()


def perform_research(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Convenience function for research."""
    return research_agent.search(query, max_results)