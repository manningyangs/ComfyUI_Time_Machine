"""配置持久化 — settings.json，存储 install_root + store_dir。

打包后 config.json 放在 exe 同级目录（dist/ComfyUI_Time_Machine/config.json）。
开发模式下放在项目根目录。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


def _app_dir() -> Path:
    """返回配置文件应存放的目录（exe 同级 or CWD）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包：sys.executable 指向 exe
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _config_path() -> Path:
    return _app_dir() / "settings.json"


def _default_store_dir() -> Path:
    """默认快照目录 — exe 同级 data/snapshots，开发环境项目根。"""
    return _app_dir() / "data" / "snapshots"


def load() -> dict:
    """加载配置，缺失字段用默认值。返回 dict。"""
    path = _config_path()
    data: dict = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (json.JSONDecodeError, OSError):
            data = {}

    result = {
        "install_root": data.get("install_root") or "",
        "store_dir": data.get("store_dir") or str(_default_store_dir()),
    }
    return result


def save(install_root: Optional[str | Path], store_dir: Optional[str | Path]) -> None:
    """保存配置到 settings.json。"""
    path = _config_path()
    cfg = load()
    if install_root is not None:
        cfg["install_root"] = str(install_root) if install_root else ""
    if store_dir is not None:
        cfg["store_dir"] = str(store_dir)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
