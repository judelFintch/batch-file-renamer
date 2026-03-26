import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    from tkinter import ttk
except ModuleNotFoundError as exc:
    tk = None
    filedialog = None
    messagebox = None
    scrolledtext = None
    ttk = None
    TK_IMPORT_ERROR = exc
else:
    TK_IMPORT_ERROR = None


CONFIG_FILE = Path(__file__).with_name(".batch_renamer.json")
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
AUTO_DETECT_MIN_SCORE = 2
AUTO_DETECT_MIN_MARGIN = 1


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


def load_config() -> Dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}

    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(config: Dict[str, str]):
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


def normalize_text_for_matching(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def split_keyword_tokens(keyword: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalize_text_for_matching(keyword)) if token]


def resolve_folder(folder_arg: Optional[str], config: Dict[str, str]) -> Path:
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

        if score > best_score:
            second_best_score = best_score
            best_label = label
            best_score = score
            best_matches = matches
        elif score > second_best_score:
            second_best_score = score

    if best_score < AUTO_DETECT_MIN_SCORE:
        return None, best_score, best_matches, "low_confidence"

    if best_score - second_best_score < AUTO_DETECT_MIN_MARGIN:
        return None, best_score, best_matches, "ambiguous_match"

    if best_score == 0:
        return None, 0, [], "no_keyword_match"

    return best_label, best_score, best_matches, extraction_method


class BatchRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Batch File Renamer")
        self.root.geometry("980x760")

        self.config = load_config()
        self.document_types = normalize_document_types(self.config.get("document_types"))
        self.document_keywords = normalize_document_keywords(
            self.config.get("document_keywords"),
            self.document_types,
        )
        self.monitoring = False
        self.monitor_after_id = None
        self.file_sizes: Dict[str, int] = {}
        self.preview_files: Dict[str, str] = {}
        self.activity_logs: List[str] = []
        self.pending_assignments: Dict[str, str] = {}
        self.pending_statuses: Dict[str, str] = {}
        self.pending_paths: List[Path] = []

        self.folder_var = tk.StringVar(value=self.config.get("default_folder", ""))
        self.manual_folder_var = tk.StringVar()
        self.manual_folder_name_var = tk.StringVar()
        self.document_type_var = tk.StringVar(value=next(iter(self.document_types)))
        self.type_label_var = tk.StringVar()
        self.type_code_var = tk.StringVar()
        self.type_keywords_var = tk.StringVar()
        self.auto_rename_var = tk.BooleanVar(value=self.config.get("auto_rename", DEFAULT_AUTO_RENAME))
        self.assignment_info_var = tk.StringVar(value="Select a file to classify.")
        self.status_var = tk.StringVar(value="Select a folder to start monitoring.")

        self.build_ui()

        if self.folder_var.get():
            self.start_monitoring()

    def build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(6, weight=1)

        title = tk.Label(
            self.root,
            text="Automatic Scan Renamer",
            font=("Helvetica", 18, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(16, 8))

        folder_label = tk.Label(self.root, text="Scanner folder")
        folder_label.grid(row=1, column=0, sticky="w", padx=16, pady=8)

        folder_entry = tk.Entry(self.root, textvariable=self.folder_var)
        folder_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=8)

        browse_button = tk.Button(self.root, text="Browse", command=self.select_folder)
        browse_button.grid(row=1, column=2, sticky="ew", padx=(8, 16), pady=8)

        save_button = tk.Button(self.root, text="Save settings", command=self.save_settings)
        save_button.grid(row=2, column=2, sticky="ew", padx=(8, 16), pady=8)

        auto_rename_check = tk.Checkbutton(
            self.root,
            text="Auto detect and rename",
            variable=self.auto_rename_var,
        )
        auto_rename_check.grid(row=2, column=1, sticky="w", padx=8, pady=8)

        manual_folder_label = tk.Label(self.root, text="Folder to rename")
        manual_folder_label.grid(row=3, column=0, sticky="w", padx=16, pady=8)

        manual_folder_entry = tk.Entry(self.root, textvariable=self.manual_folder_var)
        manual_folder_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=8)

        manual_folder_button = tk.Button(
            self.root,
            text="Choose folder",
            command=self.select_manual_folder,
        )
        manual_folder_button.grid(row=3, column=2, sticky="ew", padx=(8, 16), pady=8)

        manual_name_label = tk.Label(self.root, text="New folder name")
        manual_name_label.grid(row=4, column=0, sticky="w", padx=16, pady=8)

        manual_name_entry = tk.Entry(self.root, textvariable=self.manual_folder_name_var)
        manual_name_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=8)

        manual_rename_button = tk.Button(
            self.root,
            text="Rename folder",
            command=self.rename_selected_folder,
        )
        manual_rename_button.grid(row=4, column=2, sticky="ew", padx=(8, 16), pady=8)

        types_frame = tk.LabelFrame(self.root, text="Document types")
        types_frame.grid(row=5, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 8))
        types_frame.columnconfigure(0, weight=1)
        types_frame.columnconfigure(1, weight=1)
        types_frame.columnconfigure(2, weight=1)

        self.types_listbox = tk.Listbox(types_frame, exportselection=False, height=5)
        self.types_listbox.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(12, 8), pady=12)
        self.types_listbox.bind("<<ListboxSelect>>", self.on_type_selection)

        type_label_label = tk.Label(types_frame, text="Label")
        type_label_label.grid(row=0, column=1, sticky="w", padx=(8, 12), pady=(12, 4))

        type_label_entry = tk.Entry(types_frame, textvariable=self.type_label_var)
        type_label_entry.grid(row=1, column=1, sticky="ew", padx=(8, 12))

        type_code_label = tk.Label(types_frame, text="Code")
        type_code_label.grid(row=0, column=2, sticky="w", padx=(0, 12), pady=(12, 4))

        type_code_entry = tk.Entry(types_frame, textvariable=self.type_code_var)
        type_code_entry.grid(row=1, column=2, sticky="ew", padx=(0, 12))

        type_keywords_label = tk.Label(types_frame, text="Keywords")
        type_keywords_label.grid(row=3, column=1, sticky="w", padx=(8, 12), pady=(8, 4))

        type_keywords_entry = tk.Entry(types_frame, textvariable=self.type_keywords_var)
        type_keywords_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 12))

        add_type_button = tk.Button(types_frame, text="Add / update", command=self.add_or_update_document_type)
        add_type_button.grid(row=5, column=1, sticky="ew", padx=(8, 12), pady=(8, 12))

        delete_type_button = tk.Button(types_frame, text="Delete", command=self.delete_document_type)
        delete_type_button.grid(row=5, column=2, sticky="ew", padx=(0, 12), pady=(8, 12))

        classification_frame = tk.LabelFrame(self.root, text="Document classification")
        classification_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=16, pady=(0, 8))
        classification_frame.columnconfigure(0, weight=1)
        classification_frame.columnconfigure(1, weight=0)
        classification_frame.rowconfigure(1, weight=1)

        queue_label = tk.Label(classification_frame, text="New files waiting for a document code")
        queue_label.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))

        queue_frame = tk.Frame(classification_frame)
        queue_frame.grid(row=1, column=0, sticky="nsew", padx=(12, 8), pady=(0, 12))
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)

        self.pending_listbox = tk.Listbox(queue_frame, exportselection=False, height=8)
        self.pending_listbox.grid(row=0, column=0, sticky="nsew")
        self.pending_listbox.bind("<<ListboxSelect>>", self.on_pending_selection)

        pending_scrollbar = tk.Scrollbar(queue_frame, orient="vertical", command=self.pending_listbox.yview)
        pending_scrollbar.grid(row=0, column=1, sticky="ns")
        self.pending_listbox.configure(yscrollcommand=pending_scrollbar.set)

        assignment_frame = tk.Frame(classification_frame)
        assignment_frame.grid(row=1, column=1, sticky="ns", padx=(8, 12), pady=(0, 12))

        document_type_label = tk.Label(assignment_frame, text="Document type")
        document_type_label.grid(row=0, column=0, sticky="w")

        self.document_type_combo = ttk.Combobox(
            assignment_frame,
            textvariable=self.document_type_var,
            values=list(self.document_types.keys()),
            state="readonly",
            width=24,
        )
        self.document_type_combo.grid(row=1, column=0, sticky="ew", pady=(4, 8))

        assign_button = tk.Button(
            assignment_frame,
            text="Assign type",
            command=self.assign_selected_document_type,
        )
        assign_button.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        rename_classified_button = tk.Button(
            assignment_frame,
            text="Rename classified files",
            command=self.rename_classified_files,
        )
        rename_classified_button.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        assignment_info_label = tk.Label(
            assignment_frame,
            textvariable=self.assignment_info_var,
            anchor="w",
            justify="left",
            wraplength=220,
        )
        assignment_info_label.grid(row=4, column=0, sticky="ew")

        controls = tk.Frame(self.root)
        controls.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=16, pady=(0, 16))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)

        self.toggle_button = tk.Button(
            controls,
            text="Start monitoring",
            command=self.toggle_monitoring,
        )
        self.toggle_button.grid(row=0, column=0, sticky="w", pady=(0, 8))

        status_label = tk.Label(
            controls,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
        )
        status_label.grid(row=0, column=0, sticky="ew", padx=(140, 0), pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(controls, wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.bind("<Key>", self.prevent_log_edit)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_document_type_widgets()

    def log(self, message: str):
        self.activity_logs.append(message)
        self.activity_logs = self.activity_logs[-12:]
        self.render_monitoring_output()

    def set_preview(self, lines: Sequence[str]):
        self.preview_files = {str(index): line for index, line in enumerate(lines)}
        self.render_monitoring_output()

    def prevent_log_edit(self, event):
        if (event.state & 0x4) and event.keysym.lower() in {"c", "a"}:
            return None
        if event.keysym in {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"}:
            return None
        return "break"

    def render_monitoring_output(self):
        sections = ["FILES PRESENTS"]

        if self.preview_files:
            sections.extend(self.preview_files[key] for key in sorted(self.preview_files))
        else:
            sections.append("Aucun fichier detecte.")

        sections.append("")
        sections.append("ACTIVITE RECENTE")

        if self.activity_logs:
            sections.extend(self.activity_logs)
        else:
            sections.append("Aucun evenement pour le moment.")

        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(sections))
        self.log_text.see("1.0")

    def current_settings(self) -> Path:
        folder = Path(self.folder_var.get()).expanduser()
        ensure_valid_folder(folder)
        return folder

    def known_codes(self) -> List[str]:
        return sorted(set(self.document_types.values()))

    def save_settings(self):
        try:
            folder = self.current_settings()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.config["default_folder"] = str(folder)
        self.config["document_types"] = self.document_types
        self.config["document_keywords"] = self.document_keywords
        self.config["auto_rename"] = self.auto_rename_var.get()
        save_config(self.config)
        self.status_var.set(f"Settings saved for {folder}")
        self.log(f"Saved folder: {folder}")

    def select_folder(self):
        selected = filedialog.askdirectory(
            title="Select the folder where the scanner saves files",
            initialdir=self.folder_var.get() or str(Path.home()),
        )
        if not selected:
            return

        self.folder_var.set(selected)
        self.save_settings()
        if self.monitoring:
            self.stop_monitoring()
        self.start_monitoring()

    def select_manual_folder(self):
        selected = filedialog.askdirectory(
            title="Select the folder to rename manually",
            initialdir=self.manual_folder_var.get() or self.folder_var.get() or str(Path.home()),
        )
        if not selected:
            return

        selected_path = Path(selected)
        self.manual_folder_var.set(selected)
        if not self.manual_folder_name_var.get().strip():
            self.manual_folder_name_var.set(selected_path.name)

    def rename_selected_folder(self):
        try:
            raw_folder = self.manual_folder_var.get().strip()
            if not raw_folder:
                raw_folder = self.folder_var.get().strip()
            if not raw_folder:
                raise ValueError("Select a folder to rename first.")

            target_folder = Path(raw_folder).expanduser()
            logs = rename_folder_manually(target_folder, self.manual_folder_name_var.get())
        except Exception as exc:
            messagebox.showerror("Folder rename error", str(exc))
            self.status_var.set(str(exc))
            return

        for line in logs:
            self.log(line)

        new_path = target_folder.with_name(self.manual_folder_name_var.get().strip())
        self.manual_folder_var.set(str(new_path))
        self.manual_folder_name_var.set(new_path.name)

        if self.folder_var.get() == str(target_folder):
            self.folder_var.set(str(new_path))
            self.config["default_folder"] = str(new_path)
            save_config(self.config)

        self.status_var.set(f"Folder renamed: {new_path}")
        if self.monitoring:
            self.stop_monitoring()
            self.start_monitoring()

    def refresh_document_type_widgets(self):
        labels = list(self.document_types.keys())
        self.types_listbox.delete(0, "end")
        for label in labels:
            self.types_listbox.insert("end", f"{label} -> {self.document_types[label]}")

        self.document_type_combo["values"] = labels
        if labels:
            current_type = self.document_type_var.get()
            if current_type not in self.document_types:
                self.document_type_var.set(labels[0])
            if not self.type_label_var.get().strip():
                self.type_label_var.set(self.document_type_var.get())
                self.type_code_var.set(self.document_types[self.document_type_var.get()])
                self.type_keywords_var.set(", ".join(self.document_keywords.get(self.document_type_var.get(), [])))

    def on_type_selection(self, _event=None):
        selection = self.types_listbox.curselection()
        if not selection:
            return

        label = list(self.document_types.keys())[selection[0]]
        self.type_label_var.set(label)
        self.type_code_var.set(self.document_types[label])
        self.type_keywords_var.set(", ".join(self.document_keywords.get(label, [])))
        self.document_type_var.set(label)

    def add_or_update_document_type(self):
        label = self.type_label_var.get().strip()
        raw_code = self.type_code_var.get().strip()

        if not label:
            messagebox.showerror("Document type error", "The label cannot be empty.")
            return

        try:
            code = normalize_code(raw_code)
        except Exception as exc:
            messagebox.showerror("Document type error", str(exc))
            return

        keywords = [keyword.strip().lower() for keyword in self.type_keywords_var.get().split(",") if keyword.strip()]
        self.document_types[label] = code
        self.document_keywords[label] = keywords
        self.refresh_document_type_widgets()
        self.config["document_types"] = self.document_types
        self.config["document_keywords"] = self.document_keywords
        save_config(self.config)
        try:
            folder = self.current_settings()
        except Exception:
            pass
        else:
            self.refresh_pending_list(folder)
            self.set_preview(build_existing_files_preview(folder, self.known_codes()))
        self.status_var.set(f"Saved document type: {label} -> {code}")

    def delete_document_type(self):
        selection = self.types_listbox.curselection()
        if not selection:
            messagebox.showerror("Document type error", "Select a document type to delete.")
            return
        if len(self.document_types) == 1:
            messagebox.showerror("Document type error", "Keep at least one document type.")
            return

        label = list(self.document_types.keys())[selection[0]]
        self.document_types.pop(label, None)
        self.document_keywords.pop(label, None)

        keys_to_remove = [
            key for key, assigned_label in self.pending_assignments.items() if assigned_label == label
        ]
        for key in keys_to_remove:
            self.pending_assignments.pop(key, None)

        self.type_label_var.set("")
        self.type_code_var.set("")
        self.type_keywords_var.set("")
        self.refresh_document_type_widgets()
        self.config["document_types"] = self.document_types
        self.config["document_keywords"] = self.document_keywords
        save_config(self.config)
        self.assignment_info_var.set("Select a file to classify.")
        try:
            folder = self.current_settings()
        except Exception:
            pass
        else:
            self.refresh_pending_list(folder)
            self.set_preview(build_existing_files_preview(folder, self.known_codes()))
        self.status_var.set(f"Deleted document type: {label}")

    def refresh_pending_list(self, folder: Path):
        current_selection = self.selected_pending_file()
        known_codes = self.known_codes()
        pending_files = collect_pending_files_for_codes(folder, known_codes)

        filtered_assignments = {}
        filtered_statuses = {}
        for file_path in pending_files:
            key = str(file_path)
            if key in self.pending_assignments:
                filtered_assignments[key] = self.pending_assignments[key]
            if key in self.pending_statuses:
                filtered_statuses[key] = self.pending_statuses[key]

        self.pending_assignments = filtered_assignments
        self.pending_statuses = filtered_statuses
        self.pending_paths = pending_files

        self.pending_listbox.delete(0, "end")
        for file_path in self.pending_paths:
            key = str(file_path)
            relative_path = str(file_path.relative_to(folder))
            status = self.pending_statuses.get(key, "Detected")
            assigned_label = self.pending_assignments.get(key, "-")
            self.pending_listbox.insert("end", f"[{status}] {relative_path}  ->  {assigned_label}")

        if current_selection:
            try:
                new_index = next(
                    index for index, file_path in enumerate(self.pending_paths) if file_path == current_selection
                )
            except StopIteration:
                self.assignment_info_var.set("Select a file to classify.")
            else:
                self.pending_listbox.selection_set(new_index)
                self.pending_listbox.activate(new_index)
                self.on_pending_selection()
                return

        if self.pending_paths:
            self.pending_listbox.selection_set(0)
            self.pending_listbox.activate(0)
            self.on_pending_selection()
        else:
            self.assignment_info_var.set("No unclassified files detected.")

    def selected_pending_file(self) -> Optional[Path]:
        selection = self.pending_listbox.curselection()
        if not selection:
            return None
        return self.pending_paths[selection[0]]

    def on_pending_selection(self, _event=None):
        selected_file = self.selected_pending_file()
        if selected_file is None:
            self.assignment_info_var.set("Select a file to classify.")
            return

        assigned_label = self.pending_assignments.get(str(selected_file))
        if assigned_label:
            self.document_type_var.set(assigned_label)
        else:
            self.document_type_var.set(next(iter(self.document_types)))

        code = self.document_types[self.document_type_var.get()]
        self.assignment_info_var.set(
            f"Selected: {selected_file.name}\nCode: {code}\nNew name preview: {code}_NNN{selected_file.suffix.lower()}"
        )

    def assign_selected_document_type(self):
        selected_file = self.selected_pending_file()
        if selected_file is None:
            messagebox.showerror("Assignment error", "Select a file to classify first.")
            return

        assigned_label = self.document_type_var.get().strip()
        if assigned_label not in self.document_types:
            messagebox.showerror("Assignment error", "Select a valid document type.")
            return

        self.pending_assignments[str(selected_file)] = assigned_label
        self.pending_statuses[str(selected_file)] = "Assigned"

        try:
            folder = self.current_settings()
        except Exception:
            return

        self.refresh_pending_list(folder)
        self.status_var.set(f"Assigned {assigned_label} to {selected_file.name}")

    def rename_classified_files(self):
        try:
            folder = self.current_settings()
        except Exception as exc:
            messagebox.showerror("Rename error", str(exc))
            self.status_var.set(str(exc))
            return

        files_to_rename = [
            file_path for file_path in self.pending_paths if str(file_path) in self.pending_assignments
        ]
        if not files_to_rename:
            messagebox.showerror("Rename error", "Assign a document type to at least one file first.")
            return

        try:
            plan = build_classified_rename_plan(
                folder,
                files_to_rename,
                self.pending_assignments,
                self.document_types,
            )
            validate_plan(plan)
            logs = apply_plan(plan, dry_run=False)
        except Exception as exc:
            messagebox.showerror("Rename error", str(exc))
            self.status_var.set(str(exc))
            return

        for line in logs:
            self.log(line)

        for file_path in files_to_rename:
            key = str(file_path)
            self.pending_assignments.pop(key, None)
            self.pending_statuses.pop(key, None)
            self.file_sizes.pop(f"file:{file_path}", None)

        self.refresh_pending_list(folder)
        self.set_preview(build_existing_files_preview(folder, self.known_codes()))
        self.status_var.set(f"Renamed {len(files_to_rename)} classified file(s).")

    def auto_detect_ready_files(self, folder: Path, ready_files: Sequence[Path]):
        auto_assignments: Dict[str, str] = {}
        detected_count = 0

        for file_path in ready_files:
            label, score, matches, detection_status = detect_document_type(
                file_path,
                self.document_types,
                self.document_keywords,
            )
            key = str(file_path)
            if label is None:
                if detection_status == "ocr_missing":
                    self.pending_statuses[key] = "OCR missing"
                    self.log(f"OCR not available for {file_path.name}. Install tesseract to read scanned images.")
                elif detection_status == "ocr_failed":
                    self.pending_statuses[key] = "OCR failed"
                    self.log(f"OCR could not read {file_path.name}. Verify the file format and tesseract installation.")
                elif detection_status.startswith("no_text_extracted"):
                    self.pending_statuses[key] = "No text"
                    self.log(f"No readable text found in {file_path.name}. OCR could not be applied.")
                elif detection_status == "ambiguous_match":
                    self.pending_statuses[key] = "Ambiguous"
                    self.log(f"Ambiguous detection for {file_path.name}. Multiple document types scored similarly.")
                elif detection_status == "low_confidence":
                    self.pending_statuses[key] = "Low confidence"
                    self.log(f"Low-confidence detection for {file_path.name}. Add stronger keywords or review manually.")
                else:
                    self.pending_statuses[key] = "Review"
                    self.log(f"No keyword match found for {file_path.name}. Check the configured keywords.")
                continue

            auto_assignments[key] = label
            self.pending_statuses[key] = "Auto"
            detected_count += 1
            self.log(
                f"Auto-detected {file_path.name} as {label} ({self.document_types[label]}) using: {', '.join(matches[:3])}"
            )

        if not auto_assignments:
            return 0

        files_to_rename = [file_path for file_path in ready_files if str(file_path) in auto_assignments]
        plan = build_classified_rename_plan(folder, files_to_rename, auto_assignments, self.document_types)
        validate_plan(plan)
        logs = apply_plan(plan, dry_run=False)

        for line in logs:
            self.log(line)

        for file_path in files_to_rename:
            key = str(file_path)
            self.pending_assignments.pop(key, None)
            self.pending_statuses.pop(key, None)
            self.file_sizes.pop(f"file:{file_path}", None)

        return detected_count

    def toggle_monitoring(self):
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        try:
            folder = self.current_settings()
        except Exception as exc:
            self.status_var.set(str(exc))
            return

        self.monitoring = True
        self.toggle_button.configure(text="Stop monitoring")
        self.status_var.set(f"Monitoring {folder}")
        self.log(f"Monitoring started: {folder}")
        self.set_preview(build_existing_files_preview(folder, self.known_codes()))
        self.refresh_pending_list(folder)
        self.monitor_folder()

    def stop_monitoring(self):
        self.monitoring = False
        self.file_sizes.clear()
        self.preview_files.clear()
        self.pending_statuses.clear()
        self.pending_paths.clear()
        self.pending_listbox.delete(0, "end")
        if self.monitor_after_id is not None:
            self.root.after_cancel(self.monitor_after_id)
            self.monitor_after_id = None
        self.toggle_button.configure(text="Start monitoring")
        self.status_var.set("Monitoring stopped.")
        self.log("Monitoring stopped.")
        self.render_monitoring_output()

    def schedule_monitor(self):
        if self.monitoring:
            self.monitor_after_id = self.root.after(MONITOR_INTERVAL_MS, self.monitor_folder)

    def monitor_folder(self):
        try:
            folder = self.current_settings()
            all_files = collect_all_files(folder)
            pending_files = collect_pending_files_for_codes(folder, self.known_codes())
            preview_map: Dict[str, str] = {}
            ready_files: List[Path] = []

            for file_path in all_files:
                key = f"file:{file_path}"
                relative_path = str(file_path.relative_to(folder))
                if is_named_for_any_code(file_path, self.known_codes()):
                    preview_map[key] = f"[Named] FILE {relative_path}"
                else:
                    preview_map[key] = f"[Detected] FILE {relative_path}"

            for file_path in pending_files:
                key = f"file:{file_path}"
                size = file_path.stat().st_size
                previous_size = self.file_sizes.get(key)
                relative_path = str(file_path.relative_to(folder))

                if previous_size is not None and previous_size == size:
                    preview_map[key] = f"[Ready] FILE {relative_path}"
                    self.pending_statuses[str(file_path)] = "Ready"
                    ready_files.append(file_path)
                else:
                    self.file_sizes[key] = size
                    preview_map[key] = f"[Writing] FILE {relative_path}"
                    self.pending_statuses[str(file_path)] = "Writing"

            self.file_sizes = {
                key: size for key, size in self.file_sizes.items() if key in {f"file:{path}" for path in pending_files}
            }
            self.preview_files = preview_map
            self.render_monitoring_output()

            auto_renamed = 0
            if self.auto_rename_var.get() and ready_files:
                try:
                    auto_renamed = self.auto_detect_ready_files(folder, ready_files)
                except Exception as exc:
                    self.log(f"Automatic detection error: {exc}")

            self.refresh_pending_list(folder)
            ready_count = sum(1 for file_path in pending_files if self.pending_statuses.get(str(file_path)) == "Ready")
            if auto_renamed:
                self.status_var.set(f"Monitoring {folder} | {auto_renamed} file(s) auto-renamed")
            else:
                self.status_var.set(f"Monitoring {folder} | {ready_count} file(s) ready for classification")
            self.set_preview(build_existing_files_preview(folder, self.known_codes()))

        except Exception as exc:
            self.status_var.set(f"Monitoring error: {exc}")
            self.log(f"Monitoring error: {exc}")

        self.schedule_monitor()

    def on_close(self):
        if self.monitoring:
            self.stop_monitoring()
        self.root.destroy()


def launch_gui():
    if tk is None:
        raise RuntimeError(
            "Tkinter is not available in this Python installation. Install Python with Tk support to use the GUI."
        ) from TK_IMPORT_ERROR
    root = tk.Tk()
    app = BatchRenamerApp(root)
    app.root.mainloop()


def run_cli(args):
    config = load_config()
    code = normalize_code(args.code or config.get("code"))
    folder = resolve_folder(args.folder, config)

    ensure_valid_folder(folder)

    if args.start < 1:
        raise ValueError("--start must be greater than or equal to 1.")

    if args.save_folder:
        config["default_folder"] = str(folder)
        config["code"] = code
        save_config(config)
        print(f"Default folder saved: {folder}")

    logs = rename_files(folder, code, start=args.start, dry_run=args.dry_run)
    for line in logs:
        print(line)


def main():
    args = parse_args()

    if args.gui or len(sys.argv) == 1:
        launch_gui()
        return

    run_cli(args)


if __name__ == "__main__":
    main()
