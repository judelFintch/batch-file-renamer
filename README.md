# batch-file-renamer

A simple Python CLI tool to rename PDF files in batch with a numbered format.

## Overview

This script scans a folder, keeps only PDF files, sorts them alphabetically, and renames them using a sequential pattern such as:

```text
Facture_001.pdf
Facture_002.pdf
Facture_003.pdf
```

It is designed to be safer than a basic one-pass rename script:

- It only targets `.pdf` files
- It validates conflicts before changing anything
- It uses a two-step rename process to avoid filename collisions
- It provides a preview mode with `--dry-run`

## Requirements

- Python 3.8 or newer
- A folder containing PDF files to rename

No external dependency is required.

## Installation

Clone the repository and run the script directly:

```bash
git clone <your-repo-url>
cd batch-file-renamer
python3 index.py --help
```

## Usage

```bash
python3 index.py /path/to/folder
```

Example:

```bash
python3 index.py ~/Desktop/test_files --prefix Facture --start 1 --dry-run
```

## Command Options

```bash
python3 index.py <folder> [--prefix PREFIX] [--start NUMBER] [--dry-run]
```

Arguments:

- `folder`: path to the directory containing the PDF files

Options:

- `--prefix`: sets the filename prefix, default is `Facture`
- `--start`: sets the first sequence number, default is `1`
- `--dry-run`: prints the rename plan without modifying any file

## Features

- Stable alphabetical sorting before renaming
- Only renames `.pdf` files
- Collision detection before changes
- Two-step renaming to avoid filename conflicts
- `--dry-run` mode to preview operations safely

## Examples

Rename all PDF files in a folder with the default prefix:

```bash
python3 index.py ~/Desktop/test_files
```

Start numbering at `25`:

```bash
python3 index.py ~/Desktop/test_files --start 25
```

Use a custom prefix:

```bash
python3 index.py ~/Desktop/test_files --prefix Invoice
```

Preview the result without changing files:

```bash
python3 index.py ~/Desktop/test_files --dry-run
```

## How It Works

1. The script checks that the provided path exists and is a directory.
2. It collects only files ending with `.pdf`.
3. It sorts them alphabetically in a case-insensitive way.
4. It builds a rename plan like `Prefix_001.pdf`, `Prefix_002.pdf`, and so on.
5. It validates that no target filename already exists.
6. It renames files through temporary names first, then applies final names.

## Example Output

```text
old_document.pdf -> Facture_001.pdf
scan_2024.pdf -> Facture_002.pdf
Dry run completed. No files were renamed.
```

## Safety Notes

- Non-PDF files are ignored
- Existing target files stop the process before renaming starts
- Numbering below `1` is rejected
- If no PDF file is found, the script exits cleanly with a message

## Limitations

- The output format is fixed to `PREFIX_XXX.pdf`
- It does not recurse into subfolders
- It does not preserve original filenames

## Project Structure

```text
batch-file-renamer/
├── index.py
└── README.md
```
