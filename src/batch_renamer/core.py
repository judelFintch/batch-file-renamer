import argparse
import json
import re
import shutil
import subprocess
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import (
    AUTO_DETECT_MIN_MARGIN,
    AUTO_DETECT_MIN_SCORE,
    COMMON_REFERENCE_STOPWORDS,
    DEFAULT_CODE,
    REFERENCE_LINE_LIMIT,
    REFERENCE_PHRASE_LIMIT,
    REFERENCE_SCORE_THRESHOLD,
    REFERENCE_TERM_LIMIT,
    NUMBERED_NAME_PATTERN,
    load_config,
    normalize_code,
    save_config,
)


RenamePlan = List[Tuple[Path, Path]]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rename scanned files with an acronym and numbered pattern."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="Path to the folder containing the files to rename",
    )
    parser.add_argument(
        "--code",
        "--prefix",
        dest="code",
        default=None,
        help=f"Acronym used for renamed files (default: {DEFAULT_CODE})",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting number for the sequence (default: 1)",
    )
    parser.add_argument(
        "--save-folder",
        action="store_true",
        help="Save the provided folder as the default folder",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the rename operations without changing files",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical interface",
    )
    return parser.parse_args()


def normalize_text_for_matching(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def split_keyword_tokens(keyword: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalize_text_for_matching(keyword)) if token]


def extract_reference_tokens(text: str) -> List[str]:
    normalized_text = normalize_text_for_matching(text)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized_text)
        if len(token) >= 4 and not token.isdigit() and token not in COMMON_REFERENCE_STOPWORDS
    ]


def build_reference_sample(
    file_path: Path,
    text: str,
    extraction_method: str,
    rename_label: str,
    rename_code: str,
) -> Dict[str, Any]:
    tokens = extract_reference_tokens(text)
    token_counts = Counter(tokens)

    phrase_counts: Counter[str] = Counter()
    for size in (2, 3):
        for index in range(len(tokens) - size + 1):
            phrase_tokens = tokens[index:index + size]
            if all(token in COMMON_REFERENCE_STOPWORDS for token in phrase_tokens):
                continue
            phrase_counts[" ".join(phrase_tokens)] += 1

    normalized_lines = []
    for raw_line in text.splitlines():
        line = normalize_text_for_matching(raw_line)
        if 8 <= len(line) <= 90:
            normalized_lines.append(line)

    return {
        "name": file_path.name,
        "source": str(file_path),
        "extraction_method": extraction_method,
        "rename_label": rename_label,
        "rename_code": rename_code,
        "terms": [term for term, _ in token_counts.most_common(REFERENCE_TERM_LIMIT)],
        "phrases": [
            phrase
            for phrase, _ in sorted(
                phrase_counts.items(),
                key=lambda item: (-item[1], -len(item[0]), item[0]),
            )[:REFERENCE_PHRASE_LIMIT]
        ],
        "lines": list(dict.fromkeys(normalized_lines))[:REFERENCE_LINE_LIMIT],
    }


