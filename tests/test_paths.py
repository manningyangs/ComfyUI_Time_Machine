"""paths.py 的单元测试 —— ComfyUI 安装识别。"""

from __future__ import annotations

import pytest

from comfyui_time_machine.models import DetectionStatus, InstallationType
from comfyui_time_machine.paths import identify_installation


class TestIdentifyInstallation:
    def test_portable_sample_detected(self, portable_sample):
        inst = identify_installation(portable_sample)
        assert inst.status == DetectionStatus.DETECTED
        assert inst.type == InstallationType.PORTABLE_WINDOWS
        assert inst.root_path is not None
        assert inst.comfyui_path is not None
        assert inst.main_py.exists is True
        assert inst.python_embeded.exists is True

    def test_comfyui_path_correct(self, portable_sample):
        inst = identify_installation(portable_sample)
        expected_comfyui = portable_sample / "ComfyUI"
        assert inst.comfyui_path == expected_comfyui

    def test_python_embeded_path_correct(self, portable_sample):
        inst = identify_installation(portable_sample)
        expected_py = portable_sample / "python_embeded"
        assert inst.python_embeded.path == expected_py

    def test_non_existent_path(self, empty_dir):
        inst = identify_installation(str(empty_dir / "does_not_exist"))
        assert inst.status == DetectionStatus.ERROR
        assert inst.error is not None

    def test_random_dir_not_comfyui(self, random_dir):
        inst = identify_installation(random_dir)
        # 随机目录应被判定为 NOT_PRESENT 或 unknown
        assert inst.status in (DetectionStatus.NOT_PRESENT, DetectionStatus.UNKNOWN)

    def test_empty_dir_not_comfyui(self, tmp_path):
        inst = identify_installation(tmp_path)
        assert inst.status in (DetectionStatus.NOT_PRESENT, DetectionStatus.UNKNOWN)

    def test_user_passes_comfyui_subdir_directly(self, portable_sample):
        """用户直接把 ComfyUI/ 子目录当作 --root 传入，也应能识别。"""
        inst = identify_installation(portable_sample / "ComfyUI")
        # 此时我们能找到 main.py，应该回退到父目录找 python_embeded
        assert inst.comfyui_path is not None
        assert inst.main_py.exists is True

    def test_path_with_spaces(self, copy_of_portable, tmp_path):
        """路径含空格（中文）时也能识别。"""
        spaced = tmp_path / "包含 空格的 路径"
        spaced.mkdir()
        from pathlib import Path as P
        import shutil
        shutil.copytree(copy_of_portable, spaced / "ComfyUI_windows_portable")
        inst = identify_installation(spaced / "ComfyUI_windows_portable")
        assert inst.status == DetectionStatus.DETECTED

    def test_path_with_chinese(self, copy_of_portable, tmp_path):
        """路径含中文字符。"""
        cn = tmp_path / "项目备份"
        cn.mkdir()
        import shutil
        shutil.copytree(copy_of_portable, cn / "ComfyUI_windows_portable")
        inst = identify_installation(cn / "ComfyUI_windows_portable")
        assert inst.status == DetectionStatus.DETECTED


class TestIdentifyPartialLayouts:
    def test_missing_python_embeded_becomes_source_clone(self, tmp_path):
        """只有 ComfyUI 源码目录，没有 python_embeded → SOURCE_CLONE / UNKNOWN。"""
        comfy = tmp_path / "ComfyUI"
        comfy.mkdir()
        (comfy / "main.py").write_text("# placeholder")
        inst = identify_installation(tmp_path)
        # 期望不是 DETECTED，因为缺 python_embeded
        assert inst.status != DetectionStatus.DETECTED

    def test_missing_main_py(self, tmp_path):
        """有 ComfyUI/ 和 python_embeded/ 但没有 main.py。"""
        (tmp_path / "ComfyUI").mkdir()
        (tmp_path / "python_embeded").mkdir()
        inst = identify_installation(tmp_path)
        # main.py 缺失 → 不应判为 DETECTED
        assert inst.status != DetectionStatus.DETECTED

    def test_file_path_rejected(self, tmp_path):
        """传入的是文件而非目录。"""
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        inst = identify_installation(f)
        assert inst.status == DetectionStatus.ERROR
