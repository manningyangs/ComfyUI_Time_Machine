"""cli.py 的基础测试 —— 只测参数解析和退出码，不测真实扫描输出路径细节。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from comfyui_time_machine.cli import main


class TestCLIBasic:
    def test_version(self):
        # 捕获 --version 输出
        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with pytest.raises(SystemExit) as exc:
                main(["--version"])
        finally:
            out = sys.stdout.getvalue()
            sys.stdout = old
        assert exc.value.code == 0
        assert "comfyui-time-machine" in out.lower()
        assert "0.1.0" in out

    def test_help(self):
        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with pytest.raises(SystemExit) as exc:
                main(["--help"])
        finally:
            out = sys.stdout.getvalue()
            sys.stdout = old
        assert exc.value.code == 0
        assert "scan" in out
        assert "ComfyUI Portable" in out

    def test_scan_requires_root(self):
        with pytest.raises(SystemExit) as exc:
            main(["scan"])
        # argparse 缺失必需参数退出码 2
        assert exc.value.code == 2


class TestCLIScan:
    def test_scan_portable_sample(self, portable_sample, tmp_path):
        out = tmp_path / "report.json"
        code = main(["scan", "--root", str(portable_sample), "--out", str(out)])
        assert code == 0
        assert out.exists()

        # JSON 可读
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema_version"] == "0.1"
        assert data["installation"]["type"] == "portable_windows"
        assert data["installation"]["status"] == "detected"

    def test_scan_nonexistent_dir_fails(self, tmp_path):
        code = main(["scan", "--root", str(tmp_path / "nope"), "--out", str(tmp_path / "report.json")])
        assert code != 0

    def test_scan_random_dir_fails(self, random_dir, tmp_path):
        code = main(["scan", "--root", str(random_dir), "--out", str(tmp_path / "report.json")])
        assert code != 0


class TestCLIExitCodes:
    def test_error_exit_code(self, tmp_path):
        code = main(["scan", "--root", str(tmp_path / "missing")])
        assert code == 2  # ERROR / NOT_PRESENT → 退出码 2
