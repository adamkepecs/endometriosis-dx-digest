from pathlib import Path

from endodigest.models import CollectorResult
from endodigest.state import SeenStore, dedupe_collector_results


def item(**overrides):
    base = {
        "source_type": "paper",
        "source_name": "PubMed",
        "stable_id": "pmid:1",
        "title": "A diagnostic biomarker for endometriosis",
        "url": "https://pubmed.ncbi.nlm.nih.gov/1/?utm_source=test",
        "publication_date": "2026-01-01",
        "discovered_date": "2026-01-02",
        "authors_or_org": "Example",
        "abstract_or_snippet": "Endometriosis diagnostic biomarker.",
        "raw": {"pmid": "1", "doi": "10.1/example"},
    }
    base.update(overrides)
    return CollectorResult(**base)


def test_dedupe_by_pmid_and_doi():
    first = item(stable_id="pmid:1")
    duplicate = item(stable_id="pmid:2", raw={"pmid": "1", "doi": "10.1/example"})
    assert dedupe_collector_results([first, duplicate]) == [first]


def test_seen_store_suppresses_known_item(tmp_path: Path):
    store = SeenStore(tmp_path / "seen.json")
    first = item()
    store.mark_seen(first)
    store.save()
    reloaded = SeenStore(tmp_path / "seen.json")
    assert reloaded.has_seen(item(url="https://pubmed.ncbi.nlm.nih.gov/1/"))


def test_title_source_dedupe():
    first = item(raw={}, stable_id="web:a", url="", title="Endometriosis Diagnostic Test!")
    duplicate = item(raw={}, stable_id="web:b", url="", title="endometriosis diagnostic test")
    assert dedupe_collector_results([first, duplicate]) == [first]
