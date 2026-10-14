"""只读性回归测试 —— 证明扫描不会修改目标目录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from comfyui_time_machine.paths import identify_installation


def _snapshot_dir(dir_path: Path, exclude_patterns: tuple[str, ...] = ()) -> dict[str, dict]:
    """扫描目录，返回 {相对路径: {size, mtime, sha256}}。

    exclude_patterns: 相对路径包含这些片段就跳过。
    用于排除 .git/（Git 自身会在 status 等"只读"命令里刷新 index）、__pycache__ 等。
    """
    snap: dict[str, dict] = {}
    for p in sorted(dir_path.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(dir_path)).replace("\\", "/")
            if any(excl in rel for excl in exclude_patterns):
                continue
            h = hashlib.sha256()
            try:
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                snap[rel] = {
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                    "sha256": h.hexdigest(),
                }
            except OSError:
                snap[rel] = {"error": True}
    return snap


# 这些目录下的文件可能被 Git/Python 等工具自行维护，我们不算它们被我们修改
_EXCLUDE_FOR_READONLY = (
    ".git/",        # Git 会在 status/rev-parse 等命令里刷新 index 的 stat cache
    "__pycache__/",
    ".pytest_cache/",
)


class TestReadOnly:
    def test_paths_identification_does_not_modify_files(self, copy_of_portable):
        """identify_installation 调用前后，目标目录的文件清单、大小、mtime、hash 必须完全一致。"""
        before = _snapshot_dir(copy_of_portable)

        inst = identify_installation(copy_of_portable)
        assert inst.status.value is not None  # 只要函数返回即可

        after = _snapshot_dir(copy_of_portable)

        assert before == after, (
            "文件快照在 identify_installation 前后不同！"
            f"before 文件数: {len(before)}, after 文件数: {len(after)}"
        )

    def test_full_cli_scan_is_read_only(self, copy_of_portable, tmp_path):
        """完整 CLI scan 执行前后，目标目录不变。

        注意：.git/ 目录被排除 —— Git 自身在 status 等"只读"命令里会刷新 index 的 stat cache，
        这是 Git 的内部维护行为，不是我们写的。
        """
        from comfyui_time_machine.cli import cmd_scan
        import argparse

        before = _snapshot_dir(copy_of_portable, exclude_patterns=_EXCLUDE_FOR_READONLY)

        args = argparse.Namespace(
            root=str(copy_of_portable),
            out=str(tmp_path / "report.json"),
            force=False,
            verbose=False,
        )
        code = cmd_scan(args)
        assert code == 0 or code == 3 or code == 2

        after = _snapshot_dir(copy_of_portable, exclude_patterns=_EXCLUDE_FOR_READONLY)
        assert before == after, (
            "CLI scan 执行后目标目录被修改！"
            f"新增文件: {set(after.keys()) - set(before.keys())}\n"
            f"删除文件: {set(before.keys()) - set(after.keys())}\n"
            f"内容变化: {set(before.keys()) & set(after.keys()) - {k for k in before if before[k] == after.get(k)}}"
        )
