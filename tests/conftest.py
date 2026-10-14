"""pytest 公共 fixture。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


FIXTURES_ROOT = Path(__file__).parent / "fixtures"
PORTABLE_SAMPLE = FIXTURES_ROOT / "portable_sample"


@pytest.fixture
def portable_sample() -> Path:
    """返回只读的 ComfyUI Portable 夹具路径。"""
    return PORTABLE_SAMPLE


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    """一个干净的空目录。"""
    return tmp_path


@pytest.fixture
def random_dir(tmp_path: Path) -> Path:
    """一个包含随机文件但不是 ComfyUI 布局的目录。"""
    d = tmp_path / "some_random_dir"
    d.mkdir()
    (d / "notes.txt").write_text("hello", encoding="utf-8")
    (d / "sub").mkdir()
    return d


@pytest.fixture
def copy_of_portable(tmp_path: Path) -> Path:
    """复制一份可写的 Portable 夹具到 tmp_path，用于会修改的测试。"""
    target = tmp_path / "portable_copy"
    shutil.copytree(PORTABLE_SAMPLE, target)
    return target
