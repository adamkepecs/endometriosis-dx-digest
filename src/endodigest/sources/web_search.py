from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from endodigest.config import get_secret, is_real_secret
from endodigest.llm.openai_client import OpenAIAPIError, ResponsesClient
from endodigest.models import CollectorResult
from endodigest.utils.dates import iso_today
from endodigest.utils.normalize import canonicalize_url, clean_text, stable_hash

LOGGER = logging.getLogger(__name__)


def collect_web_search(config: dict[str, Any], start_date: date, end_date: date) -> list[CollectorResult]:
    source_config = config.get("sources", {}).get("web_search", {})
    if not source_config.get("enabled", True):
        return []
    queries = source_config.get("queries") or []
    manager = SearchProviderManager(config)
    return manager.search_many(queries, start_date, end_date, source_type="web", source_name="Web search")


class SearchProviderManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.web_config = config.get("sources", {}).get("web_search", {})
        self._warned_missing: set[str] = set()

    def search_many(
        self,
        queries: list[str],
        start_date: date,
        end_date: date,
        *,
        source_type: str,
        source_name: str,
    ) -> list[CollectorResult]:
        all_items: list[CollectorResult] = []
        seen_urls: set[str] = set()
        for query in queries:
            for item in self.search(query, start_date, end_date, source_type=source_type, source_name=source_name):
                url = canonicalize_url(item.url)
                key = url or item.stable_id
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                all_items.append(item)
        return all_items

    def search(
        self,
        query: str,
        start_date: date,
        end_date: date,
        *,
        source_type: str = "web",
        source_name: str = "Web search",
    ) -> list[CollectorResult]:
        results: list[CollectorResult] = []
        max_results = int(self.web_config.get("max_results", 8))
        if self.web_config.get("openai_web_search_enabled", True):
            results.extend(self._openai_search(query, start_date, end_date, max_results, source_type, source_name))
        optional = self.web_config.get("optional_providers", {})
        if optional.get("google_cse", True):
            results.extend(self._google_cse(query, max_results, source_type))
        if optional.get("serpapi", True):
            results.extend(self._serpapi(query, max_results, source_type))
        if optional.get("tavily", True):
            results.extend(self._tavily(query, max_results, source_type))
        if optional.get("brave", True):
            results.extend(self._brave(query, max_results, source_type))
        return results

    def _openai_search(
        self,
        query: str,
        start_date: date,
        end_date: date,
        max_results: int,
        source_type: str,
        source_name: str,
    ) -> list[CollectorResult]:
        api_key = get_secret(self.config, "OPENAI_API_KEY")
        if not is_real_secret(api_key):
            self._warn_once("openai", "OpenAI web search skipped: OPENAI_API_KEY is missing")
            return []
        client = ResponsesClient(
            api_key=api_key,
            model=str(self.config.get("llm", {}).get("model", "gpt-4.1-mini")),
            timeout=int(self.config.get("llm", {}).get("request_timeout_seconds", 60)),
        )
        schema = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "publication_date": {"type": "string"},
                            "source": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                        "required": ["title", "url", "publication_date", "source", "snippet"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        }
        prompt = (
            "Search for recent endometriosis diagnostic test, biomarker, imaging, regulatory, "
            f"or commercial updates for this query: {query!r}. Date window: {start_date} to {end_date}. "
            f"Return at most {max_results} primary-source or high-quality results with URLs."
        )
        try:
            payload = client.create_json(
                prompt=prompt,
                schema=schema,
                schema_name="web_search_results",
                tools=[{"type": self.web_config.get("openai_web_search_tool_type", "web_search_preview")}],
            )
        except OpenAIAPIError as exc:
            LOGGER.warning("OpenAI web search failed for %r: %s", query, exc)
            return []
        return [
            _web_result_to_collector(row, source_type, f"{source_name} / OpenAI", query)
            for row in payload.get("results", [])[:max_results]
        ]

    def _google_cse(self, query: str, max_results: int, source_type: str) -> list[CollectorResult]:
        api_key = get_secret(self.config, "GOOGLE_API_KEY")
        cse_id = get_secret(self.config, "GOOGLE_CSE_ID")
        if not (is_real_secret(api_key) and is_real_secret(cse_id)):
            self._warn_once("google_cse", "Google CSE skipped: GOOGLE_API_KEY or GOOGLE_CSE_ID is missing")
            return []
        params = {"key": api_key, "cx": cse_id, "q": query, "num": str(min(max_results, 10))}
        payload = _http_json(f"https://www.googleapis.com/customsearch/v1?{urllib.parse.urlencode(params)}")
        return [
            _web_result_to_collector(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "publication_date": "",
                    "source": item.get("displayLink", "Google CSE"),
                    "snippet": item.get("snippet", ""),
                },
                source_type,
                "Web search / Google CSE",
                query,
            )
            for item in payload.get("items", [])
        ]

    def _serpapi(self, query: str, max_results: int, source_type: str) -> list[CollectorResult]:
        api_key = get_secret(self.config, "SERPAPI_API_KEY")
        if not is_real_secret(api_key):
            self._warn_once("serpapi", "SerpAPI skipped: SERPAPI_API_KEY is missing")
            return []
        params = {"engine": "google", "q": query, "api_key": api_key, "num": str(max_results)}
        payload = _http_json(f"https://serpapi.com/search.json?{urllib.parse.urlencode(params)}")
        return [
            _web_result_to_collector(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "publication_date": item.get("date", ""),
                    "source": item.get("source", "SerpAPI"),
                    "snippet": item.get("snippet", ""),
                },
                source_type,
                "Web search / SerpAPI",
                query,
            )
            for item in payload.get("organic_results", [])[:max_results]
        ]

    def _tavily(self, query: str, max_results: int, source_type: str) -> list[CollectorResult]:
        api_key = get_secret(self.config, "TAVILY_API_KEY")
        if not is_real_secret(api_key):
            self._warn_once("tavily", "Tavily skipped: TAVILY_API_KEY is missing")
            return []
        payload = _http_json(
            "https://api.tavily.com/search",
            method="POST",
            body={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
            },
        )
        return [
            _web_result_to_collector(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "publication_date": item.get("published_date", ""),
                    "source": "Tavily",
                    "snippet": item.get("content", ""),
                },
                source_type,
                "Web search / Tavily",
                query,
            )
            for item in payload.get("results", [])[:max_results]
        ]

    def _brave(self, query: str, max_results: int, source_type: str) -> list[CollectorResult]:
        api_key = get_secret(self.config, "BRAVE_SEARCH_API_KEY")
        if not is_real_secret(api_key):
            self._warn_once("brave", "Brave Search skipped: BRAVE_SEARCH_API_KEY is missing")
            return []
        params = {"q": query, "count": str(min(max_results, 20))}
        payload = _http_json(
            f"https://api.search.brave.com/res/v1/web/search?{urllib.parse.urlencode(params)}",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        return [
            _web_result_to_collector(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "publication_date": item.get("age", ""),
                    "source": "Brave Search",
                    "snippet": item.get("description", ""),
                },
                source_type,
                "Web search / Brave",
                query,
            )
            for item in payload.get("web", {}).get("results", [])[:max_results]
        ]

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned_missing:
            self._warned_missing.add(key)
            LOGGER.warning(message)


def _web_result_to_collector(row: dict[str, Any], source_type: str, source_name: str, query: str) -> CollectorResult:
    url = clean_text(row.get("url"))
    title = clean_text(row.get("title"))
    return CollectorResult(
        source_type=source_type,
        source_name=source_name,
        stable_id=f"web:{stable_hash(canonicalize_url(url), title)}",
        title=title,
        url=url,
        publication_date=clean_text(row.get("publication_date")),
        discovered_date=iso_today(),
        authors_or_org=clean_text(row.get("source")),
        abstract_or_snippet=clean_text(row.get("snippet"), 2000),
        raw={"query": query, "provider": source_name, **row},
    )


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None
    req_headers = {"User-Agent": "endometriosis-dx-digest/0.1", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - configured API providers.
        return json.loads(response.read().decode("utf-8"))
