from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from endodigest.config import get_secret, is_real_secret
from endodigest.render.html import markdown_to_plain_text


class EmailDeliveryError(RuntimeError):
    """Raised when SendGrid delivery cannot proceed."""


@dataclass(slots=True)
class EmailResult:
    sent: bool
    skipped: bool
    message: str


def subject_for(end_date: str, prefix: str = "Endometriosis diagnostics weekly digest") -> str:
    return f"{prefix} \u2014 {end_date}"


def send_digest_email(
    *,
    config: dict,
    subject: str,
    html: str,
    markdown: str,
    run_dir: Path,
) -> EmailResult:
    api_key = get_secret(config, "SENDGRID_API_KEY")
    digest_to = get_secret(config, "DIGEST_TO")
    digest_from = get_secret(config, "DIGEST_FROM")
    if not all(is_real_secret(value) for value in [api_key, digest_to, digest_from]):
        html_path = run_dir / "latest_email.html"
        text_path = run_dir / "latest_email.txt"
        html_path.write_text(html, encoding="utf-8")
        text_path.write_text(markdown_to_plain_text(markdown), encoding="utf-8")
        raise EmailDeliveryError(
            "SendGrid delivery requires SENDGRID_API_KEY, DIGEST_TO, and DIGEST_FROM. "
            f"Rendered email saved to {html_path}."
        )
    payload = {
        "personalizations": [{"to": [{"email": digest_to}]}],
        "from": {"email": digest_from},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": markdown_to_plain_text(markdown)},
            {"type": "text/html", "value": html},
        ],
    }
    request = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "endometriosis-dx-digest/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - SendGrid API.
            if response.status not in {200, 202}:
                raise EmailDeliveryError(f"SendGrid returned unexpected status {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise EmailDeliveryError(f"SendGrid HTTP {exc.code}: {body[:1000]}") from exc
    return EmailResult(sent=True, skipped=False, message="email sent")
