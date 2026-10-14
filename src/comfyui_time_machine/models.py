"""扫描报告数据模型 —— 纯 dataclasses，无外部依赖。

所有字段均可 JSON 序列化。to_dict() / from_dict() 实现了嵌套 dataclass、
列表、字典、datetime、Path、Enum 的自动转换。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------

class DetectionStatus(str, enum.Enum):
    """扫描时对某个项目的识别状态。"""
    DETECTED = "detected"          # 明确找到了
    UNKNOWN = "unknown"            # 存在但无法识别（布局异常）
    NOT_PRESENT = "not_present"    # 不存在
    NOT_CHECKED = "not_checked"    # 本轮没检查
    ERROR = "error"                # 检查时出错

    def __str__(self) -> str:
        return self.value


class InstallationType(str, enum.Enum):
    """ComfyUI 安装类型。"""
    PORTABLE_WINDOWS = "portable_windows"
    DESKTOP_WINDOWS = "desktop_windows"
    PORTABLE_LINUX = "portable_linux"
    SOURCE_CLONE = "source_clone"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# 可序列化 dataclass 基类
# ---------------------------------------------------------------------------

def _to_json_value(obj: Any) -> Any:
    """递归把 Python 对象转成 JSON 安全值。"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _to_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_value(i) for i in obj]
    if dataclasses.is_dataclass(obj):
        return obj.to_dict()
    # 兜底：转字符串
    return str(obj)


def _from_json_value(value: Any, type_hint: Any) -> Any:
    """根据 dataclass 字段类型，把 JSON 值转回 Python 对象。"""
    if value is None:
        return None

    # 处理 Optional[X]
    origin = getattr(type_hint, "__origin__", None)
    if origin is type(None):  # 普通 None 标注
        return None
    if origin is not None:
        # Optional[X] 的 origin 是 Union
        import typing
        if origin is typing.Union:
            non_none_args = [a for a in type_hint.__args__ if a is not type(None)]
            if len(non_none_args) == 1:
                return _from_json_value(value, non_none_args[0])

    # 基本类型直接返回
    if type_hint is str or type_hint is int or type_hint is float or type_hint is bool:
        return value

    # Enum
    if isinstance(type_hint, type) and issubclass(type_hint, enum.Enum):
        return type_hint(value)

    # Path
    if type_hint is Path:
        return Path(value)

    # datetime
    if type_hint is dt.datetime:
        return dt.datetime.fromisoformat(value)

    # 列表
    if origin is list:
        item_type = type_hint.__args__[0]
        return [_from_json_value(i, item_type) for i in value]

    # 字典
    if origin is dict:
        val_type = type_hint.__args__[1] if len(type_hint.__args__) > 1 else Any
        return {k: _from_json_value(v, val_type) for k, v in value.items()}

    # 嵌套 dataclass
    if isinstance(type_hint, type) and dataclasses.is_dataclass(type_hint):
        return type_hint.from_dict(value)

    # 兜底
    return value


class Serializable:
    """混入类，给 dataclass 提供 to_dict / from_dict。"""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            out[f.name] = _to_json_value(getattr(self, f.name))
        return out

    @classmethod
    def _resolved_hints(cls) -> dict[str, Any]:
        """把延迟求值的字符串注解解析成真实类型对象。"""
        import typing
        try:
            return typing.get_type_hints(cls)
        except Exception:
            return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Serializable":
        kwargs: dict[str, Any] = {}
        field_map = {f.name: f for f in dataclasses.fields(cls)}
        resolved = cls._resolved_hints()
        for key, field_info in field_map.items():
            val = data.get(key, field_info.default if field_info.default is not dataclasses.MISSING else None)
            if val is None:
                kwargs[key] = val
            else:
                # 用解析后的真实类型；fallback 到 field_info.type（可能是字符串）
                real_type = resolved.get(key, field_info.type)
                kwargs[key] = _from_json_value(val, real_type)
        return cls(**kwargs)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Serializable":
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# 各业务数据模型
# ---------------------------------------------------------------------------

@dataclass
class FileMetaInfo(Serializable):
    """单个文件/目录的元数据。"""
    path: Path
    exists: bool
    size_bytes: Optional[int] = None
    modified_at: Optional[dt.datetime] = None
    is_symlink: bool = False


