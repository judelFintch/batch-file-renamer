import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
except ModuleNotFoundError as exc:
    tk = None
    filedialog = None
    messagebox = None
    scrolledtext = None
    TK_IMPORT_ERROR = exc
else:
    TK_IMPORT_ERROR = None


CONFIG_FILE = Path(__file__).with_name(".batch_renamer.json")
DEFAULT_CODE = "FAC"
DEFAULT_EXTENSIONS = "pdf,png"
MONITOR_INTERVAL_MS = 2000
NUMBERED_NAME_PATTERN = re.compile(r"^(?P<code>[A-Z0-9]+)_(?P<number>\d+)$")


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
        "--extensions",
        default=None,
        help=f"Comma-separated list of extensions to rename (default: {DEFAULT_EXTENSIONS})",
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


def normalize_extensions(raw_extensions: Optional[str]) -> Set[str]:
    source = raw_extensions or DEFAULT_EXTENSIONS
    extensions = set()

    for ext in source.split(","):
        cleaned = ext.strip().lower().lstrip(".")
        if cleaned:
            extensions.add(f".{cleaned}")

    if not extensions:
        raise ValueError("At least one valid extension must be provided.")

    return extensions


def format_extensions(extensions: Iterable[str]) -> str:
    return ",".join(sorted(ext.lstrip(".") for ext in extensions))


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


def collect_files(folder: Path, allowed_extensions: Set[str]) -> List[Path]:
    return sorted(
        [
            item
            for item in folder.rglob("*")
            if item.is_file()
            and item.suffix.lower() in allowed_extensions
            and not item.name.startswith(".rename_tmp_")
        ],
        key=lambda item: (str(item.parent).lower(), item.name.lower()),
    )


def is_numbered_name(file_path: Path) -> bool:
    return NUMBERED_NAME_PATTERN.fullmatch(file_path.stem) is not None


def next_sequence_number(
    folder: Path,
    code: str,
    allowed_extensions: Set[str],
    minimum: int = 1,
) -> int:
    highest = minimum - 1

    for file_path in collect_files(folder, allowed_extensions):
        match = NUMBERED_NAME_PATTERN.fullmatch(file_path.stem)
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

    logs = [f"{old_path.name} -> {new_path.name}" for old_path, new_path in plan]

    if dry_run:
        logs.append("Dry run completed. No files were renamed.")
        return logs

    temporary_paths = []

    for index, (old_path, _) in enumerate(plan, start=1):
        temp_path = old_path.with_name(f".rename_tmp_{index:03}{old_path.suffix.lower()}")
        while temp_path.exists():
            temp_path = old_path.with_name(f"{temp_path.stem}_x{temp_path.suffix}")
        old_path.rename(temp_path)
        temporary_paths.append(temp_path)

    for temp_path, (_, new_path) in zip(temporary_paths, plan):
        temp_path.rename(new_path)

    logs.append("Renaming completed.")
    return logs


def collect_pending_files(folder: Path, allowed_extensions: Set[str]) -> List[Path]:
    return [file_path for file_path in collect_files(folder, allowed_extensions) if not is_numbered_name(file_path)]


def build_existing_files_preview(folder: Path, allowed_extensions: Set[str]) -> List[str]:
    preview_lines = []

    for file_path in collect_files(folder, allowed_extensions):
        relative_path = str(file_path.relative_to(folder))
        status = "[Named]" if is_numbered_name(file_path) else "[Detected]"
        preview_lines.append(f"{status} {relative_path}")

    return preview_lines


def rename_files(
    folder: Path,
    code: str,
    allowed_extensions: Set[str],
    start: Optional[int] = None,
    dry_run: bool = False,
    files: Optional[Sequence[Path]] = None,
) -> List[str]:
    ensure_valid_folder(folder)
    source_files = list(files) if files is not None else collect_pending_files(folder, allowed_extensions)

    if not source_files:
        return ["No matching files found."]

    starting_number = start if start is not None else next_sequence_number(folder, code, allowed_extensions)
    plan = build_rename_plan(source_files, code, starting_number)
    validate_plan(plan)
    return apply_plan(plan, dry_run)


class BatchRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Batch File Renamer")
        self.root.geometry("760x520")

        self.config = load_config()
        self.monitoring = False
        self.monitor_after_id = None
        self.file_sizes: Dict[str, int] = {}
        self.preview_files: Dict[str, str] = {}

        self.folder_var = tk.StringVar(value=self.config.get("default_folder", ""))
        self.code_var = tk.StringVar(value=self.config.get("code", DEFAULT_CODE))
        self.extensions_var = tk.StringVar(
            value=self.config.get("extensions", DEFAULT_EXTENSIONS)
        )
        self.status_var = tk.StringVar(value="Select a folder to start monitoring.")

        self.build_ui()

        if self.folder_var.get():
            self.start_monitoring()

    def build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(4, weight=1)

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

        code_label = tk.Label(self.root, text="Acronym")
        code_label.grid(row=2, column=0, sticky="w", padx=16, pady=8)

        code_entry = tk.Entry(self.root, textvariable=self.code_var)
        code_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=8)

        ext_label = tk.Label(self.root, text="Extensions")
        ext_label.grid(row=3, column=0, sticky="w", padx=16, pady=8)

        ext_entry = tk.Entry(self.root, textvariable=self.extensions_var)
        ext_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=8)

        save_button = tk.Button(self.root, text="Save settings", command=self.save_settings)
        save_button.grid(row=2, column=2, sticky="ew", padx=(8, 16), pady=8)

        rename_button = tk.Button(self.root, text="Rename now", command=self.rename_now)
        rename_button.grid(row=3, column=2, sticky="ew", padx=(8, 16), pady=8)

        controls = tk.Frame(self.root)
        controls.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=16, pady=(8, 16))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(2, weight=1)

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

        preview_label = tk.Label(controls, text="Preview of detected files")
        preview_label.grid(row=1, column=0, sticky="w")

        self.preview_text = scrolledtext.ScrolledText(controls, height=8, state="disabled", wrap="word")
        self.preview_text.grid(row=2, column=0, sticky="nsew", pady=(4, 8))

        self.log_text = scrolledtext.ScrolledText(controls, state="disabled", wrap="word")
        self.log_text.grid(row=3, column=0, sticky="nsew")
        controls.rowconfigure(3, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_preview(self, lines: Sequence[str]):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        if lines:
            self.preview_text.insert("end", "\n".join(lines))
        else:
            self.preview_text.insert("end", "No new files detected.")

        self.preview_text.configure(state="disabled")

    def current_settings(self) -> Tuple[Path, str, Set[str]]:
        folder = Path(self.folder_var.get()).expanduser()
        code = normalize_code(self.code_var.get())
        extensions = normalize_extensions(self.extensions_var.get())
        ensure_valid_folder(folder)
        return folder, code, extensions

    def save_settings(self):
        try:
            folder, code, extensions = self.current_settings()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.config["default_folder"] = str(folder)
        self.config["code"] = code
        self.config["extensions"] = format_extensions(extensions)
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

    def rename_now(self):
        try:
            folder, code, extensions = self.current_settings()
            logs = rename_files(folder, code, extensions)
        except Exception as exc:
            messagebox.showerror("Rename error", str(exc))
            self.status_var.set(str(exc))
            return

        for line in logs:
            self.log(line)
        self.status_var.set("Manual rename completed.")

    def toggle_monitoring(self):
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        try:
            folder, _, extensions = self.current_settings()
        except Exception as exc:
            self.status_var.set(str(exc))
            return

        self.monitoring = True
        self.toggle_button.configure(text="Stop monitoring")
        self.status_var.set(f"Monitoring {folder}")
        self.log(f"Monitoring started: {folder}")
        self.set_preview(build_existing_files_preview(folder, extensions))
        self.schedule_monitor()

    def stop_monitoring(self):
        self.monitoring = False
        self.file_sizes.clear()
        self.preview_files.clear()
        if self.monitor_after_id is not None:
            self.root.after_cancel(self.monitor_after_id)
            self.monitor_after_id = None
        self.toggle_button.configure(text="Start monitoring")
        self.status_var.set("Monitoring stopped.")
        self.log("Monitoring stopped.")
        self.set_preview([])

    def schedule_monitor(self):
        if self.monitoring:
            self.monitor_after_id = self.root.after(MONITOR_INTERVAL_MS, self.monitor_folder)

    def monitor_folder(self):
        try:
            folder, code, extensions = self.current_settings()
            all_files = collect_files(folder, extensions)
            pending_files = collect_pending_files(folder, extensions)

            stable_files = []
            seen_keys = set()
            preview_map: Dict[str, str] = {}

            for file_path in all_files:
                key = str(file_path)
                relative_path = str(file_path.relative_to(folder))
                if is_numbered_name(file_path):
                    preview_map[key] = f"[Named] {relative_path}"

            for file_path in pending_files:
                key = str(file_path)
                size = file_path.stat().st_size
                previous_size = self.file_sizes.get(key)
                relative_path = str(file_path.relative_to(folder))

                if previous_size is not None and previous_size == size:
                    stable_files.append(file_path)
                    preview_map[key] = f"[Ready] {relative_path}"
                else:
                    self.file_sizes[key] = size
                    preview_map[key] = f"[Writing] {relative_path}"

                seen_keys.add(key)

            self.file_sizes = {
                key: size for key, size in self.file_sizes.items() if key in seen_keys
            }
            self.preview_files = preview_map
            self.set_preview([self.preview_files[key] for key in sorted(self.preview_files)])

            if stable_files:
                logs = rename_files(folder, code, extensions, files=stable_files)
                for line in logs:
                    self.log(line)
                self.status_var.set(f"Detected and renamed {len(stable_files)} new file(s).")

                for file_path in stable_files:
                    self.file_sizes.pop(str(file_path), None)
                    self.preview_files.pop(str(file_path), None)

                self.set_preview([self.preview_files[key] for key in sorted(self.preview_files)])
            else:
                self.status_var.set(f"Monitoring {folder}")

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
    extensions = normalize_extensions(args.extensions or config.get("extensions"))
    folder = resolve_folder(args.folder, config)

    ensure_valid_folder(folder)

    if args.start < 1:
        raise ValueError("--start must be greater than or equal to 1.")

    if args.save_folder:
        config["default_folder"] = str(folder)
        config["code"] = code
        config["extensions"] = format_extensions(extensions)
        save_config(config)
        print(f"Default folder saved: {folder}")

    logs = rename_files(folder, code, extensions, start=args.start, dry_run=args.dry_run)
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
