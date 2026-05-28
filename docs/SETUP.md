# Setup

## 1. Create The Private Repository

Create a private GitHub repository named `endometriosis-dx-digest`, then push this project to it.

```bash
git init
git branch -M main
git remote add origin git@github.com:OWNER/endometriosis-dx-digest.git
git add .
git commit -m "Initial endometriosis diagnostics digest"
git push -u origin main
```

## 2. Add GitHub Secrets

Go to **GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret**.

Required and optional secrets are documented exactly below:

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

Email-only operation requires:

```text
OPENAI_API_KEY
SENDGRID_API_KEY
DIGEST_TO
DIGEST_FROM
```

Google Docs output also requires:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_DOC_ID
```

`NCBI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_CSE_ID`, `SERPAPI_API_KEY`, `TAVILY_API_KEY`, and `BRAVE_SEARCH_API_KEY` are optional by default.

## 3. Validate Locally

```bash
python -m pip install -e ".[dev]"
python -m endodigest.cli validate-config
pytest
python -m endodigest.cli run --dry-run --lookback-days 30
```

## 4. First Backfill

After secrets are set:

```bash
python -m endodigest.cli run --dry-run --backfill-days 730
```

Then use GitHub Actions `workflow_dispatch` with `backfill_days=730`. Later scheduled runs use the default 10-day lookback.
