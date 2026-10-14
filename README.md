# ComfyUI Time Machine

Windows ComfyUI Portable 环境的**扫描 → 快照 → 比较 → 恢复**全链路工具。

> ⚠️ **恢复功能会修改 ComfyUI 目录文件，使用前请先停止 ComfyUI 并创建保护点。**
> 详见下方"恢复流程"。

## 功能

- 🔍 **只读扫描** —— 识别 ComfyUI Portable 安装，采集 Git 状态、Python 环境、自定义节点、配置文件
- 📸 **快照** —— 内容寻址 CAS（SHA-256），跨快照去重，引用计数 GC
- 📊 **差异比较** —— 当前 vs 快照 / 快照 vs 快照
- 🔄 **事务化恢复** —— staging 暂存 + 保护点备份 + L1 哈希验证 + 可回滚
- 🖥️ **PySide6 GUI** —— 6 页导航，后台线程，进度实时显示
- 📦 **PyInstaller 打包** —— `dist/ComfyUI_Time_Machine/ComfyUI_Time_Machine.exe` 绿色即用

## 系统要求

- **操作系统**：Windows 10 / 11
- **Python**：3.11 或 3.12（Time Machine 自身运行环境，独立于 ComfyUI 的嵌入式 Python）
- **支持的 ComfyUI 安装**：Windows Portable（含 `ComfyUI/` 子目录）

## 安装

```powershell
git clone <repo-url> comfyui-time-machine
cd comfyui-time-machine

# 创建虚拟环境（推荐）
py -3 -m venv .venv
.\.venv\Scripts\activate

# 安装（CLI + 扫描 + 快照 + 恢复 —— 无 GUI）
pip install -e .

# 带 GUI 安装
pip install -e ".[gui]"

# 全部（含测试 + 打包）
pip install -e ".[dev,gui,build]"
```

## 使用

### 🖥️ GUI（推荐）

```powershell
# 开发环境
py -3 -m comfyui_time_machine --gui

# 或打包后的 exe
.\dist\ComfyUI_Time_Machine\ComfyUI_Time_Machine.exe
```

GUI 自动探测常见路径（如 `F:\2026-ComfyUI-V8.3`），探测失败可在右上角「⚙️ 配置」手动选择。

### 🔧 CLI

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

恢复是唯一会**写入** ComfyUI 目录的操作，执行时会：

1. **预校验** —— 快照完整性、磁盘空间、快照状态
2. **构建 staging** —— 从 CAS blobs 复制文件到暂存区并回验 SHA-256
3. **保护点备份** —— 所有会被覆盖的当前文件复制到 `recovery_tx/backup/`
4. **原子替换** —— 从 staging 覆盖/新增目标文件
5. **L1 哈希验证** —— 恢复后对所有变更文件重算 SHA-256，不匹配则失败
6. **回滚能力** —— 任何阶段失败都保留保护点，可手动调用 `rollback()`

## 打包发布

```powershell
pip install -e ".[build]"
pyinstaller build.spec --noconfirm
# 产物: dist/ComfyUI_Time_Machine/ComfyUI_Time_Machine.exe（~113 MB）
```

## 范围与限制

### ✅ 能做的

- 识别 ComfyUI Portable / 非标准变体安装类型
- 采集核心路径、Git 状态（只读）、自定义节点（含 Git/非 Git 区分）、Python 环境、pip 包清单、配置文件元数据
- 内容寻址快照（SHA-256 CAS + ref_count GC），跨快照去重
- 当前 vs 快照差异比较
- 事务化恢复 + L1 哈希验证
- PySide6 GUI 6 页
- PyInstaller onedir 打包
- 完整 pytest 回归测试（101 passed）

### ❌ **不**能做的（安全硬规则）

- 不修改或删除用户快照里**没有**记录的文件（保守策略，避免误删模型/输出）
- 不遍历模型文件、生成图片、输出目录、缓存等大目录（scope excludes）
- 不跟随符号链接 / junction / 挂载点
- 不将 `.env`、Token、密码等秘密写入报告
- 不运行 `git pull` / `pip install` / `.bat` / ComfyUI 启动脚本
- 不支持 ComfyUI Desktop、Linux、macOS、多外部节点目录
- L2/L3 恢复后验证（ComfyUI 启动检查 / 工作流执行）尚未实现

## 真实环境验收

已在 **F:\2026-ComfyUI-V8.3**（自定义节点 45 个，Git 23 / 非 Git 22，pip 包 384 个）上完整通过：

| 验收项 | 结果 |
|---|---|
| 自动路径识别（`python/` 非 `python_embeded/`） | ✅ |
| 快照创建 | ✅ 2.835 GB / 18,445 文件 / integrity_ok=1 |
| CAS 去重 | ✅ 18,445 → 17,873 唯一 blob |
| 跨快照共享 | ✅ 删除一快照不影响另一 |
| GC 清零 | ✅ 全部快照删除后物理 blob 数 = 0 |
| 修改一个文件 → 恢复 → 回到原样 | ✅ L1 哈希通过 |
| 恢复后完整 diff | ✅ 零差异 |

## 运行测试

```powershell
py -3 -m pytest -q
# 预期: 101 passed
```

## 项目结构

```
src/comfyui_time_machine/
├── __init__.py          # 版本号
├── __main__.py          # python -m comfyui_time_machine（支持 --gui）
├── cli.py               # 命令行入口
├── models.py            # 数据模型 + JSON 序列化
├── paths.py             # ComfyUI 安装路径识别
├── safety.py             # 路径安全工具（符号链接检测、路径逃逸检查）
├── scanners/            # 只读扫描器
│   ├── core.py          # safe_run + Git 扫描
│   ├── custom_nodes.py  # 自定义节点扫描
│   ├── python_env.py    # Python 环境扫描
│   └── configs.py       # 配置文件扫描
├── snapshots/           # 快照引擎 + 恢复引擎
│   ├── scope.py         # 范围配置（含 excludes）
│   ├── store.py         # SQLite + CAS blobs + ref_count
│   ├── manager.py       # 创建/删除/列出
│   ├── diff.py          # 差异比较
│   └── restore.py       # 事务化恢复 + 保护点 + L1 验证
└── ui/                  # PySide6 GUI
    ├── state.py         # AppState 跨页共享
    ├── _detect.py       # 启动前路径探测
    ├── main_window.py   # 主窗口（左侧导航 + 右侧 QStackedWidget）
    ├── workers/         # QThread 后台线程
    │   ├── base.py
    │   ├── scan.py
    │   ├── snapshot_create.py
    │   └── restore.py
    └── pages/           # 6 个页面
        ├── home.py
        ├── scan.py
        ├── snapshots.py
        ├── compare.py
        ├── restore.py
        └── verify.py
```

## 已知问题 / 反馈

欢迎在 Issue 中提交：
- 扫描到的布局与你的 ComfyUI 安装不匹配
- 符号链接 / junction / 权限异常等边界情况
- 恢复失败但保护点数据还在 `data/snapshots/recovery_tx/` 里没清掉

**提交 Issue 时请脱敏你的真实安装路径和节点目录。**