@dataclass
class GitInfo(Serializable):
    """某个目录的 Git 状态。"""
    is_git_repo: bool = False
    is_worktree: bool = False
    commit: Optional[str] = None
    branch: Optional[str] = None
    has_local_changes: Optional[bool] = None
    status: DetectionStatus = DetectionStatus.NOT_CHECKED
    error: Optional[str] = None


@dataclass
class EnvironmentInfo(Serializable):
    """整体环境摘要。"""
    app_version: str = ""
    schema_version: str = "0.1"
    os: str = ""
    python_version: str = ""
    platform: str = ""


@dataclass
class ComfyUIInstallation(Serializable):
    """识别到的 ComfyUI 安装。"""
    type: InstallationType = InstallationType.UNKNOWN
    root_path: Optional[Path] = None            # Portable 根（含 python_embeded 那个）
    comfyui_path: Optional[Path] = None         # 实际 ComfyUI 源码目录
    main_py: FileMetaInfo = field(default_factory=lambda: FileMetaInfo(path=Path(""), exists=False))
    python_embeded: FileMetaInfo = field(default_factory=lambda: FileMetaInfo(path=Path(""), exists=False))
    custom_nodes_dir: FileMetaInfo = field(default_factory=lambda: FileMetaInfo(path=Path(""), exists=False))
    status: DetectionStatus = DetectionStatus.NOT_CHECKED
    git: GitInfo = field(default_factory=GitInfo)
    detected_at: Optional[dt.datetime] = None
    error: Optional[str] = None


@dataclass
class CustomNodeInfo(Serializable):
    """单个自定义节点。"""
    name: str = ""
    path: Path = Path("")
    exists: bool = False
    git: GitInfo = field(default_factory=GitInfo)
    has_requirements_txt: bool = False
    has_pyproject_toml: bool = False
    has_setup_py: bool = False
    is_symlink: bool = False
    out_of_scope: bool = False  # 外部路径、junction 等
    error: Optional[str] = None


@dataclass
class ConfigFileInfo(Serializable):
    """单个配置文件的元数据（默认不包含内容）。"""
    path: Path = Path("")
    exists: bool = False
    size_bytes: Optional[int] = None
    modified_at: Optional[dt.datetime] = None
    sha256: Optional[str] = None
    contains_secrets: Optional[bool] = None
    sensitive_keys_detected: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ScanWarning(Serializable):
    """扫描中遇到的警告/提示。"""
    level: str = "warning"    # info / warning / error
    category: str = ""        # path / git / python_env / secrets / ...
    message: str = ""
    detail: Optional[str] = None


@dataclass
class PythonPackageInfo(Serializable):
    """单个 Python 包的名称 + 版本。"""
    name: str = ""
    version: str = ""


@dataclass
class PythonEnvInfo(Serializable):
    """Python 嵌入式环境扫描结果。"""
    python_path: Optional[Path] = None
    python_version: Optional[str] = None
    pip_available: bool = False
    pip_error: Optional[str] = None
    packages: list[PythonPackageInfo] = field(default_factory=list)
    status: DetectionStatus = DetectionStatus.NOT_CHECKED
    error: Optional[str] = None


@dataclass
class ScanReport(Serializable):
    """顶层扫描报告。"""
    schema_version: str = "0.1"
    app_version: str = ""
    scan_started_at: Optional[dt.datetime] = None
    scan_completed_at: Optional[dt.datetime] = None

    os_info: str = ""
    platform_info: str = ""

    installation: ComfyUIInstallation = field(default_factory=ComfyUIInstallation)
    custom_nodes: list[CustomNodeInfo] = field(default_factory=list)
    config_files: list[ConfigFileInfo] = field(default_factory=list)
    python_env: PythonEnvInfo = field(default_factory=PythonEnvInfo)

    warnings: list[ScanWarning] = field(default_factory=list)

    # 扫描范围（便于后续恢复时判断是否已覆盖）
    scope: dict[str, Any] = field(default_factory=dict)

    scan_successful: bool = True
    top_level_error: Optional[str] = None