def summarize_reference_samples(samples: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    term_counts: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()
    line_counts: Counter[str] = Counter()

    for sample in samples:
        term_counts.update(sample.get("terms", []))
        phrase_counts.update(sample.get("phrases", []))
        line_counts.update(sample.get("lines", []))

    return {
        "terms": [term for term, _ in term_counts.most_common(REFERENCE_TERM_LIMIT)],
        "phrases": [phrase for phrase, _ in phrase_counts.most_common(REFERENCE_PHRASE_LIMIT)],
        "lines": [line for line, _ in line_counts.most_common(REFERENCE_LINE_LIMIT)],
    }


def build_reference_summary_for_prompt(
    document_types: Dict[str, str],
    document_keywords: Dict[str, Sequence[str]],
    document_reference_samples: Dict[str, Sequence[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for label, code in document_types.items():
        samples = document_reference_samples.get(label, [])
        aggregated = summarize_reference_samples(samples)
        summary[label] = {
            "rename_code": code,
            "keywords": list(document_keywords.get(label, []))[:12],
            "sample_count": len(samples),
            "top_terms": aggregated["terms"][:12],
            "top_phrases": aggregated["phrases"][:8],
            "top_lines": aggregated["lines"][:4],
        }
    return summary


def extract_response_text(response_payload: Dict[str, Any]) -> str:
    output_items = response_payload.get("output", [])
    for item in output_items:
        if item.get("type") != "message":
            continue
        for content_item in item.get("content", []):
            if content_item.get("type") == "output_text":
                return content_item.get("text", "")
            if content_item.get("type") == "refusal":
                return json.dumps({"action": "review", "reason": content_item.get("refusal", "refusal")})
    return ""


def send_openai_responses_request(
    api_key: str,
    endpoint_url: str,
    request_body: Dict[str, Any],
    timeout: int = 45,
) -> Dict[str, Any]:
    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI agent request failed: {exc.code} {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI agent request failed: {exc.reason}") from exc

    return json.loads(raw_response)


def send_json_post_request(
    endpoint_url: str,
    request_body: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 45,
) -> Dict[str, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Request failed: {exc.code} {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason}") from exc

    return json.loads(raw_response)


def ask_ai_agent_to_classify(
    file_path: Path,
    extracted_text: str,
    extraction_method: str,
    document_types: Dict[str, str],
    document_keywords: Dict[str, Sequence[str]],
    document_reference_samples: Dict[str, Sequence[Dict[str, Any]]],
    api_key: str,
    model: str,
    endpoint_url: str,
) -> Dict[str, Any]:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    prompt_payload = {
        "filename": file_path.name,
        "suffix": file_path.suffix.lower(),
        "extraction_method": extraction_method,
        "document_targets": build_reference_summary_for_prompt(
            document_types,
            document_keywords,
            document_reference_samples,
        ),
        "document_text": extracted_text[:12000],
    }

    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["auto_rename", "review", "reject"]},
            "rename_label": {"type": ["string", "null"]},
            "rename_code": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "matched_evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "rename_label", "rename_code", "confidence", "reason", "matched_evidence"],
        "additionalProperties": False,
    }

    request_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a document-routing agent. "
                    "Choose only among the provided rename targets. "
                    "Use action='auto_rename' only when evidence is strong. "
                    "Use action='review' when there is some signal but a human should confirm. "
                    "Use action='reject' when the document does not fit any known target. "
                    "Confidence must be between 0 and 1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=True),
            },
        ],
        "reasoning": {"effort": "high"},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "document_routing_decision",
                "strict": True,
                "schema": schema,
            }
        },
    }

    response_payload = send_openai_responses_request(api_key, endpoint_url, request_body)
    response_text = extract_response_text(response_payload).strip()
    if not response_text:
        raise RuntimeError("AI agent returned an empty response.")

    decision = json.loads(response_text)
    if decision.get("rename_label") and decision["rename_label"] not in document_types:
        decision["action"] = "review"
        decision["reason"] = "AI proposed an unknown rename target."
    return decision


def ask_ollama_agent_to_classify(
    file_path: Path,
    extracted_text: str,
    extraction_method: str,
    document_types: Dict[str, str],
    document_keywords: Dict[str, Sequence[str]],
    document_reference_samples: Dict[str, Sequence[Dict[str, Any]]],
    model: str,
    endpoint_url: str,
) -> Dict[str, Any]:
    prompt_payload = {
        "filename": file_path.name,
        "suffix": file_path.suffix.lower(),
        "extraction_method": extraction_method,
        "document_targets": build_reference_summary_for_prompt(
            document_types,
            document_keywords,
            document_reference_samples,
        ),
        "document_text": extracted_text[:12000],
        "expected_json_keys": [
            "action",
            "rename_label",
            "rename_code",
            "confidence",
            "reason",
            "matched_evidence",
        ],
    }

    prompt = (
        "You are a document-routing agent. "
        "Choose only among the provided rename targets. "
        "Return JSON only with keys: "
        "action, rename_label, rename_code, confidence, reason, matched_evidence. "
        "action must be auto_rename, review, or reject. "
        "confidence must be between 0 and 1.\n\n"
        f"{json.dumps(prompt_payload, ensure_ascii=True)}"
    )

    request_body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "rename_label": {"type": ["string", "null"]},
                "rename_code": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
                "matched_evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action", "rename_label", "rename_code", "confidence", "reason", "matched_evidence"],
        },
    }

    response_payload = send_json_post_request(endpoint_url, request_body)
    response_text = str(response_payload.get("response", "")).strip()
    if not response_text:
        raise RuntimeError("Local agent returned an empty response.")

    decision = json.loads(response_text)
    if decision.get("rename_label") and decision["rename_label"] not in document_types:
        decision["action"] = "review"
        decision["reason"] = "Local agent proposed an unknown rename target."
    return decision


