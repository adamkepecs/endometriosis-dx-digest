from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from endodigest.utils.normalize import canonicalize_url, normalize_title

CATEGORIES = [
    "saliva_miRNA",
    "blood_biomarker",
    "menstrual_blood",
    "urine",
    "imaging_ultrasound_MRI",
    "molecular_imaging_radiotracer",
    "AI_diagnostic",
    "regulatory",
    "commercial_launch",
    "clinical_trial",
    "conference_abstract",
    "review_or_meta_analysis",
    "other",
]

EVIDENCE_LEVELS = [
    "commercial_claim",
    "press_release",
    "preprint",
    "peer_reviewed_preclinical",
    "peer_reviewed_clinical",
    "clinical_trial_registry",
    "regulatory_update",
    "guideline_or_consensus",
]


@dataclass(slots=True)
class CollectorResult:
    source_type: str
    source_name: str
    stable_id: str
    title: str
    url: str
    publication_date: str
    discovered_date: str
    authors_or_org: str
    abstract_or_snippet: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectorResult":
        return cls(
            source_type=str(data.get("source_type", "")),
            source_name=str(data.get("source_name", "")),
            stable_id=str(data.get("stable_id", "")),
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            publication_date=str(data.get("publication_date", "")),
            discovered_date=str(data.get("discovered_date", "")),
            authors_or_org=str(data.get("authors_or_org", "")),
            abstract_or_snippet=str(data.get("abstract_or_snippet", "")),
            raw=dict(data.get("raw") or {}),
        )

    def dedupe_keys(self) -> list[str]:
        raw = self.raw or {}
        keys: list[str] = []
        pmid = raw.get("pmid") or (self.stable_id.split(":", 1)[1] if self.stable_id.startswith("pmid:") else "")
        doi = raw.get("doi")
        nct_id = raw.get("nct_id") or (self.stable_id.split(":", 1)[1] if self.stable_id.startswith("nct:") else "")
        url = canonicalize_url(self.url)
        title_key = normalize_title(self.title)
        if pmid:
            keys.append(f"pmid:{str(pmid).lower()}")
        if doi:
            keys.append(f"doi:{str(doi).lower().strip()}")
        if nct_id:
            keys.append(f"nct:{str(nct_id).upper().strip()}")
        if url:
            keys.append(f"url:{url}")
        if title_key:
            keys.append(f"title_source:{title_key}|{self.source_name.lower()}")
        if self.stable_id:
            keys.append(f"stable:{self.stable_id.lower()}")
        return keys


@dataclass(slots=True)
class Classification:
    include: bool
    relevance_score: int
    category: str
    evidence_level: str
    key_claim: str
    comparator_or_gold_standard: str
    sample_type: str
    cohort_size: str
    sensitivity: str
    specificity: str
    AUC: str
    PPV: str
    NPV: str
    limitations: str
    why_it_matters: str
    skepticism_note: str
    source_quality: str
    must_read: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def validate(cls, data: dict[str, Any]) -> "Classification":
        missing = [name for name in CLASSIFICATION_REQUIRED if name not in data]
        if missing:
            raise ValueError(f"classification missing required fields: {', '.join(missing)}")
        category = str(data["category"])
        evidence_level = str(data["evidence_level"])
        if category not in CATEGORIES:
            raise ValueError(f"invalid category: {category}")
        if evidence_level not in EVIDENCE_LEVELS:
            raise ValueError(f"invalid evidence_level: {evidence_level}")
        score = int(data["relevance_score"])
        if score < 0 or score > 100:
            raise ValueError("relevance_score must be 0-100")
        return cls(
            include=bool(data["include"]),
            relevance_score=score,
            category=category,
            evidence_level=evidence_level,
            key_claim=str(data.get("key_claim") or ""),
            comparator_or_gold_standard=str(data.get("comparator_or_gold_standard") or ""),
            sample_type=str(data.get("sample_type") or ""),
            cohort_size=str(data.get("cohort_size") or ""),
            sensitivity=str(data.get("sensitivity") or ""),
            specificity=str(data.get("specificity") or ""),
            AUC=str(data.get("AUC") or ""),
            PPV=str(data.get("PPV") or ""),
            NPV=str(data.get("NPV") or ""),
            limitations=str(data.get("limitations") or ""),
            why_it_matters=str(data.get("why_it_matters") or ""),
            skepticism_note=str(data.get("skepticism_note") or ""),
            source_quality=str(data.get("source_quality") or ""),
            must_read=bool(data.get("must_read")),
        )


@dataclass(slots=True)
class ClassifiedItem:
    item: CollectorResult
    classification: Classification

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "classification": self.classification.to_dict(),
        }


CLASSIFICATION_REQUIRED = [
    "include",
    "relevance_score",
    "category",
    "evidence_level",
    "key_claim",
    "comparator_or_gold_standard",
    "sample_type",
    "cohort_size",
    "sensitivity",
    "specificity",
    "AUC",
    "PPV",
    "NPV",
    "limitations",
    "why_it_matters",
    "skepticism_note",
    "source_quality",
    "must_read",
]


def classification_json_schema() -> dict[str, Any]:
    string_field = {"type": "string"}
    properties: dict[str, Any] = {
        "include": {"type": "boolean"},
        "relevance_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "category": {"type": "string", "enum": CATEGORIES},
        "evidence_level": {"type": "string", "enum": EVIDENCE_LEVELS},
        "must_read": {"type": "boolean"},
    }
    for field_name in CLASSIFICATION_REQUIRED:
        properties.setdefault(field_name, string_field)
    return {
        "type": "object",
        "properties": properties,
        "required": CLASSIFICATION_REQUIRED,
        "additionalProperties": False,
    }
