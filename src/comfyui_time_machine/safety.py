"""路径安全工具 —— 支撑"扫描器只读、不跟随符号链接、不路径逃逸"三大硬规则。

本模块只做纯粹的路径判断，不涉及任何文件读写。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 路径解析与规范化
# ---------------------------------------------------------------------------

def normalize_path(path: str | os.PathLike[str]) -> Path:
    """把任意路径转成绝对、大小写规范化（Windows 下 os.path.normpath）、不含 .. 的 Path。

    不跟随符号链接，只做字符串层面的规范化。
    """
    p = Path(path)
    resolved = Path(os.path.normpath(str(p)))
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def safe_resolve(path: str | os.PathLike[str]) -> Path:
    """返回 path 的绝对规范化形式，不跟随符号链接。"""
    return normalize_path(path)


# ---------------------------------------------------------------------------
# 符号链接检测
# ---------------------------------------------------------------------------

def is_symlink(path: str | os.PathLike[str]) -> bool:
    """判断目标文件/目录本身是否为符号链接（或 Windows 下的 junction / symlink）。"""
    try:
        return Path(path).is_symlink()
    except OSError:
        # 权限不足或路径损坏时，保守返回 True 让调用方跳过
        return True


def has_symlink_ancestor(path: str | os.PathLike[str]) -> bool:
    """判断 path 的任意父目录是否为符号链接。

    这是防御性检查：即便 path 本身不是 symlink，若上层目录是，我们也不应进入。
    """
    try:
        p = Path(path)
        for parent in p.parents:
            if parent.is_symlink():
                return True
        return False
    except OSError:
        return True


def should_follow(path: str | os.PathLike[str]) -> bool:
    """综合判断：是否应该跟随这个路径。只读扫描器默认不跟随任何符号链接。"""
    return not is_symlink(path) and not has_symlink_ancestor(path)


# ---------------------------------------------------------------------------
# 路径逃逸检查
# ---------------------------------------------------------------------------

def is_path_contained_within(candidate: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """判断 candidate 是否完全位于 root 之内（防止路径穿越）。

    两个路径都会先经 normalize_path 处理。若 root 本身不存在也会尝试比较。
    """
    try:
        c = normalize_path(candidate)
        r = normalize_path(root)
        # 在 Windows 下驱动器号要一致
        if c.drive.lower() != r.drive.lower():
            return False
        # 必须相等或是子路径
        if c == r:
            return True
        try:
            c.relative_to(r)
            return True
        except ValueError:
            return False
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 路径有效性检查（CLI 入口处使用）
# ---------------------------------------------------------------------------

@dataclass
class PathCheckResult:
    """路径检查结果。"""
    is_valid: bool
    is_directory: bool
    is_symlink: bool
    is_contained: bool  # 相对某个预期根目录；调用方需先调用 check_path
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.is_valid


def check_path(path: str | os.PathLike[str], must_be_directory: bool = True) -> PathCheckResult:
    """对用户传入路径做一次性的安全检查。

    返回的 PathCheckResult 包含失败原因，便于 CLI 输出清晰错误。
    """
    p = Path(path)

    # 路径字符串为空
    if not str(path) or str(path).strip() == "":
        return PathCheckResult(False, False, False, False, error="路径为空")

    # 检查是否为符号链接
    symlink = is_symlink(p)

    # 路径不存在
    if not p.exists():
        return PathCheckResult(
            False, False, symlink, False,
            error=f"路径不存在：{p}"
        )

    is_dir = p.is_dir()
    if must_be_directory and not is_dir:
        return PathCheckResult(
            False, False, symlink, False,
            error=f"预期是目录，但实际是文件：{p}"
        )

    if symlink:
        return PathCheckResult(
            False, is_dir, symlink, False,
            error=f"路径为符号链接或 junction，Time Machine 不跟随：{p}"
        )

    # 权限检查（尝试读取目录内容）
    try:
        if is_dir:
            next(p.iterdir(), None)
    except PermissionError:
        return PathCheckResult(
            False, is_dir, symlink, False,
            error=f"无权限访问该目录：{p}"
        )

    return PathCheckResult(True, is_dir, symlink, True, error=None)
