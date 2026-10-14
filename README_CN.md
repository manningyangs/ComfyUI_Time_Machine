# ComfyUI Time Machine

> [English](README.md) · [中文](README_CN.md)

Windows ComfyUI Portable 环境的**扫描 → 快照 → 比较 → 恢复**全链路工具。

![状态](https://img.shields.io/badge/状态-测试版-orange)
![Python](https://img.shields.io/badge/python-3.11%20%2B%203.12-blue)
![系统](https://img.shields.io/badge/系统-windows-lightgrey)
![许可](https://img.shields.io/badge/license-MIT-green)

> ⚠️ **恢复功能会修改 ComfyUI 目录文件，使用前请先停止 ComfyUI 并确保有近期快照作为保护点。**

---

## 功能特性

- 🔍 **只读扫描** —— 识别 ComfyUI Portable 安装，采集 Git 状态、Python 环境、自定义节点、配置文件
- 📸 **内容寻址快照** —— SHA-256 CAS（内容寻址存储），跨快照去重，引用计数垃圾回收
- 📊 **差异比较** —— 当前 vs 快照 / 快照 vs 快照
- 🔄 **事务化恢复** —— staging 暂存 + 保护点备份 + L1 哈希验证 + 回滚能力
- 🖥️ **PySide6 GUI** —— 6 页导航，后台线程，进度实时显示
- 📦 **PyInstaller 打包** —— `ComfyUI_Time_Machine.exe` 绿色即用，无需安装

## 系统要求

- **操作系统**：Windows 10 / 11
- **Python**：3.11 或 3.12（Time Machine 自身运行环境，独立于 ComfyUI 的嵌入式 Python）
- **支持的 ComfyUI 安装**：Windows Portable（含 `ComfyUI/` 子目录）

## 安装

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

## 使用

### 🖥️ GUI（推荐）

```powershell
# 开发环境运行
py -3 -m comfyui_time_machine --gui

# 或直接用打包后的 exe
.\dist\ComfyUI_Time_Machine\ComfyUI_Time_Machine.exe
```

GUI 启动后自动探测常见路径，探测失败可点左下角 **⚙️ 配置** 手动设置。

### 🗂️ 快照存储位置

默认存放在 exe 同级的 `data/snapshots/`（开发模式下是项目根目录）。随时可改：

1. 点击左下角 **⚙️ 配置**
2. 在 **快照存储位置** 栏点 **📂 浏览...** 选择任意磁盘空间足够的目录
3. 点 **💾 保存**

> 切换存储位置**不会**删除旧数据，只是快照列表会显示新位置的快照。如果旧位置还有数据，会弹出提示。

### 🔧 CLI 命令行

```powershell
# 扫描
py -3 -m comfyui_time_machine scan --root "D:\ComfyUI_windows_portable" --out "reports/scan.json"

# 查看版本 / 帮助
py -3 -m comfyui_time_machine --version
py -3 -m comfyui_time_machine --help
```

参数说明：

| 参数 | 说明 |
|---|---|
| `--root` / `-r` | **必需**，ComfyUI 根目录路径 |
| `--out` / `-o` | 可选，JSON 报告输出路径 |
| `--verbose` / `-v` | 可选，显示详细扫描过程 |

## 恢复流程（安全硬规则）

恢复是唯一会**写入** ComfyUI 目录的操作，严格遵循以下流程：

1. **预校验** —— 快照完整性、磁盘空间、快照状态
2. **构建 staging** —— 从 CAS blobs 复制到暂存区并回验 SHA-256
3. **保护点备份** —— 所有会被覆盖的当前文件复制到 `recovery_tx/backup/`
4. **原子替换** —— 从 staging 覆盖/新增目标文件
5. **L1 哈希验证** —— 恢复后对所有变更文件重算 SHA-256，不匹配则立即失败
6. **回滚能力** —— 任何阶段失败都保留保护点，可手动调用 `rollback()`

## 运行测试

```powershell
py -3 -m pytest -q
# 预期: 101 passed
```

## 范围与限制

### ✅ 能做的

- 识别 ComfyUI Portable / 非标准变体安装
- 采集核心路径、Git 状态（只读）、自定义节点（含 Git/非 Git 区分）、Python 环境、pip 包清单、配置文件元数据
- 内容寻址快照（SHA-256 CAS + ref_count GC），跨快照去重
- 当前 vs 快照差异比较
- 事务化恢复 + L1 哈希验证
- PySide6 6 页 GUI
- PyInstaller 打包
- 完整 pytest 回归测试（101 passed）

### ❌ **不**能做的（安全硬规则）

- 不修改或删除用户快照里**没有**记录的文件（保守策略，避免误删模型/输出）
- 不遍历模型文件、生成图片、输出目录、缓存等大目录（scope 排除）
- 不跟随符号链接 / junction / 挂载点
- 不将 `.env`、Token、密码等秘密写入报告
- 不运行 `git pull` / `pip install` / `.bat` / ComfyUI 启动脚本
- 不支持 ComfyUI Desktop、Linux、macOS、多外部节点目录
- L2/L3 恢复后验证（ComfyUI 启动检查 / 工作流执行）尚未实现

## 真实环境验收

已在 **F:\2026-ComfyUI-V8.3**（自定义节点 45 个，Git 23 / 非 Git 22，pip 包 384 个）完整通过：

| 验收项 | 结果 |
|---|---|
| 自动路径识别（`python/` 变体） | ✅ |
| 快照创建 | ✅ 2.835 GB / 18,445 文件 / integrity_ok=1 |
| CAS 去重 | ✅ 18,445 → 17,873 唯一 blob |
| 跨快照共享 | ✅ 删除一快照不影响另一 |
| GC 清零 | ✅ 全部快照删除后物理 blob 数 = 0 |
| 修改一个文件 → 恢复 → 回到原样 | ✅ L1 哈希通过 |
| 恢复后完整 diff | ✅ 零差异 |

## 项目结构

```
src/comfyui_time_machine/
├── __init__.py          # 版本号
├── __main__.py          # python -m comfyui_time_machine（支持 --gui）
├── cli.py               # 命令行入口
├── config.py            # 持久化配置（settings.json）
├── models.py            # 数据模型 + JSON 序列化
├── paths.py             # ComfyUI 安装路径识别
├── safety.py            # 路径安全工具（符号链接检测、路径逃逸检查）
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
    ├── state.py         # 跨页 AppState
    ├── main_window.py   # 主窗口（导航 + 堆叠页）
    ├── workers/         # 后台线程
    │   ├── base.py
    │   ├── scan.py
    │   ├── snapshot_create.py
    │   ├── snapshot_delete.py
    │   └── restore.py
    └── pages/           # 6 个页面
        ├── home.py
        ├── scan.py
        ├── snapshots.py
        ├── compare.py
        ├── restore.py
        └── verify.py
```

## License

MIT © ComfyUI Time Machine Contributors
