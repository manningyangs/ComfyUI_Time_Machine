"""scanners/python_env.py —— 扫描 ComfyUI 嵌入式 Python 环境。

目标：找到 python.exe，执行 pip list --format=json，记录包清单。
不做任何安装、升级、卸载操作。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..models import DetectionStatus, PythonEnvInfo, PythonPackageInfo
from ..safety import safe_resolve
from .core import safe_run


# python_embeded 下可能的 exe 名称
_PYTHON_EXE_CANDIDATES = [
    "python.exe",
    "python3.exe",
]

# pip list 的超时稍微大一点，嵌入式环境可能慢
PIP_TIMEOUT = 30


def _find_python_exe(embed_dir: Path) -> Optional[Path]:
    """在 python_embeded 目录中找 python.exe（真实列表，不硬编码）。"""
    if not embed_dir.exists() or not embed_dir.is_dir():
        return None

    # 先用硬编码候选名快速试
    for name in _PYTHON_EXE_CANDIDATES:
        candidate = embed_dir / name
        if candidate.is_file():
            return safe_resolve(candidate)

    # 没找到就列目录找 .exe
    try:
        for entry in embed_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() == ".exe":
                low = entry.name.lower()
                if low.startswith("python") and "pip" not in low and "installer" not in low:
                    return safe_resolve(entry)
    except OSError:
        pass

    return None


def _get_python_version(python_exe: Path) -> Optional[str]:
    """读取 Python 版本字符串。"""
    r = safe_run(
        [str(python_exe), "--version"],
        timeout=5,
    )
    if r.ok:
        out = (r.stdout or r.stderr).strip()
        if out.lower().startswith("python"):
            return out.split(None, 1)[1].strip() if " " in out else out
        return out[:100] or None
    return None


def _get_pip_packages(python_exe: Path) -> tuple[bool, Optional[str], list[PythonPackageInfo]]:
    """通过 python -m pip list --format=json 读取包清单。

    返回 (pip_available, error_or_None, packages_list)
    """
    r_check = safe_run(
        [str(python_exe), "-m", "pip", "--version"],
        timeout=10,
    )
    if not r_check.ok:
        return False, f"pip 不可用：{(r_check.stderr or r_check.error or '').strip()[:200]}", []

    r = safe_run(
        [str(python_exe), "-m", "pip", "list", "--format=json"],
        timeout=PIP_TIMEOUT,
    )
    if r.timed_out:
        return True, "pip list 超时", []
    if r.returncode != 0:
        return True, f"pip list 失败：{(r.stderr or '').strip()[:200]}", []

    try:
        data = json.loads(r.stdout)
        if not isinstance(data, list):
            return True, f"pip list 输出不是列表：{type(data).__name__}", []
        packages: list[PythonPackageInfo] = []
        for item in data:
            if isinstance(item, dict) and "name" in item:
                packages.append(PythonPackageInfo(
                    name=str(item.get("name", "")),
                    version=str(item.get("version", "")),
                ))
        return True, None, packages
    except json.JSONDecodeError as e:
        return True, f"pip list JSON 解析失败：{e}", []


def scan_python_environment(python_embeded_dir: Optional[Path]) -> PythonEnvInfo:
    """扫描 Python 嵌入式环境。"""
    result = PythonEnvInfo(status=DetectionStatus.NOT_CHECKED)

    if python_embeded_dir is None:
        result.status = DetectionStatus.NOT_PRESENT
        result.error = "未提供 python_embeded 目录"
        return result

    embed = Path(python_embeded_dir)
    if not embed.exists() or not embed.is_dir():
        result.status = DetectionStatus.NOT_PRESENT
        result.error = f"python_embeded 目录不存在：{embed}"
        return result

    py_exe = _find_python_exe(embed)
    if py_exe is None:
        result.status = DetectionStatus.NOT_PRESENT
        result.error = f"在 {embed} 中未找到 python.exe"
        return result

    result.python_path = py_exe
    result.python_version = _get_python_version(py_exe)

    pip_ok, pip_err, packages = _get_pip_packages(py_exe)
    result.pip_available = pip_ok
    result.pip_error = pip_err
    result.packages = packages

    result.status = DetectionStatus.DETECTED
    return result
