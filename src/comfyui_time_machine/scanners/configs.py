"""scanners/configs.py —— 扫描配置文件元数据。

规则：
- 只记录元数据（路径、大小、mtime、SHA-256），**不读取文件正文**写入报告
- 对可能包含敏感字段的配置，只记录键名，不记录值
- 绝不遍历模型、输入、输出、缓存等大目录
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from ..models import ConfigFileInfo, DetectionStatus
from ..safety import is_symlink


# 我们查找的"已知配置文件"列表（文件名或 glob 模式）
# 只记录存在性和元数据，不解析
_KNOWN_CONFIG_FILES = [
    "run_nvidia_gpu.bat",
    "run_cpu.bat",
    "run.bat",
    "run_mac.command",
    "extra_model_paths.yaml",
    "user/default.yaml",
    "settings.json",
]

# 敏感字段名关键词（如果配置解析器将来启用，这些只记键名）
_SENSITIVE_KEY_PATTERNS = [
    "api_key", "apikey", "api-key",
    "token", "access_token",
    "password", "secret",
    "api_secret",
    "auth", "credentials",
    "bearer",
]


def _sha256_file(path: Path, max_bytes: int = 100_000) -> Optional[str]:
    """计算文件的 SHA-256。读取最多 max_bytes，避免超大文件拖慢扫描。

    超过 max_bytes 的配置文件我们认为不正常（配置不该那么大），
    返回 None 让调用方只依赖 size_bytes。
    """
    try:
        size = path.stat().st_size
        if size > max_bytes:
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _safe_file_meta(path: Path, compute_hash: bool = True) -> ConfigFileInfo:
    """构造单个配置文件的元数据。"""
    cf = ConfigFileInfo(path=path)

    try:
        if path.is_symlink():
            cf.error = "符号链接，已跳过"
            return cf
        if not path.exists():
            cf.exists = False
            return cf

        cf.exists = True
        stat = path.stat()
        cf.size_bytes = stat.st_size
        import datetime as dt
        cf.modified_at = dt.datetime.fromtimestamp(stat.st_mtime)

        if compute_hash:
            cf.sha256 = _sha256_file(path)

    except OSError as e:
        cf.error = f"读取文件失败：{e}"

    return cf


def scan_config_files(comfyui_path: Optional[Path]) -> list[ConfigFileInfo]:
    """在 ComfyUI 源码目录和 Portable 根目录中查找已知配置文件。"""
    results: list[ConfigFileInfo] = []

    if comfyui_path is None:
        return results

    base = Path(comfyui_path)
    if not base.exists() or not base.is_dir():
        return results

    # Portable 根（ComfyUI 的父目录）也查一遍
    search_dirs = [base]
    parent = base.parent
    if parent != base:
        search_dirs.append(parent)

    seen_paths: set[Path] = set()

    for search_dir in search_dirs:
        for name in _KNOWN_CONFIG_FILES:
            candidate = search_dir / name
            # 规范化，避免重复
            try:
                norm = candidate.resolve() if candidate.exists() else candidate
            except OSError:
                norm = candidate

            if norm in seen_paths:
                continue
            seen_paths.add(norm)

            info = _safe_file_meta(candidate, compute_hash=True)
            results.append(info)

    return results
