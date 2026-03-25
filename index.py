import argparse
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rename PDF files in a folder using a numbered pattern."
    )
    parser.add_argument("folder", help="Path to the folder containing the PDF files")
    parser.add_argument(
        "--prefix",
        default="Facture",
        help="Prefix used for renamed files (default: Facture)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting number for the sequence (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the rename operations without changing files",
    )
    return parser.parse_args()


def collect_pdf_files(folder: Path):
    return sorted(
        [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".pdf"],
        key=lambda item: item.name.lower(),
    )


def build_rename_plan(files, prefix: str, start: int):
    plan = []

    for offset, file_path in enumerate(files, start=start):
        new_name = f"{prefix}_{offset:03}.pdf"
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
        print("No PDF files found.")
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
    folder = Path(args.folder).expanduser()

    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    if args.start < 1:
        raise ValueError("--start must be greater than or equal to 1.")

    files = collect_pdf_files(folder)
    plan = build_rename_plan(files, args.prefix, args.start)
    validate_plan(plan)
    apply_plan(plan, args.dry_run)


if __name__ == "__main__":
    main()
