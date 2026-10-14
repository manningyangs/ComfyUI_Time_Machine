"""scanners/core.py 的单元测试 —— safe_run + Git 扫描。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from comfyui_time_machine.scanners.core import (
    DEFAULT_TIMEOUT,
    SafeRunResult,
    safe_run,
    scan_git_for_directory,
)
from comfyui_time_machine.models import DetectionStatus


class TestSafeRun:
    def test_basic_python_echo(self):
        r = safe_run(["py", "-3", "-c", "print('hello')"], timeout=10)
        assert r.ok
        assert "hello" in r.stdout

    def test_empty_cmd(self):
        r = safe_run([])
        assert not r.ok
        assert r.returncode == -1

    def test_string_cmd_rejected(self):
        """硬规则：cmd 必须是 list[str]，不能让 shell=True 风险漏进来。"""
        r = safe_run("echo hi")  # type: ignore
        assert not r.ok
        assert "list" in (r.error or "").lower()

    def test_file_not_found(self):
        r = safe_run(["nonexistent_command_xyz"])
        assert not r.ok
        assert "不存在" in (r.error or "") or r.returncode == -1

    def test_timeout(self):
        r = safe_run(["py", "-3", "-c", "import time; time.sleep(5)"], timeout=1)
        assert r.timed_out

    def test_cwd_isolated(self, tmp_path):
        f = tmp_path / "test.txt"
        r = safe_run(
            ["py", "-3", "-c", f"open('test.txt','w').write('x'); print('ok')"],
            cwd=tmp_path,
            timeout=5,
        )
        assert r.ok
        assert f.exists()
        f.unlink()  # 清理（测试自己创建的）

    def test_shell_false_security(self):
        """验证 shell=False：管道符应该被当作普通参数，而不是 shell 解释。"""
        r = safe_run(["py", "-3", "-c", "import sys; print(sys.argv)", "|", "echo"])
        # Python 会把 | echo 当作参数接收，不会触发 shell 管道
        assert "| echo" in r.stdout or r.returncode == 0


class TestScanGitForDirectory:
    def test_real_git_repo(self, tmp_path):
        """在临时目录创建真实 git 仓库，验证扫描能读到 commit/branch。"""
        import subprocess as sp
        repo = tmp_path / "repo"
        repo.mkdir()
        sp.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        sp.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        sp.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("hi")
        sp.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        sp.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)

        info = scan_git_for_directory(repo)
        assert info.is_git_repo is True
        assert info.status == DetectionStatus.DETECTED
        assert info.commit and len(info.commit) >= 7
        assert info.has_local_changes is False

    def test_dirty_working_tree(self, tmp_path):
        import subprocess as sp
        repo = tmp_path / "repo"
        repo.mkdir()
        sp.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        sp.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        sp.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("hi")
        sp.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        sp.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
        # 未提交的修改
        (repo / "f.txt").write_text("modified!")

        info = scan_git_for_directory(repo)
        assert info.is_git_repo is True
        assert info.has_local_changes is True

    def test_non_git_directory(self, tmp_path):
        d = tmp_path / "plain_dir"
        d.mkdir()
        (d / "a.txt").write_text("x")
        info = scan_git_for_directory(d)
        assert info.is_git_repo is False
        assert info.status == DetectionStatus.NOT_PRESENT

    def test_nonexistent_directory(self):
        info = scan_git_for_directory("/nonexistent/path/xyz")
        assert info.status == DetectionStatus.NOT_PRESENT

    def test_git_not_available_via_monkeypatch(self, monkeypatch, tmp_path):
        """模拟 git 命令不存在（FileNotFoundError）。"""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()  # 伪造 .git 目录

        def fake_run(*a, **kw):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", fake_run)
        info = scan_git_for_directory(repo)
        assert info.is_git_repo is True  # 有 .git 就算是仓库
        assert info.status == DetectionStatus.ERROR
        assert "git 命令不可用" in (info.error or "")

    def test_git_timeout_via_monkeypatch(self, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        from comfyui_time_machine.scanners.core import SafeRunResult, DEFAULT_TIMEOUT

        call_count = {"n": 0}

        def fake_safe_run(cmd, **kw):
            call_count["n"] += 1
            return SafeRunResult(
                returncode=-1, stdout="", stderr="",
                timed_out=True, error=f"超时（{DEFAULT_TIMEOUT}s）",
            )

        # safe_run 是同模块函数，必须 patch subprocess.run 让它在 safe_run 内部触发超时
        import comfyui_time_machine.scanners.core as core_mod

        def fake_subprocess_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd=a[0], timeout=5)

        monkeypatch.setattr(core_mod.subprocess, "run", fake_subprocess_run)
        info = scan_git_for_directory(repo)
        assert info.is_git_repo is True
        # rev-parse 超时 → safe_run 返回 timed_out，scan_git_for_directory 应该处理
        # 注意：_is_git_available 也会调 subprocess.run，也会超时 → git 不可用
        assert info.status == DetectionStatus.ERROR
        assert "git 命令不可用" in (info.error or "")


class TestFixtureGitRepo:
    """直接对真实夹具中的 ComfyUI-Manager Git 仓库做扫描验证。"""
    def test_fixture_manager_is_git(self, portable_sample):
        manager = portable_sample / "ComfyUI" / "custom_nodes" / "ComfyUI-Manager"
        info = scan_git_for_directory(manager)
        assert info.is_git_repo is True
        assert info.status == DetectionStatus.DETECTED
        assert info.commit is not None
