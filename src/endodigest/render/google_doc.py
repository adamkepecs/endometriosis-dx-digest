from __future__ import annotations

import json
import logging
import re
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
        write_mode = config.get("outputs", {}).get("google_doc_write_mode", "append")
        if write_mode == "new_tab":
            tab_title = _tab_title_from_markdown(config, markdown)
            tab_id = _create_document_tab(config, doc_id, token, tab_title)
            _insert_markdown(doc_id, token, markdown.rstrip() + "\n", 1, tab_id=tab_id)
            return GoogleDocResult(
                updated=True,
                skipped=False,
                message=f"Google Doc tab created: {tab_title}",
            )
        document = _docs_request("GET", f"{DOCS_BASE}/{doc_id}", token)
        end_index = document.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
        append_mode = config.get("outputs", {}).get("google_doc_append_mode", "top")
        insertion_index = 1 if append_mode == "top" else max(1, int(end_index) - 1)
        if append_mode == "top":
            body = markdown.rstrip() + "\n\n"
        else:
            body = "\n\n" + markdown.rstrip() + "\n"
        _insert_markdown(doc_id, token, body, insertion_index)
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
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise RuntimeError("requests is required for Google Docs output") from exc
    response = requests.request(
        method,
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "endometriosis-dx-digest/0.1",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Google Docs HTTP {response.status_code}: {response.text[:1000]}")
    return response.json() if response.text else {}


def _create_document_tab(config: dict[str, Any], doc_id: str, token: str, title: str) -> str:
    tab_properties: dict[str, Any] = {"title": title}
    tab_index = config.get("outputs", {}).get("google_doc_new_tab_index")
    if tab_index is not None:
        tab_properties["index"] = int(tab_index)
    response = _docs_request(
        "POST",
        f"{DOCS_BASE}/{doc_id}:batchUpdate",
        token,
        {"requests": [{"addDocumentTab": {"tabProperties": tab_properties}}]},
    )
    replies = response.get("replies", [])
    tab_properties = (
        replies[0].get("addDocumentTab", {}).get("tabProperties", {}) if replies else {}
    )
    tab_id = tab_properties.get("tabId")
    if not tab_id:
        raise RuntimeError("Google Docs did not return a tab ID after addDocumentTab")
    return str(tab_id)


def _insert_markdown(
    doc_id: str,
    token: str,
    markdown: str,
    insertion_index: int,
    *,
    tab_id: str | None = None,
) -> None:
    plain_text, links = _markdown_to_doc_text(markdown)
    location: dict[str, Any] = {"index": insertion_index}
    if tab_id:
        location["tabId"] = tab_id
    requests: list[dict[str, Any]] = [
        {"insertText": {"location": location, "text": plain_text}}
    ]
    for start_offset, end_offset, url in links:
        text_range: dict[str, Any] = {
            "startIndex": insertion_index + start_offset,
            "endIndex": insertion_index + end_offset,
        }
        if tab_id:
            text_range["tabId"] = tab_id
        requests.append(
            {
                "updateTextStyle": {
                    "range": text_range,
                    "textStyle": {"link": {"url": url}},
                    "fields": "link",
                }
            }
        )
    _docs_request("POST", f"{DOCS_BASE}/{doc_id}:batchUpdate", token, {"requests": requests})


def _tab_title_from_markdown(config: dict[str, Any], markdown: str) -> str:
    first_heading = next(
        (line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")),
        "Digest",
    )
    match = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+to\s+(\d{4}-\d{2}-\d{2}))?", first_heading)
    date_range = " to ".join(part for part in match.groups() if part) if match else ""
    template = config.get("outputs", {}).get(
        "google_doc_tab_title_template",
        "Digest {date_range}",
    )
    title = str(template).format(date_range=date_range or first_heading, heading=first_heading)
    return title.strip()[:100] or "Digest"


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
