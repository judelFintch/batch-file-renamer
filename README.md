# batch-file-renamer

Python CLI tool to rename scanned files with an acronym and a sequence number.

## Use Case

If you scan documents as `.pdf` or `.png`, you can rename them automatically with short codes such as:

```text
FAC_001.pdf
FAC_002.png
CLI_003.pdf
ORD_004.png
```

This is useful when you want acronyms instead of full names like `Facture_001.pdf`.

## Supported Files

By default, the script renames:

- `.pdf`
- `.png`

You can also choose other extensions with `--extensions`.

## Basic Usage

```bash
python3 index.py /path/to/folder --code FAC
```

Example:

```bash
python3 index.py ~/Desktop/scans --code FAC
```

This can produce names like:

```text
FAC_001.pdf
FAC_002.png
FAC_003.pdf
```

## Using Acronyms

Use `--code` to define the acronym:

```bash
python3 index.py ~/Desktop/scans --code FAC
python3 index.py ~/Desktop/scans --code CLI
python3 index.py ~/Desktop/scans --code ORD
```

Examples:

- `FAC` for facture
- `CLI` for client
- `ORD` for ordonnance
- `BL` for bon de livraison

The script automatically converts the code to uppercase.

## Connect Your Folder Directly

If you always use the same folder, save it once:

```bash
python3 index.py ~/Desktop/scans --save-folder --dry-run
```

After that, you can run the script without giving the folder again:

```bash
python3 index.py --code FAC
```

The default folder is saved in:

```text
.batch_renamer.json
```

## Command Options

```bash
python3 index.py [folder] [--code CODE] [--start NUMBER] [--extensions LIST] [--save-folder] [--dry-run]
```

Options:

- `folder`: folder containing the files to rename
- `--code`: acronym for the new filenames, default is `FAC`
- `--start`: first number in the sequence, default is `1`
- `--extensions`: comma-separated extensions, default is `pdf,png`
- `--save-folder`: saves the folder as the default folder
- `--dry-run`: preview mode, no file is changed

## Examples

Preview the rename operations:

```bash
python3 index.py ~/Desktop/scans --code FAC --dry-run
```

Start from `25`:

```bash
python3 index.py ~/Desktop/scans --code FAC --start 25
```

Rename only PNG files:

```bash
python3 index.py ~/Desktop/scans --code IMG --extensions png
```

Rename PDF and JPG files:

```bash
python3 index.py ~/Desktop/scans --code DOC --extensions pdf,jpg,jpeg
```

Use the saved folder:

```bash
python3 index.py --code CLI --dry-run
```

## How It Works

1. The script takes the folder you pass, or the saved default folder.
2. It filters files by extension.
3. It sorts them alphabetically.
4. It creates names like `CODE_001.ext`.
5. It checks for naming conflicts before changing anything.
6. It renames files through temporary names to avoid collisions.

## Safety

- Existing target files stop the process before renaming starts
- Unsupported files are ignored
- `--dry-run` lets you verify before applying changes
- The original extension is preserved

## Notes

- The script does not scan subfolders
- The numbering format is fixed to three digits: `001`, `002`, `003`
- No external library is required
