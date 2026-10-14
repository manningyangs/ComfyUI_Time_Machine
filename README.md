# ComfyUI Time Machine

> [English](README.md) · [中文](README_CN.md)

A complete **Scan → Snapshot → Diff → Restore** toolkit for Windows ComfyUI Portable environments.

![Status](https://img.shields.io/badge/status-alpha-orange)
![Python](https://img.shields.io/badge/python-3.11%20%2B%203.12-blue)
![OS](https://img.shields.io/badge/os-windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

> ⚠️ **Restore writes to the ComfyUI directory. Stop ComfyUI before running restore and always keep a recent snapshot as a safety point.**

---

## Features

- 🔍 **Read-only Scanner** — Detects ComfyUI Portable installations, collects Git status, Python environment, custom nodes, and configuration metadata
- 📸 **Content-Addressable Snapshots** — SHA-256 CAS storage, cross-snapshot deduplication, reference-count-based GC
- 📊 **Diff Comparison** — Current vs. Snapshot, or Snapshot vs. Snapshot
- 🔄 **Transactional Restore** — Staging area + protection-point backup + L1 hash verification + rollback capability
- 🖥️ **PySide6 GUI** — 6-page navigation, background workers, live progress bars
- 📦 **PyInstaller Package** — Single `ComfyUI_Time_Machine.exe`, no installation needed

## System Requirements

- **OS**: Windows 10 / 11
- **Python**: 3.11 or 3.12 (for running Time Machine itself — independent from ComfyUI's embedded Python)
- **ComfyUI**: Windows Portable variant (with a `ComfyUI/` subdirectory)

## Installation

```powershell
git clone https://github.com/manningyangs/ComfyUI_Time_Machine.git
cd ComfyUI_Time_Machine

# Create virtual environment (recommended)
py -3 -m venv .venv
.\.venv\Scripts\activate

# Core install (CLI + scanner + snapshot + restore — no GUI)
pip install -e .

# With GUI
pip install -e ".[gui]"

# Everything (dev + test + build)
pip install -e ".[dev,gui,build]"
```

## Usage

### 🖥️ GUI (Recommended)

```powershell
# From source
py -3 -m comfyui_time_machine --gui

# Or use the packaged exe
.\dist\ComfyUI_Time_Machine\ComfyUI_Time_Machine.exe
```

The GUI auto-detects common ComfyUI paths. If detection fails, click **⚙️ Configure** in the bottom-left to set the paths manually.

### 🗂️ Snapshot Storage Location

By default, snapshots are stored in `data/snapshots/` relative to the exe (or the project root when running from source). You can change this anytime:

1. Click **⚙️ Configure** in the bottom-left of the main window
2. Under **Snapshot Storage Location**, click **📂 Browse...** and pick any directory with enough disk space
3. Click **💾 Save**

> Switching storage locations does **not** delete old snapshots — it only changes which location the GUI reads from. A warning is shown if the old location still contains data.

### 🔧 CLI

```powershell
# Scan
py -3 -m comfyui_time_machine scan --root "D:\ComfyUI_windows_portable" --out "reports/scan.json"

# Version / Help
py -3 -m comfyui_time_machine --version
py -3 -m comfyui_time_machine --help
```

CLI arguments:

| Argument | Description |
|---|---|
| `--root` / `-r` | **Required**. Path to the ComfyUI root directory |
| `--out` / `-o` | Optional. Output path for the JSON scan report |
| `--verbose` / `-v` | Optional. Show detailed scanning progress |

## Restore Flow (Safety Rules)

Restore is the **only** operation that **writes** to the ComfyUI directory. When executed, it follows this strict sequence:

1. **Pre-flight checks** — Snapshot integrity, disk space, snapshot status
2. **Build staging** — Copy CAS blobs into staging area and re-verify SHA-256
3. **Protection-point backup** — Copy all files that will be overwritten into `recovery_tx/backup/`
4. **Atomic replace** — Overwrite/add target files from staging
5. **L1 hash verification** — Re-compute SHA-256 for every changed file; abort on mismatch
6. **Rollback capability** — Any failed phase preserves the protection point; call `rollback()` manually

## Running Tests

```powershell
py -3 -m pytest -q
# Expected: 101 passed
```

## Limitations

### ✅ What it *does* do
- Detects ComfyUI Portable / non-standard variants
- Collects core paths, Git status (read-only), custom nodes (Git / non-Git), Python environment, pip packages, config metadata
- Content-addressable snapshots (SHA-256 CAS + ref_count GC) with cross-snapshot deduplication
- Current vs. Snapshot diff
- Transactional restore + L1 hash verification
- PySide6 6-page GUI
- PyInstaller onedir packaging
- Full pytest regression suite (101 passed)

### ❌ What it **does NOT** do (by design — safety rules)
- Never deletes files not recorded in the snapshot (conservative policy — avoids wiping user models/outputs)
- Never scans model files, generated images, output directories, or caches (scope excludes)
- Never follows symlinks, junctions, or mount points
- Never writes secrets (`.env`, tokens, passwords) into reports
- Never runs `git pull`, `pip install`, `.bat`, or ComfyUI startup scripts
- Does **not** support ComfyUI Desktop, Linux, macOS, or multi-directory external nodes setups
- L2/L3 post-restore verification (ComfyUI launch check / workflow execution) is not yet implemented

## Verified on Real Hardware

Fully validated on **F:\2026-ComfyUI-V8.3** (45 custom nodes, 23 Git / 22 non-Git, 384 pip packages):

| Test | Result |
|---|---|
| Auto path detection (`python/` variant — not `python_embeded/`) | ✅ |
| Snapshot creation | ✅ 2.835 GB / 18,445 files / integrity_ok=1 |
| CAS deduplication | ✅ 18,445 → 17,873 unique blobs |
| Cross-snapshot sharing | ✅ Deleting one snapshot does not affect others |
| Full GC | ✅ After all snapshots removed, physical blob count = 0 |
| Modify file → Restore → Original state | ✅ L1 hash passes |
| Full diff after restore | ✅ Zero differences |

## Project Structure

```
src/comfyui_time_machine/
├── __init__.py          # Version
├── __main__.py          # python -m comfyui_time_machine (supports --gui)
├── cli.py               # CLI entry point
├── config.py            # Persistent settings (settings.json)
├── models.py            # Data models + JSON serialization
├── paths.py             # ComfyUI installation detection
├── safety.py            # Path safety (symlink check, escape guard)
├── scanners/            # Read-only scanners
│   ├── core.py
│   ├── custom_nodes.py
│   ├── python_env.py
│   └── configs.py
├── snapshots/           # Snapshot engine + restore engine
│   ├── scope.py
│   ├── store.py         # SQLite + CAS blobs + ref_count GC
│   ├── manager.py
│   ├── diff.py
│   └── restore.py
└── ui/                  # PySide6 GUI
    ├── state.py         # Cross-page AppState
    ├── main_window.py   # Main window (nav + stacked widget)
    ├── workers/         # Background workers
    │   ├── base.py
    │   ├── scan.py
    │   ├── snapshot_create.py
    │   ├── snapshot_delete.py
    │   └── restore.py
    └── pages/           # 6 pages
        ├── home.py
        ├── scan.py
        ├── snapshots.py
        ├── compare.py
        ├── restore.py
        └── verify.py
```

## License

MIT © ComfyUI Time Machine Contributors
