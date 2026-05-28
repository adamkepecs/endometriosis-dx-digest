from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from endodigest.models import CollectorResult
from endodigest.utils.dates import iso_today, parse_date
from endodigest.utils.normalize import clean_text

LOGGER = logging.getLogger(__name__)
API_URL = "https://clinicaltrials.gov/api/v2/studies"

DEFAULT_QUERIES = [
    "endometriosis diagnosis",
    "endometriosis biomarker",
    "endometriosis saliva",
    "endometriosis blood test",
    "endometriosis menstrual blood",
    "endometriosis miRNA",
    "endometriosis imaging",
    "maraciclatide",
    "Endotest",
    "HerResolve",
    "PromarkerEndo",
]


def collect_clinical_trials(config: dict[str, Any], start_date: date, end_date: date) -> list[CollectorResult]:
    source_config = config.get("sources", {}).get("clinicaltrials", {})
    if not source_config.get("enabled", True):
        return []
    queries = source_config.get("queries") or DEFAULT_QUERIES
    max_results = int(source_config.get("max_results", 50))
    rate_limit = float(source_config.get("rate_limit_seconds", config.get("rate_limits", {}).get("clinicaltrials_seconds", 0.25)))
    results: list[CollectorResult] = []
    seen_nct: set[str] = set()
    for query in queries:
        try:
            for study in fetch_studies(query, max_results):
                item = study_to_collector(study)
                nct_id = item.raw.get("nct_id", "")
                if not nct_id or nct_id in seen_nct:
                    continue
                if _within_update_window(item.raw, start_date, end_date):
                    seen_nct.add(nct_id)
                    results.append(item)
            time.sleep(rate_limit)
        except Exception as exc:  # noqa: BLE001 - collectors must not kill the whole run.
            LOGGER.warning("ClinicalTrials.gov query failed for %r: %s", query, exc)
    return results


def fetch_studies(query: str, max_results: int) -> list[dict[str, Any]]:
    params = {
        "format": "json",
        "query.term": query,
        "pageSize": str(min(max_results, 100)),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "endometriosis-dx-digest/0.1"})
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - explicit public API.
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("studies", [])


def study_to_collector(study: dict[str, Any]) -> CollectorResult:
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    desc = protocol.get("descriptionModule", {})
    conditions = protocol.get("conditionsModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    contacts = protocol.get("contactsLocationsModule", {})

    nct_id = clean_text(ident.get("nctId"))
    title = clean_text(ident.get("briefTitle") or ident.get("officialTitle"))
    lead_sponsor = clean_text((sponsor_module.get("leadSponsor") or {}).get("name"))
    collaborators = [clean_text(item.get("name")) for item in sponsor_module.get("collaborators", []) if item.get("name")]
    interventions = [
        {
            "name": clean_text(item.get("name")),
            "type": clean_text(item.get("type")),
        }
        for item in arms.get("interventions", [])
    ]
    locations = []
    for loc in contacts.get("locations", []) or []:
        pieces = [loc.get("facility"), loc.get("city"), loc.get("state"), loc.get("country")]
        locations.append(clean_text(", ".join(str(piece) for piece in pieces if piece)))
    raw = {
        "nct_id": nct_id,
        "status": clean_text(status.get("overallStatus")),
        "brief_summary": clean_text(desc.get("briefSummary"), 4000),
        "interventions": interventions,
        "conditions": [clean_text(item) for item in conditions.get("conditions", [])],
        "lead_sponsor": lead_sponsor,
        "collaborators": collaborators,
        "start_date": _date_struct(status.get("startDateStruct")),
        "completion_date": _date_struct(status.get("completionDateStruct")),
        "last_update_submitted": clean_text(status.get("lastUpdateSubmitDate")),
        "last_update_posted": _date_struct(status.get("lastUpdatePostDateStruct")),
        "locations": locations[:20],
    }
    snippet = raw["brief_summary"]
    return CollectorResult(
        source_type="clinical_trial",
        source_name="ClinicalTrials.gov",
        stable_id=f"nct:{nct_id}" if nct_id else f"ctgov:{title}",
        title=title,
        url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
        publication_date=raw["last_update_posted"] or raw["last_update_submitted"],
        discovered_date=iso_today(),
        authors_or_org=", ".join([lead_sponsor, *collaborators[:5]]).strip(", "),
        abstract_or_snippet=snippet,
        raw=raw,
    )


def _date_struct(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    return clean_text(value.get("date") or value.get("year") or "")


def _within_update_window(raw: dict[str, Any], start_date: date, end_date: date) -> bool:
    candidates = [
        raw.get("last_update_submitted"),
        raw.get("last_update_posted"),
        raw.get("start_date"),
        raw.get("completion_date"),
    ]
    parsed = [parse_date(value) for value in candidates if value]
    parsed = [value for value in parsed if value]
    if not parsed:
        return True
    return any(start_date <= value <= end_date for value in parsed)
