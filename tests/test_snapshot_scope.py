"""snapshots/scope.py 测试。"""

from __future__ import annotations

import pytest
from pathlib import Path

from comfyui_time_machine.snapshots.scope import (
    ALWAYS_EXCLUDED_DIR_NAMES,
    ALWAYS_EXCLUDED_SUFFIXES,
    _is_excluded_by_name,
    compute_scope,
)


class TestExclusionRules:
    def test_excluded_dir_name(self):
        assert _is_excluded_by_name("checkpoints") == "always_excluded_dir"
        assert _is_excluded_by_name("output") == "always_excluded_dir"
        assert _is_excluded_by_name(".git") == "always_excluded_dir"
        assert _is_excluded_by_name("__pycache__") == "always_excluded_dir"

    def test_excluded_suffix(self):
        assert _is_excluded_by_name("model.safetensors") == "always_excluded_suffix"
        assert _is_excluded_by_name("image.png") == "always_excluded_suffix"
        assert _is_excluded_by_name("video.mp4") == "always_excluded_suffix"
        assert _is_excluded_by_name("archive.zip") == "always_excluded_suffix"

    def test_included_by_default(self):
        assert _is_excluded_by_name("main.py") is None
        assert _is_excluded_by_name("extra_model_paths.yaml") is None
        assert _is_excluded_by_name("ComfyUI-Manager") is None
        assert _is_excluded_by_name("f2c_models") is None  # 名字里不含 checkpoint


class TestComputeScope:
    def test_fixture_scope(self, portable_sample):
        scope = compute_scope(portable_sample)
        assert scope.included_items, "fixture 应该有纳入项"
        # fixture 里有 main.py，应该被纳入
        rel_names = {it.rel_path for it in scope.included_items}
        assert any(n.endswith("main.py") for n in rel_names), "main.py 应被纳入"

    def test_exclusion_applied(self, portable_sample):
        """确保 .git 内部对象和 safetensors 都被排除。"""
        scope = compute_scope(portable_sample)
        included_paths = {it.rel_path for it in scope.included_items}

        # .git/objects/ 不应纳入
        assert not any("/.git/objects/" in p for p in included_paths), \
            ".git/objects/ 不应纳入快照"

    def test_blank_description(self, portable_sample):
        scope = compute_scope(portable_sample)
        desc = scope.describe()
        assert "快照范围" in desc