def ask_lmstudio_agent_to_classify(
    file_path: Path,
    extracted_text: str,
    extraction_method: str,
    document_types: Dict[str, str],
    document_keywords: Dict[str, Sequence[str]],
    document_reference_samples: Dict[str, Sequence[Dict[str, Any]]],
    model: str,
    endpoint_url: str,
) -> Dict[str, Any]:
    prompt_payload = {
        "filename": file_path.name,
        "suffix": file_path.suffix.lower(),
        "extraction_method": extraction_method,
        "document_targets": build_reference_summary_for_prompt(
            document_types,
            document_keywords,
            document_reference_samples,
        ),
        "document_text": extracted_text[:12000],
    }

    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["auto_rename", "review", "reject"]},
            "rename_label": {"type": ["string", "null"]},
            "rename_code": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "matched_evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "rename_label", "rename_code", "confidence", "reason", "matched_evidence"],
        "additionalProperties": False,
    }

    request_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a document-routing agent. "
                    "Choose only among the provided rename targets. "
                    "Use action='auto_rename' only when evidence is strong. "
                    "Use action='review' when there is some signal but a human should confirm. "
                    "Use action='reject' when the document does not fit any known target. "
                    "Confidence must be between 0 and 1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=True),
            },
        ],
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "document_routing_decision",
                "strict": True,
                "schema": schema,
            }
        },
    }

    response_payload = send_json_post_request(endpoint_url, request_body)
    response_text = extract_response_text(response_payload).strip()
    if not response_text:
        raise RuntimeError("LM Studio agent returned an empty response.")

    decision = json.loads(response_text)
    if decision.get("rename_label") and decision["rename_label"] not in document_types:
        decision["action"] = "review"
        decision["reason"] = "LM Studio agent proposed an unknown rename target."
    return decision


def score_reference_sample(
    sample: Dict[str, Any],
    text: str,
    text_tokens: Sequence[str],
) -> Tuple[int, List[str]]:
    score = 0
    matches: List[str] = []
    token_set = set(text_tokens)

    for phrase in sample.get("phrases", []):
        if phrase and phrase in text:
            matches.append(f"ref:{phrase}")
            score += 4

    for line in sample.get("lines", []):
        if line and line in text:
            matches.append(f"line:{line[:40]}")
            score += 5

    for term in sample.get("terms", []):
        if term and term in token_set:
            matches.append(f"term:{term}")
            score += 2

    if score and len(matches) >= 3:
        score += min(4, len(matches) - 2)

    return score, matches[:5]


def resolve_folder(folder_arg: Optional[str], config: Dict[str, Any]) -> Path:
    if folder_arg:
        return Path(folder_arg).expanduser()

    default_folder = config.get("default_folder")
    if default_folder:
        return Path(default_folder).expanduser()

    raise ValueError(
        "No folder provided. Pass a folder path, save one with --save-folder, or launch the GUI."
    )


def ensure_valid_folder(folder: Path):
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")


def collect_all_files(folder: Path) -> List[Path]:
    return sorted(
        [
            item
            for item in folder.rglob("*")
            if item.is_file() and not item.name.startswith(".rename_tmp_")
        ],
        key=lambda item: (str(item.parent).lower(), item.name.lower()),
    )


def get_numbered_name_match(file_path: Path):
    return NUMBERED_NAME_PATTERN.fullmatch(file_path.stem)


def is_named_for_code(file_path: Path, code: str) -> bool:
    match = get_numbered_name_match(file_path)
    return match is not None and match.group("code") == code


def is_named_for_any_code(file_path: Path, codes: Sequence[str]) -> bool:
    match = get_numbered_name_match(file_path)
    return match is not None and match.group("code") in set(codes)


def next_sequence_number(
    folder: Path,
    code: str,
    minimum: int = 1,
) -> int:
    highest = minimum - 1

    for file_path in collect_all_files(folder):
        match = get_numbered_name_match(file_path)
        if match and match.group("code") == code:
            highest = max(highest, int(match.group("number")))

    return highest + 1


def build_rename_plan(files: Sequence[Path], code: str, start: int) -> RenamePlan:
    plan = []

    for offset, file_path in enumerate(files, start=start):
        new_name = f"{code}_{offset:03}{file_path.suffix.lower()}"
        plan.append((file_path, file_path.with_name(new_name)))

    return plan


def validate_plan(plan: RenamePlan):
    targets = [str(new_path) for _, new_path in plan]

    if len(targets) != len(set(targets)):
        raise ValueError("Duplicate target names detected in the rename plan.")

    for old_path, new_path in plan:
        if old_path == new_path:
            continue
        if new_path.exists():
            raise FileExistsError(
                f"Target file already exists: {new_path.name}. "
                "Rename or remove it before running this script."
            )


