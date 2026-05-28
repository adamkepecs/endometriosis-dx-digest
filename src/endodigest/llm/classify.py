from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from endodigest.config import get_secret, is_real_secret
from endodigest.llm.openai_client import OpenAIAPIError, ResponsesClient
from endodigest.models import (
    Classification,
    ClassifiedItem,
    CollectorResult,
    classification_json_schema,
)

LOGGER = logging.getLogger(__name__)

DIAGNOSTIC_TERMS = [
    "diagnos",
    "biomarker",
    "assay",
    "test",
    "screen",
    "imaging",
    "ultrasound",
    "mri",
    "spect",
    "radiotracer",
    "saliva",
    "blood",
    "urine",
    "menstrual",
    "microrna",
    "mirna",
    "radiomics",
    "methylation",
]


def classify_items(items: list[CollectorResult], config: dict[str, Any], *, dry_run: bool = False) -> list[ClassifiedItem]:
    api_key = get_secret(config, "OPENAI_API_KEY")
    use_llm = is_real_secret(api_key) and not dry_run
    client = None
    if use_llm:
        client = ResponsesClient(
            api_key=api_key,
            model=str(config.get("llm", {}).get("model", "gpt-4.1-mini")),
            timeout=int(config.get("llm", {}).get("request_timeout_seconds", 60)),
        )
    threshold = int(config.get("inclusion", {}).get("relevance_threshold", 55))
    classified: list[ClassifiedItem] = []
    for item in items:
        classification = _classify_one(item, config, client=client)
        include = classification.include and (
            classification.relevance_score >= threshold or _explicit_endometriosis_dx(item)
        )
        if include:
            classified.append(ClassifiedItem(item=item, classification=classification))
    return sorted(
        classified,
        key=lambda row: (row.classification.must_read, row.classification.relevance_score),
        reverse=True,
    )


def _classify_one(
    item: CollectorResult,
    config: dict[str, Any],
    *,
    client: ResponsesClient | None,
) -> Classification:
    if client is None:
        return heuristic_classification(item)
    system = _read_prompt("system.md")
    task = _read_prompt("classify_item.md")
    prompt = f"{task}\n\nItem JSON:\n{json.dumps(item.to_dict(), indent=2, sort_keys=True)}"
    try:
        payload = client.create_json(
            prompt=prompt,
            system=system,
            schema=classification_json_schema(),
            schema_name="endometriosis_dx_classification",
        )
        return Classification.validate(payload)
    except (OpenAIAPIError, ValueError) as exc:
        LOGGER.warning("LLM classification failed for %s; using heuristic fallback: %s", item.stable_id, exc)
        return heuristic_classification(item)


def heuristic_classification(item: CollectorResult) -> Classification:
    text = f"{item.title} {item.abstract_or_snippet} {item.authors_or_org} {item.url}".lower()
    explicit = _explicit_endometriosis_dx(item)
    category = _category(text, item.source_type)
    evidence = _evidence_level(text, item)
    score = 20
    if "endometriosis" in text:
        score += 25
    if any(term in text for term in DIAGNOSTIC_TERMS):
        score += 25
    if item.source_type == "clinical_trial":
        score += 20
    if category in {"regulatory", "commercial_launch"}:
        score += 15
    if item.source_type == "paper" and ("sensitivity" in text or "specificity" in text or "auc" in text):
        score += 15
    score = max(0, min(100, score))
    include = explicit or score >= 55
    metrics = _extract_metrics(text)
    return Classification(
        include=include,
        relevance_score=score,
        category=category,
        evidence_level=evidence,
        key_claim=_claim(item),
        comparator_or_gold_standard=_gold_standard(text),
        sample_type=_sample_type(text),
        cohort_size=_cohort_size(text),
        sensitivity=metrics.get("sensitivity", ""),
        specificity=metrics.get("specificity", ""),
        AUC=metrics.get("auc", ""),
        PPV=metrics.get("ppv", ""),
        NPV=metrics.get("npv", ""),
        limitations="Not assessed by LLM; verify methods, cohort selection, reference standard, and independent validation.",
        why_it_matters=_why_it_matters(category),
        skepticism_note=_skepticism(evidence),
        source_quality=_source_quality(evidence, item),
        must_read=score >= 80 or item.source_type in {"clinical_trial", "regulatory"},
    )


def _explicit_endometriosis_dx(item: CollectorResult) -> bool:
    text = f"{item.title} {item.abstract_or_snippet} {item.url}".lower()
    if item.source_type in {"clinical_trial", "regulatory"} and "endometriosis" in text:
        return True
    return "endometriosis" in text and any(term in text for term in DIAGNOSTIC_TERMS)


