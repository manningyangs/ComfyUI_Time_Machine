"""scanners/custom_nodes.py —— 扫描 ComfyUI/custom_nodes 下的自定义节点。

默认只遍历一级子目录，不递归进入其内部文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..models import CustomNodeInfo, DetectionStatus
from ..safety import is_symlink, safe_resolve
from .core import scan_git_for_directory


# 我们认为一个目录如果是下面这些名字，就不是真正的自定义节点
_SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    ".DS_Store",
    "desktop.ini",
}


def _detect_dependency_files(node_dir: Path) -> tuple[bool, bool, bool]:
    """检测节点目录是否有常见依赖声明文件。"""
    has_req = (node_dir / "requirements.txt").is_file()
    has_pyproj = (node_dir / "pyproject.toml").is_file()
    has_setup = (node_dir / "setup.py").is_file()
    return has_req, has_pyproj, has_setup


def scan_custom_nodes(
    custom_nodes_dir: Optional[Path],
) -> list[CustomNodeInfo]:
    """扫描给定 custom_nodes 目录下的所有一级子目录。

    设计要点：
    - 单个节点的扫描失败（权限、损坏、git 超时）**不会**中断其他节点的扫描
    - 不跟随符号链接（is_symlink=True → 标记 out_of_scope）
    - 默认不递归子目录内容
    """
    results: list[CustomNodeInfo] = []

    if custom_nodes_dir is None:
        return results

    base = Path(custom_nodes_dir)
    if not base.exists() or not base.is_dir():
        return results

    try:
        entries = list(base.iterdir())
    except OSError as e:
        # 整个目录都无法读取时，返回一个带 error 的占位
        info = CustomNodeInfo(
            name=str(base),
            path=base,
            exists=False,
            error=f"无法列出 custom_nodes 目录：{e}",
        )
        results.append(info)
        return results

    for entry in sorted(entries):
        name = entry.name

        # 跳过缓存和隐藏目录
        if name in _SKIP_DIR_NAMES:
            continue

        # 必须是目录
        try:
            is_dir = entry.is_dir()
        except OSError:
            is_dir = False

        if not is_dir:
            # 不是子目录，跳过
            continue

        # 符号链接 → 标记 out_of_scope
        sym = False
        try:
            sym = entry.is_symlink()
        except OSError:
            sym = True  # 保守

        if sym:
            results.append(CustomNodeInfo(
                name=name,
                path=safe_resolve(entry),
                exists=True,
                is_symlink=True,
                out_of_scope=True,
                error="符号链接，Time Machine 不跟随",
            ))
            continue

        # 检测依赖文件
        has_req, has_pyproj, has_setup = _detect_dependency_files(entry)

        # 采集 Git 状态（只读，有超时）
        try:
            git_info = scan_git_for_directory(entry)
        except Exception as e:
            from ..models import GitInfo
            git_info = GitInfo(status=DetectionStatus.ERROR, error=str(e))

        node = CustomNodeInfo(
            name=name,
            path=safe_resolve(entry),
            exists=True,
            git=git_info,
            has_requirements_txt=has_req,
            has_pyproject_toml=has_pyproj,
            has_setup_py=has_setup,
            is_symlink=False,
        )
        results.append(node)

    return results
