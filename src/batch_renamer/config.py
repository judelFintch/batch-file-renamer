import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


APP_ENV_CONFIG = "BATCH_RENAMER_CONFIG"
LEGACY_CONFIG_NAME = ".batch_renamer.json"
DEFAULT_CODE = "FAC"
MONITOR_INTERVAL_MS = 2000
NUMBERED_NAME_PATTERN = re.compile(r"^(?P<code>[A-Z0-9]+)_(?P<number>\d+)$")
DEFAULT_DOCUMENT_TYPES = {
    "Ordre a declarer": "OAD",
    "Invoice": "FCM",
    "Packing List": "LCL",
    "Manifest": "MNF",
    "Certificat d'assurance": "CAA",
}
DEFAULT_AUTO_RENAME = True
DEFAULT_AI_AGENT_ENABLED = False
DEFAULT_AI_REVIEW_THRESHOLD = 0.65
DEFAULT_AI_AUTO_RENAME_THRESHOLD = 0.85
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_AI_PROVIDER = "openai"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_LMSTUDIO_MODEL = "local-model"
DEFAULT_LMSTUDIO_URL = "http://localhost:1234/v1/responses"
AUTO_DETECT_MIN_SCORE = 2
AUTO_DETECT_MIN_MARGIN = 1
REFERENCE_TERM_LIMIT = 24
REFERENCE_PHRASE_LIMIT = 18
REFERENCE_LINE_LIMIT = 6
REFERENCE_SCORE_THRESHOLD = 6
COMMON_REFERENCE_STOPWORDS = {
    "avec",
    "avoir",
    "bill",
    "cette",
    "chez",
    "code",
    "comment",
    "dans",
    "date",
    "document",
    "dont",
    "elle",
    "from",
    "have",
    "nous",
    "page",
    "pour",
    "reference",
    "sera",
    "sont",
    "that",
    "this",
    "votre",
    "vous",
}


def config_file_path() -> Path:
    env_path = os.environ.get(APP_ENV_CONFIG, "").strip()
    if env_path:
        return Path(env_path).expanduser()

    legacy_path = Path.cwd() / LEGACY_CONFIG_NAME
    if legacy_path.exists():
        return legacy_path

    return Path.home() / LEGACY_CONFIG_NAME


CONFIG_FILE = config_file_path()


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}

    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(config: Dict[str, Any]):
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def normalize_code(raw_code: Optional[str]) -> str:
    code = (raw_code or DEFAULT_CODE).strip().upper()
    if not code:
        raise ValueError("The acronym cannot be empty.")
    if not re.fullmatch(r"[A-Z0-9]+", code):
        raise ValueError("The acronym must contain only letters and numbers.")
    return code


def normalize_document_types(raw_document_types: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not raw_document_types:
        return DEFAULT_DOCUMENT_TYPES.copy()

    normalized = {}
    for label, code in raw_document_types.items():
        cleaned_label = str(label).strip()
        if not cleaned_label:
            continue
        normalized[cleaned_label] = normalize_code(str(code))

    return normalized or DEFAULT_DOCUMENT_TYPES.copy()


def normalize_document_keywords(
    raw_document_keywords: Optional[Dict[str, Sequence[str]]],
    document_types: Dict[str, str],
) -> Dict[str, List[str]]:
    normalized = {label: [] for label in document_types}

    if not raw_document_keywords:
        return normalized

    for label, keywords in raw_document_keywords.items():
        if label not in document_types:
            continue
        if isinstance(keywords, str):
            items = keywords.split(",")
        else:
            items = keywords
        normalized[label] = [str(keyword).strip().lower() for keyword in items if str(keyword).strip()]

    return normalized


def normalize_document_reference_samples(
    raw_reference_samples: Optional[Dict[str, Sequence[Dict[str, Any]]]],
    document_types: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    normalized = {label: [] for label in document_types}

    if not raw_reference_samples:
        return normalized

    for label, samples in raw_reference_samples.items():
        if label not in document_types or not isinstance(samples, Sequence):
            continue

        cleaned_samples: List[Dict[str, Any]] = []
        for sample in samples:
            if not isinstance(sample, dict):
                continue

            cleaned_sample = {
                "name": str(sample.get("name", "")).strip(),
                "source": str(sample.get("source", "")).strip(),
                "extraction_method": str(sample.get("extraction_method", "")).strip(),
                "rename_label": str(sample.get("rename_label", "")).strip(),
                "rename_code": str(sample.get("rename_code", "")).strip(),
                "terms": [str(item).strip() for item in sample.get("terms", []) if str(item).strip()],
                "phrases": [str(item).strip() for item in sample.get("phrases", []) if str(item).strip()],
                "lines": [str(item).strip() for item in sample.get("lines", []) if str(item).strip()],
            }
            if cleaned_sample["terms"] or cleaned_sample["phrases"] or cleaned_sample["lines"]:
                cleaned_samples.append(cleaned_sample)

        normalized[label] = cleaned_samples

    return normalized