def apply_plan(plan: RenamePlan, dry_run: bool) -> List[str]:
    if not plan:
        return ["No matching files found."]

    logs = [f"{old_path} -> {new_path}" for old_path, new_path in plan]

    if dry_run:
        logs.append("Dry run completed. No files were renamed.")
        return logs

    temporary_paths = []

    for index, (old_path, _) in enumerate(plan, start=1):
        temp_suffix = old_path.suffix.lower() if old_path.is_file() else ""
        temp_path = old_path.with_name(f".rename_tmp_{index:03}{temp_suffix}")
        while temp_path.exists():
            temp_path = old_path.with_name(f"{temp_path.stem}_x{temp_path.suffix}")
        old_path.rename(temp_path)
        temporary_paths.append(temp_path)

    for temp_path, (_, new_path) in zip(temporary_paths, plan):
        temp_path.rename(new_path)

    logs.append("Renaming completed.")
    return logs


def collect_pending_files(folder: Path, code: str) -> List[Path]:
    return [file_path for file_path in collect_all_files(folder) if not is_named_for_code(file_path, code)]


def collect_pending_files_for_codes(folder: Path, codes: Sequence[str]) -> List[Path]:
    return [file_path for file_path in collect_all_files(folder) if not is_named_for_any_code(file_path, codes)]


def build_existing_files_preview(folder: Path, codes: Sequence[str]) -> List[str]:
    preview_lines = []

    for file_path in collect_all_files(folder):
        relative_path = str(file_path.relative_to(folder))
        status = "[Named]" if is_named_for_any_code(file_path, codes) else "[Present]"
        preview_lines.append(f"{status} FILE {relative_path}")

    return preview_lines


def rename_files(
    folder: Path,
    code: str,
    start: Optional[int] = None,
    dry_run: bool = False,
    files: Optional[Sequence[Path]] = None,
) -> List[str]:
    ensure_valid_folder(folder)
    source_files = list(files) if files is not None else collect_pending_files(folder, code)

    if not source_files:
        return ["No matching files found."]

    starting_number = start if start is not None else next_sequence_number(folder, code)
    plan = build_rename_plan(source_files, code, starting_number)
    validate_plan(plan)
    return apply_plan(plan, dry_run)


def rename_folder_manually(target_folder: Path, new_name: str, dry_run: bool = False) -> List[str]:
    if str(target_folder).strip() in {"", "."}:
        raise ValueError("Select a folder to rename first.")
    if not target_folder.exists():
        raise FileNotFoundError(f"Folder not found: {target_folder}")
    if not target_folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {target_folder}")
    if target_folder.name == "":
        raise ValueError("The selected folder name is invalid.")

    cleaned_name = new_name.strip()
    if not cleaned_name:
        raise ValueError("The new folder name cannot be empty.")
    if "/" in cleaned_name:
        raise ValueError("The new folder name must not contain '/'.")

    target_path = target_folder.with_name(cleaned_name)
    validate_plan([(target_folder, target_path)])
    return apply_plan([(target_folder, target_path)], dry_run)


def build_classified_rename_plan(
    folder: Path,
    files: Sequence[Path],
    assignments: Dict[str, str],
    document_types: Dict[str, str],
) -> RenamePlan:
    next_numbers: Dict[str, int] = {}
    plan: RenamePlan = []

    for file_path in sorted(files, key=lambda item: str(item).lower()):
        assigned_label = assignments.get(str(file_path))
        if not assigned_label:
            continue

        code = document_types[assigned_label]
        if code not in next_numbers:
            next_numbers[code] = next_sequence_number(folder, code)

        new_name = f"{code}_{next_numbers[code]:03}{file_path.suffix.lower()}"
        plan.append((file_path, file_path.with_name(new_name)))
        next_numbers[code] += 1

    return plan


