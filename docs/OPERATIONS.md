# Operations

## Manual Runs

Normal weekly-style run:

```bash
python -m endodigest.cli run --lookback-days 10
```

Dry run:

```bash
python -m endodigest.cli run --dry-run --lookback-days 30
```

Backfill:

```bash
python -m endodigest.cli run --backfill-days 730
```

Collect one source:

```bash
python -m endodigest.cli collect --source pubmed
python -m endodigest.cli collect --source clinicaltrials
```

## Change Recipient

Update the GitHub secret:

```text
DIGEST_TO
```

Do not hard-code recipient emails in the repository.

## Change Sender

Update:

```text
DIGEST_FROM
```

The address must be verified in SendGrid.

## Change Schedule

Edit `.github/workflows/weekly-digest.yml`.

The default schedule is Friday at 5:00 AM America/Chicago:

```yaml
schedule:
  - cron: "0 5 * * FRI"
    timezone: "America/Chicago"
```

## Reset Seen State

To rerun as if nothing has been seen, reset `data/seen.json` to:

```json
{
  "version": 1,
  "updated_at": null,
  "items": {}
}
```

Commit that change before the next scheduled run.

## Troubleshooting

`OPENAI_API_KEY` missing:

- Non-dry email runs require `OPENAI_API_KEY`.
- Dry runs and local tests use deterministic fallback classification/synthesis.

`SENDGRID_API_KEY`, `DIGEST_TO`, or `DIGEST_FROM` missing:

- The run saves rendered email HTML and text under `data/runs/`.
- The GitHub Action fails with a clear error.

Google Docs skipped:

- Confirm `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_DOC_ID`.
- Run `python -m endodigest.cli print-google-service-account-email`.
- Share the Google Doc with that email as Editor.

Optional web provider warnings:

- Missing Google CSE, SerpAPI, Tavily, or Brave keys are warnings only.
- OpenAI web search remains the default when `OPENAI_API_KEY` is present.

Too few items:

- Run a backfill.
- Check API credentials and GitHub Actions logs.
- Review `config/seed_queries.yml` and source-specific query lists.

Duplicate items:

- Deduplication uses PMID, DOI, NCT ID, canonical URL, and normalized title plus source.
- Inspect `data/seen.json` if an item should be allowed through again.
