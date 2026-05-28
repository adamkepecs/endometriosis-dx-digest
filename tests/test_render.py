from endodigest.llm.classify import heuristic_classification
from endodigest.models import ClassifiedItem, CollectorResult
from endodigest.render.html import markdown_to_html
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
