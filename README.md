# ComfyUI Time Machine

Windows ComfyUI Portable 环境的 **Scan → Snapshot → Diff → Restore** 全链路工具 · Scan, snapshot, diff, and restore Windows ComfyUI Portable environments.

![Status](https://img.shields.io/badge/status-alpha-orange)
![Python](https://img.shields.io/badge/python-3.11%20%2B%203.12-blue)
![OS](https://img.shields.io/badge/os-windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 📖 Table of Contents · 目录

- [English](#-english)
- [中文](#-中文)

---

## 🇬🇧 English

> ⚠️ **Restore writes to the ComfyUI directory. Stop ComfyUI before running restore and always keep a recent snapshot as a safety point.**

### Features

- 🔍 **Read-only Scanner** — Detects ComfyUI Portable installations, collects Git status, Python environment, custom nodes, and configuration metadata
- 📸 **Content-Addressable Snapshots** — SHA-256 CAS storage, cross-snapshot deduplication, reference-count-based GC
- 📊 **Diff Comparison** — Current vs. Snapshot, or Snapshot vs. Snapshot
- 🔄 **Transactional Restore** — Staging area + protection-point backup + L1 hash verification + rollback capability
- 🖥️ **PySide6 GUI** — 6-page navigation, background workers, live progress bars
- 📦 **PyInstaller Package** — Single `ComfyUI_Time_Machine.exe`, no installation needed

### System Requirements

- **OS**: Windows 10 / 11
- **Python**: 3.11 or 3.12 (independent from ComfyUI's embedded Python)
- **ComfyUI**: Windows Portable variant (with a `ComfyUI/` subdirectory)

### Installation

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

### Usage

#### GUI (Recommended)

```powershell
# From source
py -3 -m comfyui_time_machine --gui

# Or use the packaged exe
.\dist\ComfyUI_Time_Machine\ComfyUI_Time_Machine.exe
```

The GUI auto-detects common ComfyUI paths. If detection fails, click **⚙️ Configure** in the bottom-left to set paths manually.

#### Snapshot Storage Location

By default, snapshots are stored in `data/snapshots/` relative to the exe (or project root when running from source). Change anytime via **⚙️ Configure → Snapshot Storage Location**. Switching locations does **not** delete old snapshots.

#### CLI

```powershell
py -3 -m comfyui_time_machine scan --root "D:\ComfyUI_windows_portable" --out "reports/scan.json"
py -3 -m comfyui_time_machine --version
```

| Argument | Description |
|---|---|
| `--root` / `-r` | **Required**. Path to the ComfyUI root directory |
| `--out` / `-o` | Optional. Output path for the JSON scan report |
| `--verbose` / `-v` | Optional. Show detailed scanning progress |

### Restore Flow (Safety Rules)

Restore is the **only** operation that **writes** to the ComfyUI directory. Strict sequence:

1. **Pre-flight checks** — Snapshot integrity, disk space, snapshot status
2. **Build staging** — Copy CAS blobs into staging area and re-verify SHA-256
3. **Protection-point backup** — Copy all files to be overwritten into `recovery_tx/backup/`
4. **Atomic replace** — Overwrite/add target files from staging
5. **L1 hash verification** — Re-compute SHA-256 for every changed file; abort on mismatch
6. **Rollback capability** — Any failed phase preserves the protection point

### Running Tests

```powershell
py -3 -m pytest -q
# Expected: 101 passed
```

### Limitations

**Does ✅**
- Detects ComfyUI Portable / non-standard variants
- Content-addressable snapshots with cross-snapshot dedup
- Current vs. Snapshot diff
- Transactional restore + L1 hash verification
- PySide6 6-page GUI
- Full pytest regression suite (101 passed)

**Does NOT ❌** (by design — safety rules)
- Never deletes files not recorded in the snapshot (conservative policy)
- Never scans model files, generated images, outputs, or caches
- Never follows symlinks, junctions, or mount points
- Never writes secrets (`.env`, tokens, passwords) into reports
- Never runs `git pull`, `pip install`, `.bat`, or ComfyUI startup scripts
- Does **not** support ComfyUI Desktop, Linux, or macOS

### Verified on Real Hardware

Fully validated on **F:\2026-ComfyUI-V8.3** (45 custom nodes, 384 pip packages, 2.835 GB / 18,445 files):

| Test | Result |
|---|---|
| Auto path detection | ✅ |
| Snapshot creation | ✅ integrity_ok=1 |
| CAS deduplication | ✅ 18,445 → 17,873 unique blobs |
| Cross-snapshot sharing | ✅ |
| Full GC | ✅ blob count = 0 after all deleted |
| Modify → Restore → Original | ✅ L1 hash passes |

### Project Structure

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
├── snapshots/           # Snapshot + restore engine
│   ├── scope.py
│   ├── store.py         # SQLite + CAS blobs + ref_count
│   ├── manager.py
│   ├── diff.py
│   └── restore.py
└── ui/                  # PySide6 GUI
    ├── state.py
    ├── main_window.py
    ├── workers/         # Background workers
    └── pages/           # 6 pages: home, scan, snapshots, compare, restore, verify
```

---

## 🇨🇳 中文

> ⚠️ **恢复功能会修改 ComfyUI 目录文件，使用前请先停止 ComfyUI 并确保有近期快照作为保护点。**

### 功能特性

- 🔍 **只读扫描** —— 识别 ComfyUI Portable 安装，采集 Git 状态、Python 环境、自定义节点、配置文件
- 📸 **内容寻址快照** —— SHA-256 CAS，跨快照去重，引用计数垃圾回收
- 📊 **差异比较** —— 当前 vs 快照 / 快照 vs 快照
- 🔄 **事务化恢复** —— staging 暂存 + 保护点备份 + L1 哈希验证 + 回滚能力
- 🖥️ **PySide6 GUI** —— 6 页导航，后台线程，进度实时显示
- 📦 **PyInstaller 打包** —— `ComfyUI_Time_Machine.exe` 绿色即用

### 系统要求

- **操作系统**：Windows 10 / 11
- **Python**：3.11 或 3.12（独立于 ComfyUI 的嵌入式 Python）
- **支持的 ComfyUI**：Windows Portable（含 `ComfyUI/` 子目录）

### 安装

```powershell
git clone https://github.com/manningyangs/ComfyUI_Time_Machine.git
cd ComfyUI_Time_Machine

# 创建虚拟环境（推荐）
py -3 -m venv .venv
.\.venv\Scripts\activate

# 核心安装（CLI + 扫描 + 快照 + 恢复 —— 无 GUI）
pip install -e .

# 带 GUI
pip install -e ".[gui]"

# 全部（含测试 + 打包）
pip install -e ".[dev,gui,build]"
```

### 使用

#### GUI（推荐）

```powershell
# 开发环境运行
py -3 -m comfyui_time_machine --gui

# 或直接用打包后的 exe
.\dist\ComfyUI_Time_Machine\ComfyUI_Time_Machine.exe
```

GUI 启动后自动探测常见路径，探测失败可点左下角 **⚙️ 配置** 手动设置。

#### 快照存储位置

默认存放在 exe 同级的 `data/snapshots/`（开发模式下是项目根目录）。随时可在 **⚙️ 配置 → 快照存储位置** 中修改。切换位置不会删除旧数据。

#### 命令行 CLI

```powershell
py -3 -m comfyui_time_machine scan --root "D:\ComfyUI_windows_portable" --out "reports/scan.json"
py -3 -m comfyui_time_machine --version
```

| 参数 | 说明 |
|---|---|
| `--root` / `-r` | **必需**，ComfyUI 根目录路径 |
| `--out` / `-o` | 可选，JSON 报告输出路径 |
| `--verbose` / `-v` | 可选，显示详细扫描过程 |

### 恢复流程（安全硬规则）

恢复是唯一会**写入** ComfyUI 目录的操作，严格遵循：

1. **预校验** —— 快照完整性、磁盘空间、快照状态
2. **构建 staging** —— 从 CAS blobs 复制到暂存区并回验 SHA-256
3. **保护点备份** —— 所有会被覆盖的当前文件复制到 `recovery_tx/backup/`
4. **原子替换** —— 从 staging 覆盖/新增目标文件
5. **L1 哈希验证** —— 恢复后对所有变更文件重算 SHA-256，不匹配则立即失败
6. **回滚能力** —— 任何阶段失败都保留保护点

### 运行测试

```powershell
py -3 -m pytest -q
# 预期: 101 passed
```

### 范围与限制

**能做 ✅**
- 识别 ComfyUI Portable / 非标准变体
- 内容寻址快照，跨快照去重
- 当前 vs 快照差异比较
- 事务化恢复 + L1 哈希验证
- PySide6 6 页 GUI
- 完整 pytest 回归（101 passed）

**不能做 ❌**（安全硬规则）
- 不删除用户快照里没有记录的文件（保守策略，避免误删模型/输出）
- 不遍历模型文件、生成图片、输出目录、缓存
- 不跟随符号链接 / junction / 挂载点
- 不将 `.env`、Token、密码等秘密写入报告
- 不运行 `git pull` / `pip install` / `.bat` / ComfyUI 启动脚本
- 不支持 ComfyUI Desktop、Linux、macOS

### 真实环境验收

已在 **F:\2026-ComfyUI-V8.3**（自定义节点 45 个，pip 包 384 个，2.835 GB / 18,445 文件）完整通过：

| 验收项 | 结果 |
|---|---|
| 自动路径识别 | ✅ |
| 快照创建 | ✅ integrity_ok=1 |
| CAS 去重 | ✅ 18,445 → 17,873 唯一 blob |
| 跨快照共享 | ✅ |
| GC 清零 | ✅ 全部删除后 blob 数 = 0 |
| 修改→恢复→原样 | ✅ L1 哈希通过 |

### 项目结构

```
src/comfyui_time_machine/
├── __init__.py          # 版本号
├── __main__.py          # python -m comfyui_time_machine（支持 --gui）
├── cli.py               # 命令行入口
├── config.py            # 持久化配置
├── models.py            # 数据模型
├── paths.py             # 安装路径识别
├── safety.py            # 路径安全工具
├── scanners/            # 只读扫描器
│   ├── core.py
│   ├── custom_nodes.py
│   ├── python_env.py
│   └── configs.py
├── snapshots/           # 快照引擎 + 恢复引擎
│   ├── scope.py
│   ├── store.py         # SQLite + CAS blobs + ref_count
│   ├── manager.py
│   ├── diff.py
│   └── restore.py
└── ui/                  # PySide6 GUI
    ├── state.py
    ├── main_window.py
    ├── workers/         # 后台线程
    └── pages/           # 6 页面：首页、扫描、快照、比较、恢复、验证
```

---

## License · 许可

MIT © ComfyUI Time Machine Contributors
