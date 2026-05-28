from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

from endodigest.config import get_secret, is_real_secret
from endodigest.models import CollectorResult
from endodigest.utils.dates import iso_today, pubmed_date
from endodigest.utils.normalize import clean_text

LOGGER = logging.getLogger(__name__)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

DEFAULT_QUERY = (
    "(endometriosis[Title/Abstract]) AND "
    "(diagnos*[Title/Abstract] OR biomarker*[Title/Abstract] OR assay[Title/Abstract] "
    "OR test[Title/Abstract] OR imaging[Title/Abstract] OR ultrasound[Title/Abstract] "
    "OR MRI[Title/Abstract] OR radiotracer[Title/Abstract] OR saliva[Title/Abstract] "
    "OR blood[Title/Abstract] OR urine[Title/Abstract] OR menstrual[Title/Abstract] "
    "OR microRNA[Title/Abstract] OR miRNA[Title/Abstract])"
)


def collect_pubmed(config: dict[str, Any], start_date: date, end_date: date) -> list[CollectorResult]:
    source_config = config.get("sources", {}).get("pubmed", {})
    if not source_config.get("enabled", True):
        return []
    queries = source_config.get("queries") or [DEFAULT_QUERY]
    max_results = int(source_config.get("max_results", 50))
    rate_limit = float(source_config.get("rate_limit_seconds", config.get("rate_limits", {}).get("pubmed_seconds", 0.34)))
    api_key = get_secret(config, "NCBI_API_KEY")
    all_results: list[CollectorResult] = []
    seen_pmids: set[str] = set()
    for query in queries:
        try:
            pmids = esearch(query, start_date, end_date, max_results, api_key)
            time.sleep(rate_limit)
            if not pmids:
                continue
            for item in efetch(pmids, api_key):
                pmid = str(item.get("pmid", ""))
                if not pmid or pmid in seen_pmids:
                    continue
                seen_pmids.add(pmid)
                all_results.append(pubmed_item_to_collector(item))
            time.sleep(rate_limit)
        except Exception as exc:  # noqa: BLE001 - collectors must not kill the whole run.
            LOGGER.warning("PubMed query failed for %r: %s", query, exc)
    return all_results


def esearch(query: str, start_date: date, end_date: date, max_results: int, api_key: str = "") -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(max_results),
        "sort": "pub date",
        "datetype": "pdat",
        "mindate": pubmed_date(start_date),
        "maxdate": pubmed_date(end_date),
    }
    if is_real_secret(api_key):
        params["api_key"] = api_key
    url = f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    payload = _get_json(url)
    return [str(pmid) for pmid in payload.get("esearchresult", {}).get("idlist", [])]


def efetch(pmids: list[str], api_key: str = "") -> list[dict[str, Any]]:
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if is_real_secret(api_key):
        params["api_key"] = api_key
    url = f"{EUTILS}/efetch.fcgi?{urllib.parse.urlencode(params)}"
    root = _get_xml(url)
    return [_parse_article(article) for article in root.findall(".//PubmedArticle")]


def pubmed_item_to_collector(item: dict[str, Any]) -> CollectorResult:
    pmid = str(item.get("pmid") or "")
    doi = str(item.get("doi") or "")
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
    if doi:
        item["doi_url"] = f"https://doi.org/{doi}"
    return CollectorResult(
        source_type="paper",
        source_name="PubMed",
        stable_id=f"pmid:{pmid}" if pmid else f"pubmed:{item.get('title', '')}",
        title=clean_text(item.get("title")),
        url=url,
        publication_date=clean_text(item.get("publication_date")),
        discovered_date=iso_today(),
        authors_or_org=", ".join(item.get("authors", [])[:8]),
        abstract_or_snippet=clean_text(item.get("abstract"), 4000),
        raw=item,
    )


def _parse_article(article: ET.Element) -> dict[str, Any]:
    pmid = _text(article.find(".//PMID"))
    medline = article.find("MedlineCitation")
    article_node = medline.find("Article") if medline is not None else None
    title = _text(article_node.find("ArticleTitle")) if article_node is not None else ""
    abstract_parts = []
    for node in article.findall(".//Abstract/AbstractText"):
        label = node.attrib.get("Label")
        text = "".join(node.itertext()).strip()
        if label:
            abstract_parts.append(f"{label}: {text}")
        elif text:
            abstract_parts.append(text)
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = _text(author.find("LastName"))
        initials = _text(author.find("Initials"))
        name = " ".join(part for part in [last, initials] if part)
        if name:
            authors.append(name)
    doi = ""
    for node in article.findall(".//ArticleIdList/ArticleId"):
        if node.attrib.get("IdType") == "doi":
            doi = _text(node)
            break
    journal = _text(article.find(".//Journal/Title"))
    pub_date = _publication_date(article)
    return {
        "pmid": pmid,
        "doi": doi,
        "journal": journal,
        "publication_date": pub_date,
        "title": title,
        "abstract": "\n".join(abstract_parts),
        "authors": authors,
    }


def _publication_date(article: ET.Element) -> str:
    pub_date = article.find(".//JournalIssue/PubDate")
    if pub_date is None:
        return ""
    year = _text(pub_date.find("Year"))
    month = _text(pub_date.find("Month"))
    day = _text(pub_date.find("Day"))
    medline = _text(pub_date.find("MedlineDate"))
    if year:
        parts = [year]
        if month:
            parts.append(month)
        if day:
            parts.append(day)
        return " ".join(parts)
    return medline


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return clean_text(node.text)


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "endometriosis-dx-digest/0.1"})
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - explicit public APIs.
        return json.loads(response.read().decode("utf-8"))


def _get_xml(url: str) -> ET.Element:
    req = urllib.request.Request(url, headers={"User-Agent": "endometriosis-dx-digest/0.1"})
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - explicit public APIs.
        return ET.fromstring(response.read())
