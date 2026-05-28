from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OpenAIAPIError(RuntimeError):
    """Raised when an OpenAI Responses API call fails."""


class ResponsesClient:
    def __init__(self, *, api_key: str, model: str, timeout: int = 60) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def create_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": self._input(prompt, system),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if tools:
            payload["tools"] = tools
        text = self._post_and_extract_text(payload)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OpenAIAPIError(f"OpenAI did not return valid JSON: {text[:500]}") from exc
        if not isinstance(data, dict):
            raise OpenAIAPIError("OpenAI JSON response was not an object")
        return data

    def create_text(self, *, prompt: str, system: str | None = None) -> str:
        payload = {"model": self.model, "input": self._input(prompt, system)}
        return self._post_and_extract_text(payload)

    def _input(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _post_and_extract_text(self, payload: dict[str, Any]) -> str:
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "endometriosis-dx-digest/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310 - official OpenAI API.
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(f"HTTP {exc.code}: {body[:1000]}") from exc
        except Exception as exc:  # noqa: BLE001 - callers fall back gracefully.
            raise OpenAIAPIError(str(exc)) from exc
        return extract_response_text(data)


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for output in data.get("output", []) or []:
        for content in output.get("content", []) or []:
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
            elif isinstance(content.get("output_text"), str):
                chunks.append(content["output_text"])
    text = "\n".join(chunk for chunk in chunks if chunk).strip()
    if not text:
        raise OpenAIAPIError("OpenAI response did not contain output text")
    return text
