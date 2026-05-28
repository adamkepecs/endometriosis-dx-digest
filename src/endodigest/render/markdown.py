from __future__ import annotations

from pathlib import Path

from endodigest.models import ClassifiedItem


def write_markdown(markdown: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def build_fallback_markdown(
    classified_items: list[ClassifiedItem],
    *,
    start_date: str,
    end_date: str,
    source_counts: dict[str, int],
    queries_run: list[str],
) -> str:
    high_signal = [row for row in classified_items if row.classification.must_read or row.classification.relevance_score >= 75]
    papers = [row for row in classified_items if row.item.source_type == "paper"]
    trials = [row for row in classified_items if row.item.source_type == "clinical_trial"]
    regulatory = [
        row
        for row in classified_items
        if row.item.source_type == "regulatory"
        or row.classification.category in {"regulatory", "commercial_launch"}
    ]
    web = [
        row
        for row in classified_items
        if row.item.source_type == "web"
        and row not in regulatory
    ]
    lines = [
        f"# Endometriosis Diagnostics Weekly Digest: {start_date} to {end_date}",
        "",
        "This surveillance digest is informational and is not medical advice.",
        "",
        "## Executive summary",
    ]
    if classified_items:
        lines.extend(_executive_summary(classified_items))
    else:
        lines.append("- No included high-relevance items were found in this run. This may reflect a quiet window, missing API credentials, or network limits in the run environment.")
    lines.extend(["", "## High-signal updates"])
    lines.extend(_items_or_empty(high_signal))
    lines.extend(["", "## New papers"])
    lines.extend(_items_or_empty(papers))
    lines.extend(["", "## New or updated clinical trials"])
    lines.extend(_items_or_empty(trials))
    lines.extend(["", "## Regulatory / commercial / company updates"])
    lines.extend(_items_or_empty(regulatory))
    lines.extend(["", "## Conference / news / web signals"])
    lines.extend(_items_or_empty(web))
    lines.extend(["", "## Watchlist by modality"])
    lines.extend(_watchlist(classified_items))
    lines.extend(["", "## Skeptical read: what is strong, weak, uncertain"])
    lines.extend(_skeptical_read(classified_items))
    lines.extend(["", "## Items worth reading fully"])
    must_read = [row for row in classified_items if row.classification.must_read]
    lines.extend(_items_or_empty(must_read))
    lines.extend(["", "## Search appendix", "", "Source counts:"])
    lines.extend(f"- {source}: {count}" for source, count in sorted(source_counts.items()))
    lines.extend(["", "Queries run:"])
    lines.extend(f"- {query}" for query in queries_run)
    return "\n".join(lines).strip() + "\n"


def _executive_summary(items: list[ClassifiedItem]) -> list[str]:
    total = len(items)
    categories = sorted({row.classification.category for row in items})
    must_read = sum(1 for row in items if row.classification.must_read)
    commercial = sum(1 for row in items if row.classification.evidence_level in {"commercial_claim", "press_release"})
    return [
        f"- {total} item(s) met inclusion criteria after deduplication and relevance filtering.",
        f"- Main modalities/signals: {', '.join(categories[:8]) or 'none'}.",
        f"- {must_read} item(s) were marked worth reading fully based on relevance and source type.",
        f"- {commercial} item(s) are commercial or press-release level and should be read as claims until validated.",
    ]


def _items_or_empty(items: list[ClassifiedItem]) -> list[str]:
    if not items:
        return ["- No included items in this section."]
    return [_format_item(row) for row in items]


def _format_item(row: ClassifiedItem) -> str:
    item = row.item
    classification = row.classification
    title = item.title or item.stable_id
    link = f"[{title}]({item.url})" if item.url else title
    bits = [
        f"- {link}",
        f"({classification.category}; {classification.evidence_level}; relevance {classification.relevance_score})",
    ]
    if item.publication_date:
        bits.append(f"Date: {item.publication_date}.")
    if item.authors_or_org:
        bits.append(f"Source/org: {item.authors_or_org}.")
    if classification.key_claim:
        bits.append(f"Claim: {classification.key_claim}")
    metrics = _metric_text(classification)
    if metrics:
        bits.append(f"Reported performance: {metrics}.")
    if classification.skepticism_note:
        bits.append(f"Skeptical note: {classification.skepticism_note}")
    return " ".join(bits)


def _metric_text(classification) -> str:
    pieces = []
    for label, value in [
        ("sensitivity", classification.sensitivity),
        ("specificity", classification.specificity),
        ("AUC", classification.AUC),
        ("PPV", classification.PPV),
        ("NPV", classification.NPV),
    ]:
        if value:
            pieces.append(f"{label} {value}")
    return ", ".join(pieces)


def _watchlist(items: list[ClassifiedItem]) -> list[str]:
    if not items:
        return ["- No modality-specific watchlist entries this run."]
    grouped: dict[str, list[ClassifiedItem]] = {}
    for row in items:
        grouped.setdefault(row.classification.category, []).append(row)
    lines = []
    for category, rows in sorted(grouped.items()):
        strongest = max(rows, key=lambda row: row.classification.relevance_score)
        title = strongest.item.title or strongest.item.stable_id
        lines.append(f"- {category}: {len(rows)} signal(s); highest relevance: {title}.")
    return lines


def _skeptical_read(items: list[ClassifiedItem]) -> list[str]:
    if not items:
        return [
            "- Strong: no new claims to upgrade.",
            "- Weak: absence of included results is not evidence of absence; credential or network gaps may suppress collection.",
            "- Uncertain: run a credentialed backfill before interpreting trends.",
        ]
    peer_reviewed = sum(1 for row in items if row.classification.evidence_level.startswith("peer_reviewed"))
    registry = sum(1 for row in items if row.classification.evidence_level == "clinical_trial_registry")
    claims = sum(1 for row in items if row.classification.evidence_level in {"commercial_claim", "press_release"})
    return [
        f"- Stronger: {peer_reviewed} peer-reviewed item(s) may contain methods/performance details to inspect.",
        f"- Developing: {registry} registry item(s) indicate study activity but not diagnostic performance.",
        f"- Weak/uncertain: {claims} commercial or press-release item(s) need independent validation and clear reference-standard details.",
    ]
