"""ComfyUI 安装路径识别 —— 只做只读路径检查，不做任何文件修改。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from .models import (
    ComfyUIInstallation,
    DetectionStatus,
    FileMetaInfo,
    GitInfo,
    InstallationType,
)
from .safety import check_path, is_symlink, normalize_path


# Portable 根目录的预期布局：
#   D:\\...\\ComfyUI_windows_portable\\
#       ComfyUI\\                 ← 源码目录，含 main.py
#       python_embeded\\          ← 嵌入式 Python
#       run_nvidia_gpu.bat / run_cpu.bat / run.bat
#       update\\                  ← 可选的更新脚本目录

# 为了稳健，我们允许 python_embeded 目录名有轻微差异（如 python_embedded、python）
PYTHON_EMBEDED_CANDIDATES = [
    "python_embeded",
    "python_embedded",
    "python",
]

COMFYUI_SUBDIR_CANDIDATES = [
    "ComfyUI",
    "comfyui",
]


def _file_meta(path: Path) -> FileMetaInfo:
    """快速构造 FileMetaInfo，只填 exists / is_symlink / 基础信息。

    对符号链接使用 lstat 不跟随；对正常文件用 stat。
    """
    path_norm = normalize_path(path)
    exists = False
    size = None
    mtime = None
    sym = False
    try:
        # 先用 lstat 检测 symlink，不跟随
        lst = path_norm.lstat()
        sym = path_norm.is_symlink()
        # 只有不是 symlink 时才 follow，否则只记录 link 自身的 stat
        stat = path_norm.stat() if not sym else lst
        exists = True
        size = stat.st_size
        mtime = dt.datetime.fromtimestamp(stat.st_mtime)
    except OSError:
        # 路径不存在或权限不足，exists 保持 False
        try:
            sym = path_norm.is_symlink()
        except OSError:
            pass
    return FileMetaInfo(
        path=path_norm,
        exists=exists,
        size_bytes=size,
        modified_at=mtime,
        is_symlink=sym,
    )


def _first_existing_dir(root: Path, candidates: list[str]) -> Optional[Path]:
    """在 root 下找第一个存在的候选子目录。"""
    for name in candidates:
        p = root / name
        try:
            if p.is_dir() and not is_symlink(p):
                return p
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# 核心识别函数
# ---------------------------------------------------------------------------

def identify_installation(root_path: str | Path) -> ComfyUIInstallation:
    """尝试识别给定路径上的 ComfyUI 安装类型。

    返回的 ComfyUIInstallation 总会有 status 字段，调用方根据 status 判断是否继续。
    本函数绝不创建、修改、删除任何文件。
    """
    result = ComfyUIInstallation(
        detected_at=dt.datetime.now(),
    )

    # 1. 基础路径安全检查
    check = check_path(root_path, must_be_directory=True)
    if not check.is_valid:
        result.status = DetectionStatus.ERROR
        result.error = check.error or "路径检查失败"
        return result

    root = normalize_path(root_path)
    result.root_path = root

    # 2. 判断是否已经直接在 ComfyUI 源码目录（含 main.py）
    #    即用户可能传了 Portable 根，也可能直接传了 ComfyUI 子目录
    main_py_here = root / "main.py"
    comfyui_here = None
    python_embeded_here = None

    if main_py_here.is_file():
        # 当前目录本身就像是 ComfyUI 源码目录
        comfyui_here = root
        # 往上找 python_embeded（说明这是 Portable 子目录）
        for parent in root.parents:
            py_dir = _first_existing_dir(parent, PYTHON_EMBEDED_CANDIDATES)
            if py_dir:
                python_embeded_here = py_dir
                # 修正 Portable 根
                result.root_path = parent
                break

    # 3. 尝试作为 Portable 根布局识别
    if comfyui_here is None:
        comfyui_here = _first_existing_dir(root, COMFYUI_SUBDIR_CANDIDATES)
    if python_embeded_here is None:
        python_embeded_here = _first_existing_dir(root, PYTHON_EMBEDED_CANDIDATES)

    # 4. 填充安装信息
    result.comfyui_path = comfyui_here
    result.python_embeded = _file_meta(python_embeded_here) if python_embeded_here else FileMetaInfo(path=root / "python_embeded", exists=False)
    if comfyui_here is not None:
        result.main_py = _file_meta(comfyui_here / "main.py")
        result.custom_nodes_dir = _file_meta(comfyui_here / "custom_nodes")
    else:
        result.main_py = FileMetaInfo(path=root / "ComfyUI" / "main.py", exists=False)
        result.custom_nodes_dir = FileMetaInfo(path=root / "ComfyUI" / "custom_nodes", exists=False)

    # 5. 根据特征判断安装类型
    has_comfyui_subdir = comfyui_here is not None
    has_python_embeded = result.python_embeded.exists
    has_main_py = result.main_py.exists

    if has_comfyui_subdir and has_python_embeded and has_main_py:
        # 典型 Portable Windows
        result.type = InstallationType.PORTABLE_WINDOWS
        result.status = DetectionStatus.DETECTED
        return result

    # 只有源码目录，没有 python_embeded —— 可能是源码 clone
    if has_comfyui_subdir and has_main_py and not has_python_embeded:
        result.type = InstallationType.SOURCE_CLONE
        result.status = DetectionStatus.UNKNOWN
        result.error = "检测到 ComfyUI 源码目录但未发现 python_embeded，不属于 Portable 安装"
        return result

    # 什么都没有 —— 随机目录
    if not has_comfyui_subdir and not has_main_py:
        result.type = InstallationType.UNKNOWN
        result.status = DetectionStatus.NOT_PRESENT
        result.error = "未检测到 ComfyUI 安装特征"
        return result

    # 其他边缘情况 —— 保守处理
    result.type = InstallationType.UNSUPPORTED
    result.status = DetectionStatus.UNKNOWN
    result.error = "检测到 ComfyUI 相关文件但布局不符合已知安装类型，暂不支持"
    return result


def expected_custom_nodes_dir(installation: ComfyUIInstallation) -> Optional[Path]:
    """给出自定义节点目录的预期路径（仅 Portable 有效）。"""
    if installation.comfyui_path is None:
        return None
    return installation.comfyui_path / "custom_nodes"
