# endometriosis-dx-digest

Private weekly surveillance automation for endometriosis diagnostic tests.

The digest collects new papers, clinical-trial updates, regulatory/commercial signals, and web/news items; classifies relevance with the OpenAI Responses API using a strict JSON schema; synthesizes a skeptical scientific digest; writes it to a Google Doc when configured; and emails HTML plus plain text through SendGrid.

This is an informational surveillance tool for research use. It is not medical advice.

## Quick Start

```bash
python -m pip install -e ".[dev]"
python -m endodigest.cli validate-config
python -m endodigest.cli run --dry-run --lookback-days 30
```

Dry runs always skip SendGrid and Google Docs delivery and write local artifacts under `data/runs/`.

Useful commands:

```bash
python -m endodigest.cli run
python -m endodigest.cli run --lookback-days 10
python -m endodigest.cli run --backfill-days 730
python -m endodigest.cli run --dry-run
python -m endodigest.cli collect --source pubmed
python -m endodigest.cli collect --source clinicaltrials
python -m endodigest.cli print-google-service-account-email
python -m endodigest.cli validate-config
```

## Required Secrets

Add these in GitHub: **Settings -> Secrets and variables -> Actions -> New repository secret**.

```text
OPENAI_API_KEY
SENDGRID_API_KEY
DIGEST_TO
DIGEST_FROM
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_DOC_ID
NCBI_API_KEY
GOOGLE_API_KEY
GOOGLE_CSE_ID
SERPAPI_API_KEY
TAVILY_API_KEY
BRAVE_SEARCH_API_KEY
```

Only `OPENAI_API_KEY`, `SENDGRID_API_KEY`, `DIGEST_TO`, and `DIGEST_FROM` are strictly required for email-only operation. Google Docs requires `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_DOC_ID`. NCBI and web-search provider keys are optional unless you configure a provider as required.

## Schedule

The GitHub Actions workflow runs every Friday at 5:00 AM America/Chicago and also supports `workflow_dispatch` manual runs with `lookback_days`, `backfill_days`, `dry_run`, `send_email`, and `update_google_doc` inputs.

## Sources

- PubMed via NCBI E-utilities.
- ClinicalTrials.gov API v2.
- OpenAI Responses API web search by default.
- Optional Google Programmable Search, SerpAPI, Tavily, and Brave Search when keys are present.
- FDA/regulatory/commercial query set using the configured web-search providers.

Missing optional keys log warnings and do not crash the run.

## Output

Each run writes Markdown, HTML, and metadata under `data/runs/`. Google Docs output creates a new tab per digest by default; set `outputs.google_doc_write_mode` to `append` for one continuous document. Successful non-dry runs update `data/seen.json` so later runs suppress duplicates by PMID, DOI, NCT ID, canonical URL, and normalized title plus source.

See:

- [docs/SETUP.md](docs/SETUP.md)
- [docs/GOOGLE_DOC_SETUP.md](docs/GOOGLE_DOC_SETUP.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