def extract_text_for_detection(file_path: Path) -> Tuple[str, str]:
    if file_path.suffix.lower() in {".txt", ".csv"}:
        return file_path.read_text(encoding="utf-8", errors="ignore"), "plain_text"

    try:
        textutil_result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        textutil_result = None
    else:
        if textutil_result.returncode == 0 and textutil_result.stdout.strip():
            return textutil_result.stdout, "textutil"

    if file_path.suffix.lower() == ".pdf":
        try:
            strings_result = subprocess.run(
                ["strings", "-n", "6", str(file_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return "", "unreadable"
        if strings_result.returncode == 0:
            return strings_result.stdout, "strings"

    return "", "unreadable"


def ocr_is_available() -> bool:
    return shutil.which("tesseract") is not None


def extract_text_with_ocr(file_path: Path) -> Tuple[str, str]:
    if not ocr_is_available():
        return "", "ocr_missing"

    try:
        ocr_result = subprocess.run(
            ["tesseract", str(file_path), "stdout"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "", "ocr_failed"

    if ocr_result.returncode != 0:
        return "", "ocr_failed"

    return ocr_result.stdout, "ocr"


def detect_document_type(
    file_path: Path,
    document_types: Dict[str, str],
    document_keywords: Dict[str, Sequence[str]],
    document_reference_samples: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
) -> Tuple[Optional[str], int, List[str], str]:
    raw_text, extraction_method = extract_text_for_detection(file_path)
    text = normalize_text_for_matching(raw_text)
    suffix = file_path.suffix.lower()

    if not text.strip() and suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf"}:
        raw_text, extraction_method = extract_text_with_ocr(file_path)
        text = normalize_text_for_matching(raw_text)
        if not text.strip():
            return None, 0, [], extraction_method

    if not text.strip():
        return None, 0, [], f"no_text_extracted:{extraction_method}"

    best_label = None
    best_score = 0
    best_matches: List[str] = []
    second_best_score = 0
    text_tokens = extract_reference_tokens(text)

    for label in document_types:
        matches: List[str] = []
        score = 0

        for keyword in document_keywords.get(label, []):
            normalized_keyword = normalize_text_for_matching(keyword)
            if not normalized_keyword:
                continue

            if normalized_keyword in text:
                matches.append(keyword)
                score += 3 if " " in normalized_keyword else 2
                continue

            keyword_tokens = split_keyword_tokens(normalized_keyword)
            if keyword_tokens and all(token in text for token in keyword_tokens):
                matches.append(keyword)
                score += 1

        if document_reference_samples:
            sample_scores: List[Tuple[int, List[str], str]] = []
            for sample in document_reference_samples.get(label, []):
                sample_score, sample_matches = score_reference_sample(sample, text, text_tokens)
                if sample_score > 0:
                    sample_scores.append((sample_score, sample_matches, sample.get("name", "reference")))

            sample_scores.sort(key=lambda item: item[0], reverse=True)
            for sample_score, sample_matches, sample_name in sample_scores[:3]:
                score += sample_score
                matches.append(f"sample:{sample_name}")
                matches.extend(sample_matches[:2])

            if len(sample_scores) >= 2:
                score += 2

        if score > best_score:
            second_best_score = best_score
            best_label = label
            best_score = score
            best_matches = matches
        elif score > second_best_score:
            second_best_score = score

    if best_score < REFERENCE_SCORE_THRESHOLD and not any(
        document_keywords.get(label) for label in document_types
    ) and document_reference_samples:
        return None, best_score, best_matches[:5], "low_confidence"

    if best_score < AUTO_DETECT_MIN_SCORE:
        return None, best_score, best_matches[:5], "low_confidence"

    if best_score - second_best_score < AUTO_DETECT_MIN_MARGIN:
        return None, best_score, best_matches[:5], "ambiguous_match"

    if best_score == 0:
        return None, 0, [], "no_keyword_match"

    return best_label, best_score, best_matches[:5], extraction_method


def extract_text_preview(file_path: Path) -> Tuple[str, str]:
    raw_text, extraction_method = extract_text_for_detection(file_path)
    text = raw_text.strip()
    suffix = file_path.suffix.lower()

    if not text and suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf"}:
        raw_text, extraction_method = extract_text_with_ocr(file_path)
        text = raw_text.strip()

    return text, extraction_method


__all__ = [
    "RenamePlan",
    "apply_plan",
    "ask_ai_agent_to_classify",
    "ask_lmstudio_agent_to_classify",
    "ask_ollama_agent_to_classify",
    "build_classified_rename_plan",
    "build_existing_files_preview",
    "build_reference_sample",
    "collect_all_files",
    "collect_pending_files",
    "collect_pending_files_for_codes",
    "detect_document_type",
    "ensure_valid_folder",
    "extract_response_text",
    "extract_text_preview",
    "get_numbered_name_match",
    "is_named_for_any_code",
    "is_named_for_code",
    "load_config",
    "next_sequence_number",
    "parse_args",
    "rename_files",
    "rename_folder_manually",
    "resolve_folder",
    "save_config",
    "send_json_post_request",
    "send_openai_responses_request",
    "validate_plan",
]
