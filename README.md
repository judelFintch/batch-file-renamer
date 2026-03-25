# batch-file-renamer

Python tool to rename scanned files with an acronym and an automatic sequence.

## What It Does

The project now includes:

- a graphical interface to choose the scanner folder
- saved settings so the selected folder is remembered
- automatic monitoring of the folder
- automatic renaming of new scanned files
- CLI support if you still want to run it from the terminal

Example output names:

```text
FAC_001.pdf
FAC_002.png
CLI_003.pdf
```

## Supported Files

By default, the app watches and renames:

- `.pdf`
- `.png`

You can change the extensions list from the GUI or the CLI.

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
- enter an acronym such as `FAC`, `CLI`, `ORD`, `BL`
- define the allowed extensions
- save the settings
- rename current files immediately
- start or stop automatic monitoring

## Saved Folder and Settings

When you select a folder and save the settings, the app stores:

- the default folder
- the acronym
- the extensions list

These settings are saved in:

```text
.batch_renamer.json
```

The next time you open the app, it reloads the saved folder and starts monitoring it automatically if the folder still exists.

## Automatic Detection

The GUI checks the selected folder every few seconds.

When a new scan appears:

1. the app waits until the file size stops changing
2. it considers the file stable
3. it renames it automatically

This avoids renaming a file while the scanner is still writing it.

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
- `CLI_003.pdf`

The original extension is preserved.

## Basic GUI Workflow

1. Run `python3 index.py`
2. Click `Browse`
3. Select the folder where your scanner saves files
4. Enter your acronym, for example `FAC`
5. Click `Save settings`
6. Click `Rename now` for existing files if needed
7. Leave monitoring enabled for future scans

## CLI Usage

You can still use the terminal mode.

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

Rename only PNG files:

```bash
python3 index.py ~/Desktop/scans --code IMG --extensions png
```

Save a default folder from the CLI:

```bash
python3 index.py ~/Desktop/scans --code FAC --save-folder --dry-run
```

## CLI Options

```bash
python3 index.py [folder] [--code CODE] [--start NUMBER] [--extensions LIST] [--save-folder] [--dry-run] [--gui]
```

Options:

- `folder`: folder containing the files to rename
- `--code`: acronym for the new filenames
- `--start`: first number in the sequence for CLI batch renaming
- `--extensions`: comma-separated extensions such as `pdf,png,jpg`
- `--save-folder`: save the folder and current settings
- `--dry-run`: preview mode, no file is changed
- `--gui`: launch the graphical interface

## How Renaming Works

1. The app loads the saved settings or the values you enter.
2. It filters files by extension.
3. It ignores files already named like `CODE_001`.
4. It finds the next available number for the selected acronym.
5. It renames new files safely through temporary names.

## Safety Notes

- Existing target files block the operation before changes are applied
- Files already using the numbered acronym format are ignored by the watcher
- Unsupported extensions are ignored
- The original extension is preserved

## Requirements

- Python 3
- `tkinter` available in your Python installation

No external dependency is required.
