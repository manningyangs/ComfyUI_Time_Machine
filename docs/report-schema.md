# 扫描报告 Schema（v0.1）

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `string` | 报告 schema 版本号。当前固定 `"0.1"` |
| `app_version` | `string` | Time Machine 应用版本号 |
| `scan_started_at` | `datetime` | 扫描开始时间（ISO 8601） |
| `scan_completed_at` | `datetime` | 扫描完成时间（ISO 8601） |
| `os_info` | `string` | 操作系统信息，如 `"nt win32"` |
| `platform_info` | `string` | Python `sys.platform` 值 |
| `installation` | `ComfyUIInstallation` | 识别到的 ComfyUI 安装信息（见下） |
| `custom_nodes` | `CustomNodeInfo[]` | 自定义节点列表 |
| `config_files` | `ConfigFileInfo[]` | 配置文件元数据列表 |
| `python_env` | `PythonEnvInfo` | 嵌入式 Python 环境扫描结果（见下） |
| `warnings` | `ScanWarning[]` | 扫描过程中产生的警告/提示 |
| `scope` | `object` | 本次扫描覆盖的范围元数据 |
| `scan_successful` | `boolean` | 整体是否成功完成 |
| `top_level_error` | `string \| null` | 顶层严重错误信息（若扫描未能启动） |

---

## 安装信息 `ComfyUIInstallation`

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `InstallationType` | 安装类型枚举值，见下表 |
| `status` | `DetectionStatus` | 识别状态枚举值，见下表 |
| `root_path` | `Path \| null` | Portable 根目录（含 `python_embeded/` 的那个） |
| `comfyui_path` | `Path \| null` | ComfyUI 源码目录（含 `main.py` 的那个） |
| `main_py` | `FileMetaInfo` | `main.py` 文件元数据 |
| `python_embeded` | `FileMetaInfo` | 嵌入式 Python 目录元数据 |
| `custom_nodes_dir` | `FileMetaInfo` | 自定义节点目录元数据 |
| `git` | `GitInfo` | ComfyUI 源码目录的 Git 状态 |
| `detected_at` | `datetime` | 识别完成的时间 |
| `error` | `string \| null` | 识别错误信息 |

---

## 枚举值

### InstallationType（安装类型）
| 值 | 说明 |
|---|---|
| `portable_windows` | ComfyUI Windows Portable（**当前唯一正式支持**） |
| `desktop_windows` | ComfyUI Desktop 安装 |
| `portable_linux` | ComfyUI Linux Portable |
| `source_clone` | 直接 `git clone` 的源码 |
| `unknown` | 无法识别 |
| `unsupported` | 检测到但当前版本不支持 |

### DetectionStatus（检测状态）
| 值 | 说明 |
|---|---|
| `detected` | 明确找到了 |
| `unknown` | 存在但布局异常，无法确认 |
| `not_present` | 不存在 |
| `not_checked` | 本轮没有检查这一项 |
| `error` | 检查过程中出错 |

---

## 文件元数据 `FileMetaInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `path` | `Path` | 绝对、规范化的路径 |
| `exists` | `boolean` | 文件/目录是否存在 |
| `size_bytes` | `int \| null` | 文件大小（字节），目录为 null |
| `modified_at` | `datetime \| null` | 最后修改时间 |
| `is_symlink` | `boolean` | 是否为符号链接 |

---

## Git 信息 `GitInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `is_git_repo` | `boolean` | 是否为 Git 仓库 |
| `is_worktree` | `boolean` | `.git` 是 worktree 指针文件还是目录 |
| `commit` | `string \| null` | 当前 HEAD 提交号 |
| `branch` | `string \| null` | 当前分支名 |
| `has_local_changes` | `boolean \| null` | 工作区是否有未提交修改 |
| `status` | `DetectionStatus` | Git 检测状态 |
| `error` | `string \| null` | Git 命令失败时的错误信息 |

---

## 自定义节点 `CustomNodeInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `string` | 节点目录名 |
| `path` | `Path` | 节点绝对路径 |
| `exists` | `boolean` | 节点目录是否存在 |
| `git` | `GitInfo` | 节点的 Git 状态 |
| `has_requirements_txt` | `boolean` | 是否存在 `requirements.txt` |
| `has_pyproject_toml` | `boolean` | 是否存在 `pyproject.toml` |
| `has_setup_py` | `boolean` | 是否存在 `setup.py` |
| `is_symlink` | `boolean` | 是否为符号链接 |
| `out_of_scope` | `boolean` | 是否超出当前支持范围（如外部路径、junction） |
| `error` | `string \| null` | 扫描该节点时遇到的错误 |

---

## 配置文件 `ConfigFileInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `path` | `Path` | 配置文件绝对路径 |
| `exists` | `boolean` | 文件是否存在 |
| `size_bytes` | `int \| null` | 文件大小 |
| `modified_at` | `datetime \| null` | 最后修改时间 |
| `sha256` | `string \| null` | 文件 SHA-256 哈希（当前版本不计算，始终 null） |
| `contains_secrets` | `boolean \| null` | 是否可能包含敏感字段（当前版本 null） |
| `sensitive_keys_detected` | `string[]` | 检测到的可能敏感字段名（只记键名，不记值） |
| `error` | `string \| null` | 扫描错误 |

---

## Python 嵌入式环境 `PythonEnvInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `python_path` | `Path \| null` | 嵌入式 `python.exe` 绝对路径 |
| `python_version` | `string \| null` | Python 版本字符串 |
| `pip_available` | `boolean` | 该 Python 环境是否有 pip 模块可用 |
| `pip_error` | `string \| null` | pip 相关的错误（如超时、解析失败） |
| `packages` | `PythonPackageInfo[]` | `pip list --format=json` 采集到的包清单 |
| `status` | `DetectionStatus` | Python 环境扫描状态 |
| `error` | `string \| null` | 扫描错误 |

## Python 包 `PythonPackageInfo`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `string` | 包名 |
| `version` | `string` | 版本号 |

---

## 警告 `ScanWarning`

| 字段 | 类型 | 说明 |
|---|---|---|
| `level` | `string` | `"info"` / `"warning"` / `"error"` |
| `category` | `string` | 警告类别，如 `"installation_detection"` / `"git"` / `"path"` 等 |
| `message` | `string` | 警告信息 |
| `detail` | `string \| null` | 更多详情 |

---

## 隐私与安全

- 报告中所有路径均为绝对路径，可能包含用户名或你的安装目录结构。**请不要将原始报告上传到公共论坛。**
- Time Machine **不会**将 `.env`、API Key、密码、Token 等秘密值写入报告。
- `ConfigFileInfo.sensitive_keys_detected` 只记录键名（如 `"api_key"`），不记录对应的值。