def _category(text: str, source_type: str) -> str:
    if source_type == "clinical_trial":
        return "clinical_trial"
    if "fda" in text or "regulatory" in text or "clearance" in text or "fast track" in text:
        return "regulatory"
    if "launch" in text or "commercial" in text or "available" in text:
        return "commercial_launch"
    if "saliva" in text or "salivary" in text or "mirna" in text or "microrna" in text:
        return "saliva_miRNA"
    if "menstrual" in text or "effluent" in text:
        return "menstrual_blood"
    if "urine" in text:
        return "urine"
    if "maraciclatide" in text or "spect" in text or "radiotracer" in text:
        return "molecular_imaging_radiotracer"
    if "ultrasound" in text or "mri" in text or "radiomics" in text:
        return "imaging_ultrasound_MRI"
    if "ai" in text or "machine learning" in text or "deep learning" in text:
        return "AI_diagnostic"
    if "blood" in text or "plasma" in text or "serum" in text or "proteomic" in text:
        return "blood_biomarker"
    if "review" in text or "meta-analysis" in text:
        return "review_or_meta_analysis"
    return "other"


def _evidence_level(text: str, item: CollectorResult) -> str:
    if item.source_type == "clinical_trial":
        return "clinical_trial_registry"
    if item.source_type == "regulatory" or "fda" in text or "regulatory" in text:
        return "regulatory_update"
    if "press release" in text or "prnewswire" in text or "businesswire" in text or "globenewswire" in text:
        return "press_release"
    if "preprint" in text or "biorxiv" in text or "medrxiv" in text:
        return "preprint"
    if item.source_type == "paper":
        if any(term in text for term in ["patient", "cohort", "sensitivity", "specificity", "auc", "clinical"]):
            return "peer_reviewed_clinical"
        return "peer_reviewed_preclinical"
    if "guideline" in text or "consensus" in text:
        return "guideline_or_consensus"
    return "commercial_claim"


def _extract_metrics(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    patterns = {
        "sensitivity": r"sensitivit(?:y|ies)[^\d]{0,20}(\d{1,3}(?:\.\d+)?\s*%?)",
        "specificity": r"specificit(?:y|ies)[^\d]{0,20}(\d{1,3}(?:\.\d+)?\s*%?)",
        "auc": r"\bauc[^\d]{0,20}(\d(?:\.\d+)?)",
        "ppv": r"\bppv[^\d]{0,20}(\d{1,3}(?:\.\d+)?\s*%?)",
        "npv": r"\bnpv[^\d]{0,20}(\d{1,3}(?:\.\d+)?\s*%?)",
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            metrics[name] = match.group(1)
    return metrics


def _cohort_size(text: str) -> str:
    match = re.search(r"\b(?:n\s*=\s*|cohort of |study of )(\d{2,6})", text)
    return match.group(1) if match else ""


def _sample_type(text: str) -> str:
    for sample in ["saliva", "blood", "plasma", "serum", "menstrual blood", "urine", "imaging", "tissue"]:
        if sample in text:
            return sample
    return ""


def _gold_standard(text: str) -> str:
    if "laparoscopy" in text or "surgery" in text:
        return "surgical/laparoscopic diagnosis"
    if "histolog" in text:
        return "histology"
    if "mri" in text or "ultrasound" in text:
        return "imaging comparator"
    return ""


def _claim(item: CollectorResult) -> str:
    snippet = item.abstract_or_snippet or item.title
    return snippet[:260].strip()


def _why_it_matters(category: str) -> str:
    if category == "clinical_trial":
        return "Registered diagnostic studies can signal prospective validation and near-term readouts."
    if category in {"regulatory", "commercial_launch"}:
        return "Regulatory and commercial movement can affect availability, claims, and adoption pressure."
    return "Potentially relevant to noninvasive or less-invasive endometriosis diagnosis surveillance."


def _skepticism(evidence: str) -> str:
    if evidence in {"commercial_claim", "press_release"}:
        return "Treat as a claim until methods, reference standard, population, and independent validation are visible."
    if evidence == "clinical_trial_registry":
        return "Registry entries show study intent and updates, not diagnostic performance."
    if evidence == "peer_reviewed_clinical":
        return "Check independent validation, spectrum bias, comparator, and confidence intervals."
    return "Interpret in context; diagnostic utility depends on validation against an appropriate reference standard."


def _source_quality(evidence: str, item: CollectorResult) -> str:
    if evidence == "peer_reviewed_clinical":
        return "peer-reviewed clinical source"
    if evidence == "clinical_trial_registry":
        return "trial registry"
    if evidence == "regulatory_update":
        return "regulatory or official update"
    if item.url:
        return "web source with primary link"
    return "source quality uncertain"


def _read_prompt(name: str) -> str:
    path = Path("prompts") / name
    return path.read_text(encoding="utf-8") if path.exists() else ""
