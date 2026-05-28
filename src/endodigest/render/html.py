from __future__ import annotations

import html
import re
from pathlib import Path


def markdown_to_html(markdown: str) -> str:
    body: list[str] = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p>{_inline(line)}</p>")
    if in_list:
        body.append("</ul>")
    return _wrap("\n".join(body))


def write_html(markdown: str, path: Path) -> Path:
    html_text = markdown_to_html(markdown)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path


def markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", markdown)
    return text


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1))}</a>',
        escaped,
    )


def _wrap(body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.52; color: #1f2933; max-width: 880px; margin: 0 auto; padding: 28px; }}
    h1 {{ font-size: 26px; margin: 0 0 16px; color: #102a43; }}
    h2 {{ font-size: 19px; margin-top: 28px; color: #243b53; border-bottom: 1px solid #d9e2ec; padding-bottom: 6px; }}
    a {{ color: #0b5cad; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    li {{ margin: 8px 0; }}
    p {{ margin: 10px 0; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
