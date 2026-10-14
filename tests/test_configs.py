"""scanners/configs.py 的单元测试。"""

from __future__ import annotations

from pathlib import Path

from comfyui_time_machine.scanners.configs import scan_config_files


class TestScanConfigFiles:
    def test_fixture_finds_extra_model_paths(self, portable_sample):
        comfyui = portable_sample / "ComfyUI"
        results = scan_config_files(comfyui)
        names = [c.path.name for c in results]
        assert "extra_model_paths.yaml" in names
        target = next(c for c in results if c.path.name == "extra_model_paths.yaml")
        assert target.exists is True
        assert target.sha256 is not None  # 能算出 hash

    def test_missing_comfyui_dir(self, tmp_path):
        results = scan_config_files(None)
        assert results == []

        results2 = scan_config_files(tmp_path / "nope")
        assert results2 == []

    def test_hash_different_for_different_content(self, tmp_path):
        comfyui = tmp_path / "ComfyUI"
        comfyui.mkdir()
        f = comfyui / "extra_model_paths.yaml"
        f.write_text("model_path: /a")
        r1 = scan_config_files(comfyui)
        h1 = next(c.sha256 for c in r1 if c.path.name == "extra_model_paths.yaml")

        f.write_text("model_path: /b")
        r2 = scan_config_files(comfyui)
        h2 = next(c.sha256 for c in r2 if c.path.name == "extra_model_paths.yaml")

        assert h1 != h2

    def test_no_files_when_clean(self, tmp_path):
        comfyui = tmp_path / "ComfyUI"
        comfyui.mkdir()
        results = scan_config_files(comfyui)
        # 空目录下会列出"不在"的配置文件条目（exists=False）
        # 关键：不会崩溃
        assert len(results) > 0
        for r in results:
            assert r.exists is False


class TestConfigFileReadOnly:
    """证明 scan_config_files 不会修改目标文件。"""
    def test_read_only(self, portable_sample):
        import hashlib
        before = {}
        for f in portable_sample.rglob("*"):
            if f.is_file():
                before[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()

        scan_config_files(portable_sample / "ComfyUI")

        after = {}
        for f in portable_sample.rglob("*"):
            if f.is_file():
                after[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()

        assert before == after, "scan_config_files 修改了目标目录文件！"
