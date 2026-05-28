from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from endodigest.config import (
    deep_copy_without_secrets,
    get_secret,
    is_real_secret,
    load_config,
    load_seed_queries,
    validate_config,
)
from endodigest.llm.classify import classify_items
from endodigest.llm.synthesize import synthesize_digest
from endodigest.render.email import EmailDeliveryError, send_digest_email, subject_for
from endodigest.render.google_doc import append_digest_to_google_doc, print_service_account_email
from endodigest.render.html import markdown_to_html, write_html
from endodigest.render.markdown import write_markdown
from endodigest.sources.clinicaltrials import collect_clinical_trials
from endodigest.sources.fda_press import collect_fda_press
from endodigest.sources.pubmed import collect_pubmed
from endodigest.sources.web_search import collect_web_search
from endodigest.state import SeenStore, dedupe_collector_results
from endodigest.utils.dates import date_window, utc_stamp
from endodigest.utils.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(getattr(args, "verbose", False))
    try:
        return int(args.func(args) or 0)
    except EmailDeliveryError as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should return clear failures.
        LOGGER.error("%s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="endodigest", description="Endometriosis diagnostics digest automation")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML/JSON")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(required=True)

    run_parser = subparsers.add_parser("run", help="Collect, classify, synthesize, and deliver the digest")
    run_parser.add_argument("--lookback-days", type=int, default=None)
    run_parser.add_argument("--backfill-days", type=int, default=None)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--send-email", dest="send_email", action=argparse.BooleanOptionalAction, default=None)
    run_parser.add_argument("--update-google-doc", dest="update_google_doc", action=argparse.BooleanOptionalAction, default=None)
    run_parser.set_defaults(func=run_digest)

    collect_parser = subparsers.add_parser("collect", help="Collect from one source and print JSON")
    collect_parser.add_argument("--source", choices=["pubmed", "clinicaltrials", "web_search", "fda_press", "all"], required=True)
    collect_parser.add_argument("--lookback-days", type=int, default=None)
    collect_parser.add_argument("--backfill-days", type=int, default=None)
    collect_parser.set_defaults(func=collect_command)

    email_parser = subparsers.add_parser("print-google-service-account-email", help="Print service account client_email")
    email_parser.set_defaults(func=print_google_service_account_email_command)

    validate_parser = subparsers.add_parser("validate-config", help="Validate config shape and optional secret status")
    validate_parser.add_argument("--strict-secrets", action="store_true")
    validate_parser.set_defaults(func=validate_config_command)
    return parser


