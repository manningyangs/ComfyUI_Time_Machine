"""scanners/python_env.py 的单元测试 —— 重点测错误处理，用 monkeypatch 模拟 pip 输出。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from comfyui_time_machine.models import DetectionStatus
from comfyui_time_machine.scanners.python_env import (
    PIP_TIMEOUT,
    _find_python_exe,
    scan_python_environment,
)


class TestFindPythonExe:
    def test_finds_python_exe(self, portable_sample):
        embed = portable_sample / "python_embeded"
        py = _find_python_exe(embed)
        assert py is not None
        assert py.name == "python.exe"

    def test_missing_dir(self, tmp_path):
        assert _find_python_exe(tmp_path / "nope") is None


class TestScanPythonEnvironment:
    def test_none_input(self):
        info = scan_python_environment(None)
        assert info.status == DetectionStatus.NOT_PRESENT

    def test_missing_dir(self, tmp_path):
        info = scan_python_environment(tmp_path / "missing")
        assert info.status == DetectionStatus.NOT_PRESENT

    def test_no_python_exe(self, tmp_path):
        embed = tmp_path / "python_embeded"
        embed.mkdir()
        info = scan_python_environment(embed)
        assert info.status == DetectionStatus.NOT_PRESENT
        assert "python.exe" in (info.error or "")

    def test_success_with_monkeypatched_pip(self, tmp_path, monkeypatch):
        """模拟 pip list 正常返回 JSON。"""
        embed = tmp_path / "python_embeded"
        embed.mkdir()
        (embed / "python.exe").write_text("fake")

        fake_pip_packages = [
            {"name": "torch", "version": "2.1.0"},
            {"name": "numpy", "version": "1.26.2"},
        ]

        import comfyui_time_machine.scanners.python_env as m

        def fake_safe_run(cmd, **kw):
            if "pip" in cmd and "list" in cmd:
                from comfyui_time_machine.scanners.core import SafeRunResult
                return SafeRunResult(0, json.dumps(fake_pip_packages), "")
            if "pip" in cmd and "--version" in cmd:
                from comfyui_time_machine.scanners.core import SafeRunResult
                return SafeRunResult(0, "pip 24.0", "")
            if "--version" in cmd:
                from comfyui_time_machine.scanners.core import SafeRunResult
                return SafeRunResult(0, "", "Python 3.11.8")
            from comfyui_time_machine.scanners.core import SafeRunResult
            return SafeRunResult(-1, "", "", error="unexpected")

        monkeypatch.setattr(m, "safe_run", fake_safe_run)

        info = scan_python_environment(embed)
        assert info.status == DetectionStatus.DETECTED
        assert info.python_version == "3.11.8"
        assert info.pip_available is True
        assert info.pip_error is None
        assert len(info.packages) == 2
        assert info.packages[0].name == "torch"
        assert info.packages[1].version == "1.26.2"

    def test_pip_not_available(self, tmp_path, monkeypatch):
        embed = tmp_path / "python_embeded"
        embed.mkdir()
        (embed / "python.exe").write_text("fake")

        import comfyui_time_machine.scanners.python_env as m
        from comfyui_time_machine.scanners.core import SafeRunResult

        def fake_safe_run(cmd, **kw):
            if "--version" in cmd and "pip" not in cmd:
                return SafeRunResult(0, "", "Python 3.11.8")
            if "pip" in cmd:
                return SafeRunResult(1, "", "No module named pip")
            return SafeRunResult(-1, "", "", error="unexpected")

        monkeypatch.setattr(m, "safe_run", fake_safe_run)

        info = scan_python_environment(embed)
        assert info.status == DetectionStatus.DETECTED  # python 本身找到了
        assert info.pip_available is False
        assert info.python_version == "3.11.8"

    def test_pip_timeout(self, tmp_path, monkeypatch):
        embed = tmp_path / "python_embeded"
        embed.mkdir()
        (embed / "python.exe").write_text("fake")

        import comfyui_time_machine.scanners.python_env as m
        from comfyui_time_machine.scanners.core import SafeRunResult

        call_count = {"pip_list": 0}

        def fake_safe_run(cmd, **kw):
            if "--version" in cmd and "pip" not in cmd:
                return SafeRunResult(0, "", "Python 3.11.8")
            if "pip" in cmd and "--version" in cmd:
                return SafeRunResult(0, "pip 24.0", "")
            if "pip" in cmd and "list" in cmd:
                call_count["pip_list"] += 1
                return SafeRunResult(-1, "", "", timed_out=True, error=f"超时（{PIP_TIMEOUT}s）")
            return SafeRunResult(-1, "", "", error="unexpected")

        monkeypatch.setattr(m, "safe_run", fake_safe_run)

        info = scan_python_environment(embed)
        assert info.status == DetectionStatus.DETECTED
        assert info.pip_available is True  # pip 本身可用
        assert "超时" in (info.pip_error or "")
        assert info.packages == []
        assert call_count["pip_list"] == 1

    def test_pip_bad_json(self, tmp_path, monkeypatch):
        embed = tmp_path / "python_embeded"
        embed.mkdir()
        (embed / "python.exe").write_text("fake")

        import comfyui_time_machine.scanners.python_env as m
        from comfyui_time_machine.scanners.core import SafeRunResult

        def fake_safe_run(cmd, **kw):
            if "--version" in cmd and "pip" not in cmd:
                return SafeRunResult(0, "", "Python 3.11.8")
            if "pip" in cmd and "--version" in cmd:
                return SafeRunResult(0, "pip 24.0", "")
            if "pip" in cmd and "list" in cmd:
                return SafeRunResult(0, "not json output", "")
            return SafeRunResult(-1, "", "", error="unexpected")

        monkeypatch.setattr(m, "safe_run", fake_safe_run)

        info = scan_python_environment(embed)
        assert info.pip_available is True
        assert "JSON 解析" in (info.pip_error or "")
        assert info.packages == []
