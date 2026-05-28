from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from endodigest.config import get_secret, is_real_secret

LOGGER = logging.getLogger(__name__)
DOCS_BASE = "https://docs.googleapis.com/v1/documents"
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


@dataclass(slots=True)
class GoogleDocResult:
    updated: bool
    skipped: bool
    message: str


def print_service_account_email(config: dict[str, Any]) -> str:
    info = _service_account_info(config)
    email = info.get("client_email")
    if not email:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON does not contain client_email")
    return str(email)


def append_digest_to_google_doc(config: dict[str, Any], markdown: str) -> GoogleDocResult:
    doc_id = get_secret(config, "GOOGLE_DOC_ID")
    service_account_json = get_secret(config, "GOOGLE_SERVICE_ACCOUNT_JSON")
    if not (is_real_secret(doc_id) and is_real_secret(service_account_json)):
        return GoogleDocResult(
            updated=False,
            skipped=True,
            message="Google Docs output skipped: GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_DOC_ID is missing",
        )
    try:
        token = _access_token(config)
        document = _docs_request("GET", f"{DOCS_BASE}/{doc_id}", token)
        end_index = document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
        append_mode = config.get("outputs", {}).get("google_doc_append_mode", "top")
        insertion_index = 1 if append_mode == "top" else max(1, int(end_index) - 1)
        plain_text, links = _markdown_to_doc_text(markdown)
        if append_mode == "top":
            plain_text = plain_text.rstrip() + "\n\n"
        else:
            plain_text = "\n\n" + plain_text.rstrip() + "\n"
        requests: list[dict[str, Any]] = [
            {"insertText": {"location": {"index": insertion_index}, "text": plain_text}}
        ]
        for start_offset, end_offset, url in links:
            start = insertion_index + start_offset
            end = insertion_index + end_offset
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"link": {"url": url}},
                        "fields": "link",
                    }
                }
            )
        _docs_request("POST", f"{DOCS_BASE}/{doc_id}:batchUpdate", token, {"requests": requests})
        return GoogleDocResult(updated=True, skipped=False, message="Google Doc updated")
    except Exception as exc:  # noqa: BLE001 - Google Docs should not block email.
        LOGGER.warning("Google Docs update skipped after error: %s", exc)
        return GoogleDocResult(updated=False, skipped=True, message=f"Google Docs skipped after error: {exc}")


def _service_account_info(config: dict[str, Any]) -> dict[str, Any]:
    raw = get_secret(config, "GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw.strip().startswith("{"):
        return json.loads(raw)
    with open(raw, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _access_token(config: dict[str, Any]) -> str:
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:
        raise RuntimeError("google-auth is required for Google Docs output") from exc
    credentials = service_account.Credentials.from_service_account_info(
        _service_account_info(config),
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return str(credentials.token)


def _docs_request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "endometriosis-dx-digest/0.1",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - Google Docs API.
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Docs HTTP {exc.code}: {body[:1000]}") from exc
    return json.loads(raw) if raw else {}


def _markdown_to_doc_text(markdown: str) -> tuple[str, list[tuple[int, int, str]]]:
    links: list[tuple[int, int, str]] = []
    output: list[str] = []
    position = 0
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    for line in markdown.splitlines():
        if line.startswith("# "):
            line = line[2:].upper()
        elif line.startswith("## "):
            line = line[3:].upper()
        rendered = ""
        last = 0
        for match in pattern.finditer(line):
            rendered += line[last : match.start()]
            label = match.group(1)
            start = position + len(rendered)
            rendered += label
            end = position + len(rendered)
            links.append((start, end, match.group(2)))
            last = match.end()
        rendered += line[last:]
        output.append(rendered)
        position += len(rendered) + 1
    return "\n".join(output), links