def run_digest(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    errors, warnings = validate_config(config, strict_secrets=False, dry_run=args.dry_run)
    for warning in warnings:
        LOGGER.warning(warning)
    if errors:
        for error in errors:
            LOGGER.error(error)
        return 1

    tz_name = str(config.get("schedule", {}).get("timezone", "America/Chicago"))
    default_lookback = int(config.get("date_windows", {}).get("default_lookback_days", 10))
    lookback_days = args.lookback_days if args.lookback_days is not None else default_lookback
    start, end = date_window(lookback_days=lookback_days, backfill_days=args.backfill_days, tz_name=tz_name)

    stamp = utc_stamp()
    run_dir = Path("data/runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = run_dir / f"{stamp}_digest.md"
    html_path = run_dir / f"{stamp}_digest.html"
    metadata_path = run_dir / f"{stamp}_metadata.json"

    LOGGER.info("collecting items for %s to %s", start, end)
    raw_items, source_counts, queries_run = collect_all_sources(config, start, end)
    seen = SeenStore(Path("data/seen.json"))
    new_items = dedupe_collector_results(raw_items, seen)
    LOGGER.info("collected %d item(s), %d new after dedupe", len(raw_items), len(new_items))

    classified = classify_items(new_items, config, dry_run=args.dry_run)
    LOGGER.info("%d item(s) included after classification", len(classified))
    markdown, synthesis_mode = synthesize_digest(
        classified,
        config=config,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        source_counts=source_counts,
        queries_run=queries_run,
        dry_run=args.dry_run,
    )
    write_markdown(markdown, markdown_path)
    write_html(markdown, html_path)
    html = markdown_to_html(markdown)

    send_email_flag = bool(config.get("outputs", {}).get("email", True)) if args.send_email is None else bool(args.send_email)
    update_google_doc_flag = bool(config.get("outputs", {}).get("google_doc", True)) if args.update_google_doc is None else bool(args.update_google_doc)
    if args.dry_run:
        send_email_flag = False
        update_google_doc_flag = False

    output_status: dict[str, Any] = {
        "markdown_path": str(markdown_path),
        "html_path": str(html_path),
        "email": "skipped",
        "google_doc": "skipped",
    }
    if update_google_doc_flag:
        doc_result = append_digest_to_google_doc(config, markdown)
        output_status["google_doc"] = doc_result.message
        LOGGER.info(doc_result.message)

    email_error = None
    if send_email_flag:
        subject = subject_for(end.isoformat(), str(config.get("outputs", {}).get("subject_prefix", "Endometriosis diagnostics weekly digest")))
        try:
            if not is_real_secret(get_secret(config, "OPENAI_API_KEY")):
                (run_dir / "latest_email.html").write_text(html, encoding="utf-8")
                raise EmailDeliveryError(
                    "OPENAI_API_KEY is required for non-dry email runs. "
                    f"Rendered digest saved to {html_path}."
                )
            email_result = send_digest_email(config=config, subject=subject, html=html, markdown=markdown, run_dir=run_dir)
            output_status["email"] = email_result.message
        except EmailDeliveryError as exc:
            email_error = exc
            output_status["email"] = str(exc)

    if not args.dry_run and email_error is None:
        seen.mark_many(row.item for row in classified)
        seen.save()

    metadata = {
        "stamp": stamp,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "dry_run": args.dry_run,
        "source_counts": source_counts,
        "raw_count": len(raw_items),
        "new_count": len(new_items),
        "included_count": len(classified),
        "synthesis_mode": synthesis_mode,
        "outputs": output_status,
        "queries_run": queries_run,
        "config": deep_copy_without_secrets(config),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s and %s", markdown_path, html_path)
    LOGGER.info("wrote metadata to %s", metadata_path)

    if email_error is not None:
        raise email_error
    return 0


def collect_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    tz_name = str(config.get("schedule", {}).get("timezone", "America/Chicago"))
    default_lookback = int(config.get("date_windows", {}).get("default_lookback_days", 10))
    start, end = date_window(
        lookback_days=args.lookback_days if args.lookback_days is not None else default_lookback,
        backfill_days=args.backfill_days,
        tz_name=tz_name,
    )
    items, _, _ = collect_all_sources(config, start, end, only=args.source)
    print(json.dumps([item.to_dict() for item in items], indent=2, sort_keys=True))
    return 0


def validate_config_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    errors, warnings = validate_config(config, strict_secrets=args.strict_secrets)
    for warning in warnings:
        LOGGER.warning(warning)
    if errors:
        for error in errors:
            LOGGER.error(error)
        return 1
    LOGGER.info("config OK: %s", config.get("_config_path"))
    return 0


def print_google_service_account_email_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(print_service_account_email(config))
    return 0


def collect_all_sources(
    config: dict[str, Any],
    start,
    end,
    *,
    only: str = "all",
):
    collectors = {
        "pubmed": collect_pubmed,
        "clinicaltrials": collect_clinical_trials,
        "web_search": collect_web_search,
        "fda_press": collect_fda_press,
    }
    if only != "all":
        collectors = {only: collectors[only]}
    items = []
    counts: dict[str, int] = {}
    for name, collector in collectors.items():
        collected = collector(config, start, end)
        items.extend(collected)
        counts[name] = len(collected)
    return items, counts, queries_run_from_config(config, only=only)


def queries_run_from_config(config: dict[str, Any], *, only: str = "all") -> list[str]:
    source_configs = config.get("sources", {})
    queries: list[str] = []
    for source_name, source_config in source_configs.items():
        if only != "all" and source_name != only:
            continue
        for query in source_config.get("queries", []) or []:
            queries.append(f"{source_name}: {query}")
    seed = load_seed_queries()
    for group, values in seed.items():
        if isinstance(values, list):
            for value in values:
                queries.append(f"seed/{group}: {value}")
    return queries


if __name__ == "__main__":
    sys.exit(main())
