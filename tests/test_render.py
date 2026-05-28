from endodigest.llm.classify import heuristic_classification
from endodigest.models import ClassifiedItem, CollectorResult
from endodigest.render.html import markdown_to_html
from endodigest.render.google_doc import append_digest_to_google_doc
from endodigest.render.markdown import build_fallback_markdown


def test_markdown_and_html_keep_primary_links():
    source = CollectorResult(
        source_type="paper",
        source_name="PubMed",
        stable_id="pmid:38320163",
        title="Validation of a salivary miRNA signature of endometriosis",
        url="https://pubmed.ncbi.nlm.nih.gov/38320163/",
        publication_date="2024",
        discovered_date="2026-05-28",
        authors_or_org="Example",
        abstract_or_snippet="Endometriosis diagnostic saliva miRNA test with AUC 0.95.",
        raw={"pmid": "38320163"},
    )
    classified = ClassifiedItem(item=source, classification=heuristic_classification(source))
    markdown = build_fallback_markdown(
        [classified],
        start_date="2026-05-01",
        end_date="2026-05-28",
        source_counts={"pubmed": 1},
        queries_run=["pubmed: endometriosis diagnosis"],
    )
    html = markdown_to_html(markdown)
    assert "[Validation of a salivary miRNA signature of endometriosis](https://pubmed.ncbi.nlm.nih.gov/38320163/)" in markdown
    assert '<a href="https://pubmed.ncbi.nlm.nih.gov/38320163/">Validation of a salivary miRNA signature of endometriosis</a>' in html
    assert "not medical advice" in markdown.lower()


def test_empty_digest_renders_clear_summary():
    markdown = build_fallback_markdown(
        [],
        start_date="2026-05-01",
        end_date="2026-05-28",
        source_counts={"pubmed": 0},
        queries_run=[],
    )
    assert "No included high-relevance items" in markdown
    assert "Search appendix" in markdown


def test_google_doc_new_tab_targets_created_tab(monkeypatch):
    calls = []

    def fake_access_token(config):
        return "token"

    def fake_docs_request(method, url, token, body=None):
        calls.append({"method": method, "url": url, "body": body})
        if body and body["requests"][0].get("addDocumentTab"):
            return {
                "replies": [
                    {
                        "addDocumentTab": {
                            "tabProperties": {
                                "tabId": "tab-123",
                                "title": "Digest 2026-05-18 to 2026-05-28",
                            }
                        }
                    }
                ]
            }
        return {}

    monkeypatch.setattr("endodigest.render.google_doc._access_token", fake_access_token)
    monkeypatch.setattr("endodigest.render.google_doc._docs_request", fake_docs_request)

    config = {
        "secrets": {
            "google_doc_id": "doc-123",
            "google_service_account_json": '{"client_email":"test@example.iam.gserviceaccount.com"}',
        },
        "outputs": {
            "google_doc_write_mode": "new_tab",
            "google_doc_tab_title_template": "Digest {date_range}",
            "google_doc_new_tab_index": 0,
        },
    }
    result = append_digest_to_google_doc(
        config,
        "# Endometriosis Diagnostics Weekly Digest: 2026-05-18 to 2026-05-28\n\n"
        "[Primary source](https://example.org/paper)",
    )

    assert result.updated is True
    assert calls[0]["body"]["requests"][0]["addDocumentTab"]["tabProperties"] == {
        "title": "Digest 2026-05-18 to 2026-05-28",
        "index": 0,
    }
    requests = calls[1]["body"]["requests"]
    assert requests[0]["insertText"]["location"]["tabId"] == "tab-123"
    assert requests[1]["updateTextStyle"]["range"]["tabId"] == "tab-123"
