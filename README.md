# batch-file-renamer

Python tool to monitor a scanner folder and rename files with an acronym plus an automatic sequence.

## What It Does

The project includes:

- a GUI to choose the scanner folder
- saved settings for the folder and acronym
- recursive monitoring of the selected folder and its subfolders
- automatic detection of files created by the scanner
- automatic renaming with a sequence such as `FAC_001`
- CLI support for batch renaming from the terminal

Example output names:

```text
FAC_001.pdf
FAC_002.jpg
FAC_003
```

The original suffix is preserved when the file has one.

## Graphical Interface

Start the app:

```bash
python3 index.py
```

Or explicitly:

```bash
python3 index.py --gui
```

The interface lets you:

- browse and select the folder used by the scanner
- open a dedicated `Configuration` window for settings and API parameters
- open a dedicated `Learn Files` window for study files and learned samples
- optionally enable an AI agent workflow for autonomous routing and renaming review
- rename current files immediately
- start or stop automatic monitoring

## Monitoring View

The monitoring panel shows two sections:

- `FILES PRESENTS`: files currently found in the selected folder and all subfolders
- `ACTIVITE RECENTE`: recent monitoring and renaming events

Displayed states:

- `[Present]`: file found and not yet renamed for the active code
- `[Detected]`: file currently tracked by monitoring
- `[Writing]`: file is still changing size, so the app waits
- `[Ready]`: file is stable and ready to be renamed
- `[Named]`: file already renamed with the active code

## Automatic Detection

The GUI checks the selected folder every few seconds.

When a file appears:

1. the app detects it recursively, including inside subfolders
2. it waits until the file size stops changing
3. it renames the file automatically

This prevents renaming a file while the scanner is still writing it.

For scanned images and image-only PDFs, the app will try OCR through `tesseract` when no embedded text is available.

You can also train each document type from multiple real sample files. The app stores all learned references, lets you remove a bad sample, and uses the strongest matching examples to classify future scans.

You can store the real API settings directly in the `Configuration` window, including the API token, model, and responses URL. The AI agent reads the extracted text, compares it with your learned references, auto-renames high-confidence files, and sends medium-confidence files to human review.

## Naming Format

The app renames files like this:

```text
CODE_001.ext
CODE_002.ext
CODE_003.ext
```

Examples:

- `FAC_001.pdf`
- `FAC_002.png`
- `CLI_003.docx`

The current code is important:

- files already named with the active code are treated as done
- files named with another code can still be renamed with the current code

## Basic GUI Workflow

1. Run `python3 index.py`
2. Click `Configuration`
3. Select the parent folder used by the scanner and save the settings
4. If needed, add the API token, model, and thresholds
5. Click `Learn Files` and upload sample documents for each rename target
6. Review detected files in the renaming area
7. Leave monitoring enabled for future scans

## Saved Settings

When you save the settings, the app stores:

- the default folder
- the acronym

These settings are saved in:

```text
.batch_renamer.json
```

The next time you open the app, it reloads the saved folder and starts monitoring it automatically if the folder still exists.

## CLI Usage

Basic command:

```bash
python3 index.py /path/to/folder --code FAC
```

If a default folder is already saved:

```bash
python3 index.py --code FAC
```

Preview only:

```bash
python3 index.py ~/Desktop/scans --code FAC --dry-run
```

Save a default folder from the CLI:

```bash
python3 index.py ~/Desktop/scans --code FAC --save-folder --dry-run
```

## CLI Options

```bash
python3 index.py [folder] [--code CODE] [--start NUMBER] [--save-folder] [--dry-run] [--gui]
```

Options:

- `folder`: folder containing the files to rename
- `--code`: acronym for the new filenames
- `--start`: first number in the sequence for CLI batch renaming
- `--save-folder`: save the folder and current settings
- `--dry-run`: preview mode, no file is changed
- `--gui`: launch the graphical interface

## How Renaming Works

1. The app loads the saved settings or the values you enter.
2. It scans all files recursively in the selected folder.
3. It ignores only files already named with the active code.
4. It finds the next available number for that code.
5. It renames files safely through temporary names.

## Safety Notes

- Existing target files block the operation before changes are applied
- Files are renamed only after they become stable
- The original suffix is preserved
- Hidden temporary rename files are ignored by the scanner

## Requirements

- Python 3
- `tkinter` available in your Python installation

Optional for scanned images and image-only PDFs:

- `tesseract`

Optional for the AI agent workflow:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` to override the default model (`gpt-4o-mini`)
