from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config/config.example.yml")
DEFAULT_SEED_PATH = Path("config/seed_queries.yml")

SECRET_ENV_NAMES = [
    "OPENAI_API_KEY",
    "SENDGRID_API_KEY",
    "DIGEST_TO",
    "DIGEST_FROM",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_DOC_ID",
    "NCBI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CSE_ID",
    "SERPAPI_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_SEARCH_API_KEY",
]


def load_yamlish(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"{path} is not JSON-compatible YAML and PyYAML is not installed"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


def load_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        env_path = os.environ.get("ENDODIGEST_CONFIG")
        path = Path(env_path) if env_path else (Path("config/config.yml") if Path("config/config.yml").exists() else DEFAULT_CONFIG_PATH)
    config = load_yamlish(path)
    apply_env_overrides(config)
    config["_config_path"] = str(path)
    return config


def load_seed_queries(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_SEED_PATH
    if not path.exists():
        return {}
    return load_yamlish(path)


def apply_env_overrides(config: dict[str, Any]) -> None:
    config.setdefault("secrets", {})
    for env_name in SECRET_ENV_NAMES:
        value = os.environ.get(env_name)
        if value:
            config["secrets"][env_name.lower()] = value
    if os.environ.get("ENDODIGEST_LLM_MODEL"):
        config.setdefault("llm", {})["model"] = os.environ["ENDODIGEST_LLM_MODEL"]
    if os.environ.get("ENDODIGEST_SYNTHESIS_MODEL"):
        config.setdefault("llm", {})["synthesis_model"] = os.environ["ENDODIGEST_SYNTHESIS_MODEL"]
    if os.environ.get("ENDODIGEST_RECIPIENT_LABEL"):
        config.setdefault("digest", {})["recipient_label"] = os.environ["ENDODIGEST_RECIPIENT_LABEL"]


def get_secret(config: dict[str, Any], env_name: str) -> str:
    return str(config.get("secrets", {}).get(env_name.lower()) or os.environ.get(env_name) or "")


def is_real_secret(value: str | None) -> bool:
    if not value:
        return False
    lower = value.lower()
    placeholder_bits = [
        "placeholder",
        "example.com",
        "optional-",
        "google-doc-id",
        "placeholders",
        "begin private key-----\\nplaceholder",
    ]
    return not any(bit in lower for bit in placeholder_bits)


def deep_copy_without_secrets(config: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(config)
    if "secrets" in copied:
        copied["secrets"] = {name: "***" for name in copied["secrets"]}
    return copied


def validate_config(
    config: dict[str, Any],
    *,
    strict_secrets: bool = False,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for section in ["schedule", "date_windows", "llm", "sources", "outputs"]:
        if section not in config:
            errors.append(f"missing config section: {section}")
    timezone = config.get("schedule", {}).get("timezone")
    if not timezone:
        errors.append("schedule.timezone is required")
    append_mode = config.get("outputs", {}).get("google_doc_append_mode")
    if append_mode not in {"top", "bottom"}:
        errors.append("outputs.google_doc_append_mode must be 'top' or 'bottom'")
    threshold = int(config.get("inclusion", {}).get("relevance_threshold", 0))
    if threshold < 0 or threshold > 100:
        errors.append("inclusion.relevance_threshold must be 0-100")

    if strict_secrets and not dry_run:
        if config.get("outputs", {}).get("email", True):
            for name in ["OPENAI_API_KEY", "SENDGRID_API_KEY", "DIGEST_TO", "DIGEST_FROM"]:
                if not is_real_secret(get_secret(config, name)):
                    errors.append(f"missing required secret for email run: {name}")
        if config.get("outputs", {}).get("google_doc", True):
            for name in ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DOC_ID"]:
                if not is_real_secret(get_secret(config, name)):
                    warnings.append(f"Google Docs output will be skipped without {name}")

    for name in ["NCBI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID", "SERPAPI_API_KEY", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"]:
        if not is_real_secret(get_secret(config, name)):
            warnings.append(f"optional secret not configured: {name}")
    return errors, warnings
