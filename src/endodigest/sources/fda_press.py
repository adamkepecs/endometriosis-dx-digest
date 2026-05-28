from __future__ import annotations

from datetime import date
from typing import Any

from endodigest.sources.web_search import SearchProviderManager

DEFAULT_QUERIES = [
    "site:fda.gov endometriosis diagnostic test",
    "site:fda.gov endometriosis biomarker diagnostic",
    "endometriosis diagnostic FDA clearance",
    "endometriosis diagnostic test launch PRNewswire",
    "endometriosis diagnostic BusinessWire",
    "endometriosis diagnostic GlobeNewswire",
    "Ziwig Endotest endometriosis diagnostic",
    "HerResolve endometriosis diagnostic",
    "PromarkerEndo endometriosis diagnostic",
    "99mTc-maraciclatide FDA Fast Track endometriosis",
    "medical device news endometriosis diagnostic",
    "specialty clinical news endometriosis diagnostic",
]


def collect_fda_press(config: dict[str, Any], start_date: date, end_date: date):
    source_config = config.get("sources", {}).get("fda_press", {})
    if not source_config.get("enabled", True):
        return []
    queries = source_config.get("queries") or DEFAULT_QUERIES
    manager = SearchProviderManager(config)
    return manager.search_many(
        queries,
        start_date,
        end_date,
        source_type="regulatory",
        source_name="FDA/regulatory/commercial",
    )
