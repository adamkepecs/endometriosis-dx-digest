from __future__ import annotations

import json
import logging
from typing import Any

from endodigest.config import get_secret, is_real_secret
from endodigest.llm.openai_client import OpenAIAPIError, ResponsesClient
from endodigest.models import ClassifiedItem
from endodigest.render.markdown import build_fallback_markdown

LOGGER = logging.getLogger(__name__)


def synthesize_digest(
    classified_items: list[ClassifiedItem],
    *,
    config: dict[str, Any],
    start_date: str,
    end_date: str,
    source_counts: dict[str, int],
    queries_run: list[str],
    dry_run: bool = False,
) -> tuple[str, str]:
    api_key = get_secret(config, "OPENAI_API_KEY")
    if dry_run or not is_real_secret(api_key):
        return (
            build_fallback_markdown(
                classified_items,
                start_date=start_date,
                end_date=end_date,
                source_counts=source_counts,
                queries_run=queries_run,
            ),
            "fallback",
        )
    client = ResponsesClient(
        api_key=api_key,
        model=str(config.get("llm", {}).get("synthesis_model", config.get("llm", {}).get("model", "gpt-4.1-mini"))),
        timeout=int(config.get("llm", {}).get("request_timeout_seconds", 60)),
    )
    system = _prompt_text("system.md")
    instructions = _prompt_text("synthesize_digest.md")
    payload = {
        "date_range": {"start": start_date, "end": end_date},
        "items": [item.to_dict() for item in classified_items],
        "source_counts": source_counts,
        "queries_run": queries_run,
    }
    prompt = f"{instructions}\n\nDigest source JSON:\n{json.dumps(payload, indent=2, sort_keys=True)}"
    try:
        markdown = client.create_text(prompt=prompt, system=system)
        if "Search appendix" not in markdown:
            markdown += "\n\n" + _appendix(source_counts, queries_run)
        return markdown.strip() + "\n", "llm"
    except OpenAIAPIError as exc:
        LOGGER.warning("LLM synthesis failed; using fallback markdown: %s", exc)
        return (
            build_fallback_markdown(
                classified_items,
                start_date=start_date,
                end_date=end_date,
                source_counts=source_counts,
                queries_run=queries_run,
            ),
            "fallback_after_llm_error",
        )


def _prompt_text(name: str) -> str:
    from pathlib import Path

    path = Path("prompts") / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _appendix(source_counts: dict[str, int], queries_run: list[str]) -> str:
    lines = ["## Search appendix", "", "Source counts:"]
    lines.extend(f"- {source}: {count}" for source, count in sorted(source_counts.items()))
    lines.append("")
    lines.append("Queries run:")
    lines.extend(f"- {query}" for query in queries_run)
    return "\n".join(lines)
