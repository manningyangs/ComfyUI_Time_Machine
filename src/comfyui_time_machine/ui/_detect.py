"""UI 启动前的安装路径快速探测。"""

from __future__ import annotations

from pathlib import Path

from ..paths import identify_installation


def try_detect(path: str):
    """尝试识别某个路径是否为 ComfyUI 安装。

    返回 ComfyUIInstallation 或 None。
    """
    try:
        root = Path(path)
        if not root.is_dir():
            return None
        result = identify_installation(root)
        if result.status.value in ("detected", "custom_comfyui_root", "comfyui_subdir_only"):
            return result
        return None
    except Exception:
        return None
