from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from endodigest.models import CollectorResult
from endodigest.utils.dates import utc_now


class SeenStore:
    def __init__(self, path: Path = Path("data/seen.json")) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "updated_at": None, "items": {}}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if "items" not in loaded:
            items = {}
            for record in loaded.get("seen", []):
                key = record.get("key")
                if key:
                    items[key] = record
            loaded = {"version": 1, "updated_at": loaded.get("updated_at"), "items": items}
        return loaded

    @property
    def items(self) -> dict:
        return self.data.setdefault("items", {})

    def has_seen(self, item: CollectorResult) -> bool:
        return any(key in self.items for key in item.dedupe_keys())

    def mark_seen(self, item: CollectorResult) -> None:
        record = {
            "stable_id": item.stable_id,
            "source_type": item.source_type,
            "source_name": item.source_name,
            "title": item.title,
            "url": item.url,
            "publication_date": item.publication_date,
            "first_seen_at": utc_now().isoformat(),
        }
        for key in item.dedupe_keys():
            self.items[key] = record

    def mark_many(self, items: Iterable[CollectorResult]) -> None:
        for item in items:
            self.mark_seen(item)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = utc_now().isoformat()
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dedupe_collector_results(items: Iterable[CollectorResult], seen: SeenStore | None = None) -> list[CollectorResult]:
    output: list[CollectorResult] = []
    local_keys: set[str] = set()
    for item in items:
        keys = set(item.dedupe_keys())
        if not keys:
            keys = {f"stable:{item.source_name}:{item.stable_id}:{item.title}"}
        if local_keys.intersection(keys):
            continue
        if seen and seen.has_seen(item):
            continue
        local_keys.update(keys)
        output.append(item)
    return output
