# Google Doc Setup

Google Docs output is optional. If credentials or `GOOGLE_DOC_ID` are missing, the run continues and sends email, while marking Google Docs output as skipped.

## Steps

1. Create a Google Cloud project.
2. Enable **Google Docs API**.
3. Enable **Google Drive API**.
4. Create a service account.
5. Create a JSON key for that service account.
6. Add the full JSON as GitHub secret `GOOGLE_SERVICE_ACCOUNT_JSON`.
7. Add the target Google Doc ID as GitHub secret `GOOGLE_DOC_ID`.
8. Install the package locally and run:

```bash
python -m endodigest.cli print-google-service-account-email
```

9. Share the target Google Doc with the printed service-account email as **Editor**.

The service-account email will look like:

```text
endometriosis-dx-digest@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

## Finding The Google Doc ID

Use the ID in the document URL:

```text
https://docs.google.com/document/d/GOOGLE_DOC_ID/edit
```

## Append Mode

Set `outputs.google_doc_append_mode` in `config/config.example.yml` or your private `config/config.yml`:

```json
{
  "outputs": {
    "google_doc_append_mode": "top"
  }
}
```

Allowed values are `top` and `bottom`.
