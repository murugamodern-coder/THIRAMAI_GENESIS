import json
import urllib.parse
import urllib.request
from typing import Any


def search_web(query: str, limit: int = 5) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote_plus(query)
    url = (
        "https://api.duckduckgo.com/"
        f"?q={encoded}&format=json&no_html=1&skip_disambig=1"
    )
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results: list[dict[str, Any]] = []
    abstract = payload.get("AbstractText", "").strip()
    abstract_url = payload.get("AbstractURL", "").strip()
    if abstract:
        results.append(
            {
                "title": payload.get("Heading", "DuckDuckGo Abstract"),
                "snippet": abstract,
                "url": abstract_url,
            }
        )

    for item in payload.get("RelatedTopics", []):
        if isinstance(item, dict) and "Text" in item:
            results.append(
                {
                    "title": item.get("FirstURL", "Related Topic"),
                    "snippet": item.get("Text", ""),
                    "url": item.get("FirstURL", ""),
                }
            )
        if len(results) >= limit:
            break

    return results[:limit]
