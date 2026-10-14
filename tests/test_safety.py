"""safety.py 的单元测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from comfyui_time_machine.safety import (
    check_path,
    is_path_contained_within,
    is_symlink,
    normalize_path,
    safe_resolve,
    should_follow,
)


class TestNormalizePath:
    def test_absolute_path_stays(self):
        p = normalize_path("C:/foo/bar")
        assert p.is_absolute()
        assert str(p) == os.path.normpath("C:/foo/bar")

    def test_relative_becomes_absolute(self, tmp_path):
        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            p = normalize_path("foo/bar")
            assert p.is_absolute()
        finally:
            os.chdir(old_cwd)

    def test_dots_removed(self):
        p = normalize_path("C:/foo/bar/../baz/./qux")
        # normpath 会去掉 .. 和 .
        assert ".." not in str(p)


class TestIsPathContained:
    def test_same_path(self, tmp_path):
        assert is_path_contained_within(tmp_path, tmp_path) is True

    def test_child_path(self, tmp_path):
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)
        assert is_path_contained_within(child, tmp_path) is True

    def test_parent_path(self, tmp_path):
        parent = tmp_path.parent
        assert is_path_contained_within(tmp_path, parent) is True

    def test_unrelated_path(self, tmp_path):
        other = tmp_path.parent / "other"
        assert is_path_contained_within(other, tmp_path) is False


class TestIsSymlink:
    def test_normal_file_not_symlink(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hi")
        assert is_symlink(f) is False

    @pytest.mark.skipif(
        os.name != "nt" or not hasattr(os, "symlink"),
        reason="非 Windows 或不支持 os.symlink",
    )
    def test_symlink_detected(self, tmp_path):
        target = tmp_path / "real.txt"
        target.write_text("real")
        link = tmp_path / "link.txt"
        # 只有管理员或开发者模式下才成功
        try:
            os.symlink(target, link)
        except OSError:
            pytest.skip("创建符号链接需要管理员或开发者模式")
        assert is_symlink(link) is True


class TestCheckPath:
    def test_empty_string(self):
        result = check_path("", must_be_directory=True)
        assert result.is_valid is False
        assert "为空" in (result.error or "")

    def test_path_not_exist(self, tmp_path):
        result = check_path(tmp_path / "nonexistent", must_be_directory=True)
        assert result.is_valid is False
        assert "不存在" in (result.error or "")

    def test_file_instead_of_dir(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = check_path(f, must_be_directory=True)
        assert result.is_valid is False
        assert "文件" in (result.error or "")

    def test_valid_directory(self, tmp_path):
        result = check_path(tmp_path, must_be_directory=True)
        assert result.is_valid is True
        assert result.is_directory is True

    def test_valid_file_when_not_dir_required(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = check_path(f, must_be_directory=False)
        assert result.is_valid is True
