import argparse
import json
from pathlib import Path


CONFIG_FILE = Path(__file__).with_name(".batch_renamer.json")


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
        default="FAC",
        help="Acronym used for renamed files (default: FAC)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting number for the sequence (default: 1)",
    )
    parser.add_argument(
        "--extensions",
        default="pdf,png",
        help="Comma-separated list of extensions to rename (default: pdf,png)",
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
    return parser.parse_args()


def normalize_extensions(raw_extensions: str):
    extensions = set()

    for ext in raw_extensions.split(","):
        cleaned = ext.strip().lower().lstrip(".")
        if cleaned:
            extensions.add(f".{cleaned}")

    if not extensions:
        raise ValueError("At least one valid extension must be provided.")

    return extensions


def load_default_folder():
    if not CONFIG_FILE.exists():
        return None

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    folder = config.get("default_folder")
    return Path(folder).expanduser() if folder else None


def save_default_folder(folder: Path):
    CONFIG_FILE.write_text(
        json.dumps({"default_folder": str(folder)}, indent=2),
        encoding="utf-8",
    )


def resolve_folder(folder_arg: str | None):
    if folder_arg:
        return Path(folder_arg).expanduser()

    default_folder = load_default_folder()
    if default_folder:
        return default_folder

    raise ValueError(
        "No folder provided. Pass a folder path or save one with --save-folder."
    )


def collect_files(folder: Path, allowed_extensions):
    return sorted(
        [
            item
            for item in folder.iterdir()
            if item.is_file() and item.suffix.lower() in allowed_extensions
        ],
        key=lambda item: item.name.lower(),
    )


def build_rename_plan(files, code: str, start: int):
    plan = []

    for offset, file_path in enumerate(files, start=start):
        new_name = f"{code}_{offset:03}{file_path.suffix.lower()}"
        plan.append((file_path, file_path.with_name(new_name)))

    return plan


def validate_plan(plan):
    targets = [new_path.name for _, new_path in plan]

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


def apply_plan(plan, dry_run: bool):
    if not plan:
        print("No matching files found.")
        return

    for old_path, new_path in plan:
        print(f"{old_path.name} -> {new_path.name}")

    if dry_run:
        print("Dry run completed. No files were renamed.")
        return

    temporary_paths = []

    for index, (old_path, _) in enumerate(plan, start=1):
        temp_path = old_path.with_name(f".rename_tmp_{index:03}{old_path.suffix.lower()}")
        while temp_path.exists():
            temp_path = old_path.with_name(f"{temp_path.stem}_x{temp_path.suffix}")
        old_path.rename(temp_path)
        temporary_paths.append(temp_path)

    for temp_path, (_, new_path) in zip(temporary_paths, plan):
        temp_path.rename(new_path)

    print("Renaming completed.")


def main():
    args = parse_args()
    folder = resolve_folder(args.folder)
    allowed_extensions = normalize_extensions(args.extensions)

    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    if args.start < 1:
        raise ValueError("--start must be greater than or equal to 1.")

    if args.save_folder:
        save_default_folder(folder)
        print(f"Default folder saved: {folder}")

    files = collect_files(folder, allowed_extensions)
    plan = build_rename_plan(files, args.code.upper(), args.start)
    validate_plan(plan)
    apply_plan(plan, args.dry_run)


if __name__ == "__main__":
    main()
