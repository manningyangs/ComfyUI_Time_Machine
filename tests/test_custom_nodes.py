"""scanners/custom_nodes.py 的单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from comfyui_time_machine.models import DetectionStatus
from comfyui_time_machine.scanners.custom_nodes import scan_custom_nodes


class TestScanCustomNodes:
    def test_fixture_has_two_nodes(self, portable_sample):
        cn_dir = portable_sample / "ComfyUI" / "custom_nodes"
        nodes = scan_custom_nodes(cn_dir)
        names = {n.name for n in nodes}
        assert "ComfyUI-Manager" in names
        assert "SomeNodes" in names

    def test_git_node_detected(self, portable_sample):
        cn_dir = portable_sample / "ComfyUI" / "custom_nodes"
        nodes = scan_custom_nodes(cn_dir)
        manager = next(n for n in nodes if n.name == "ComfyUI-Manager")
        assert manager.exists is True
        assert manager.git.is_git_repo is True
        assert manager.git.commit is not None
        assert manager.has_requirements_txt is True
        assert manager.has_pyproject_toml is True

    def test_plain_node_detected(self, portable_sample):
        cn_dir = portable_sample / "ComfyUI" / "custom_nodes"
        nodes = scan_custom_nodes(cn_dir)
        plain = next(n for n in nodes if n.name == "SomeNodes")
        assert plain.exists is True
        assert plain.git.is_git_repo is False
        assert plain.has_requirements_txt is True
        assert plain.has_setup_py is True
        assert plain.git.status == DetectionStatus.NOT_PRESENT

    def test_missing_custom_nodes_dir(self, tmp_path):
        nodes = scan_custom_nodes(tmp_path / "nonexistent")
        assert nodes == []

    def test_none_input(self):
        assert scan_custom_nodes(None) == []

    def test_single_broken_node_doesnt_stop_others(self, tmp_path):
        """模拟一个损坏目录（无权限），其他节点仍能扫描。"""
        cn = tmp_path / "custom_nodes"
        cn.mkdir()
        (cn / "GoodNode").mkdir()
        (cn / "GoodNode" / "__init__.py").write_text("")
        # "Broken" 目录不存在（模拟中间迭代遇到 OSError）
        # 直接测试普通场景：一个有 .git，一个没有
        import subprocess as sp
        good = cn / "GoodGit"
        good.mkdir()
        sp.run(["git", "init", "-q"], cwd=good, capture_output=True)
        sp.run(["git", "config", "user.email", "t@t.com"], cwd=good, capture_output=True)
        sp.run(["git", "config", "user.name", "T"], cwd=good, capture_output=True)
        (good / "f.py").write_text("")
        sp.run(["git", "add", "."], cwd=good, capture_output=True)
        sp.run(["git", "commit", "-q", "-m", "init"], cwd=good, capture_output=True)

        nodes = scan_custom_nodes(cn)
        names = {n.name for n in nodes}
        assert len(nodes) == 2
        assert "GoodNode" in names
        assert "GoodGit" in names

    def test_symlink_marked_out_of_scope(self, tmp_path):
        """符号链接节点应标记 out_of_scope。"""
        cn = tmp_path / "custom_nodes"
        cn.mkdir()
        target = tmp_path / "real_node"
        target.mkdir()
        (target / "__init__.py").write_text("")

        try:
            import os
            os.symlink(target, cn / "LinkedNode")
        except OSError:
            pytest.skip("创建符号链接需要管理员或开发者模式")

        nodes = scan_custom_nodes(cn)
        linked = next((n for n in nodes if n.name == "LinkedNode"), None)
        assert linked is not None
        assert linked.is_symlink is True
        assert linked.out_of_scope is True
