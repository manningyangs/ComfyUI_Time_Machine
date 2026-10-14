"""全局应用状态 —— 跨页面共享 + 信号驱动刷新。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    """单例风格的应用状态容器。"""

    # 页面导航信号（携带目标页面 key）
    nav_to = Signal(str)
    # 状态变化通用信号（触发各页面刷新）
    updated = Signal()

    def __init__(self):
        super().__init__()

        # 从持久化配置加载
        from .. import config
        cfg = config.load()

        self._install_root: Path | None = Path(cfg["install_root"]) if cfg["install_root"] else None
        self._install_type: str = ""
        self._store_dir: Path = Path(cfg["store_dir"])
        self._last_scan: dict | None = None

    # --- install_root ---
    @property
    def install_root(self) -> Path | None:
        return self._install_root

    @install_root.setter
    def install_root(self, value: str | Path | None):
        self._install_root = Path(value) if value else None
        self.updated.emit()

    # --- install_type ---
    @property
    def install_type(self) -> str:
        return self._install_type

    @install_type.setter
    def install_type(self, value: str):
        self._install_type = value
        self.updated.emit()

    # --- store_dir ---
    @property
    def store_dir(self) -> Path:
        return self._store_dir

    @store_dir.setter
    def store_dir(self, value: str | Path):
        self._store_dir = Path(value)
        self.updated.emit()

    # --- last_scan ---
    @property
    def last_scan(self) -> dict | None:
        return self._last_scan

    @last_scan.setter
    def last_scan(self, value: dict | None):
        self._last_scan = value
        self.updated.emit()

    # --- helpers ---
    def snapshot_count(self) -> int:
        try:
            from ...snapshots.manager import list_snapshots
            return len(list_snapshots(store_dir=self._store_dir))
        except Exception:
            return 0
