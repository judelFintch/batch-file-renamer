# batch-file-renamer

A simple Python tool to rename PDF files in batch with a numbered format.

## Usage

```bash
python3 index.py /path/to/folder
```

Example:

```bash
python3 index.py ~/Desktop/test_files --prefix Facture --start 1 --dry-run
```

## Features

- Stable alphabetical sorting before renaming
- Only renames `.pdf` files
- Collision detection before changes
- Two-step renaming to avoid filename conflicts
- `--dry-run` mode to preview operations safely
