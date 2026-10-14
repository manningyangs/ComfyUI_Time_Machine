"""快照删除 Worker —— 带进度回调。"""
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from .base import BaseWorker


class SnapshotDeleteWorker(BaseWorker):
    """后台删除快照，实时发进度 + 日志。"""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, snapshot_id: int, store_dir: Path | str | None = None):
        super().__init__()
        self.snapshot_id = snapshot_id
        self.store_dir = store_dir
        self._progress_emit = None  # 在 run 里注入

    def run(self):
        try:
            from ...snapshots.manager import delete_snapshot

            self.progress.emit(2, "分析快照引用关系...")

            def cb(phase: str, done: int, total: int, detail: str):
                # 将内部进度映射到 0-100% 全局区间
                percent = self._phase_to_percent(phase, done, total)
                self.progress.emit(percent, f"{self._phase_label(phase)}  {detail}")

            self.log.emit(f"开始删除快照 #{self.snapshot_id}...")
            result = delete_snapshot(
                self.snapshot_id, progress_callback=cb, store_dir=self.store_dir
            )
            self.progress.emit(100, "删除完成")
            self.log.emit(
                f"✓ 删除完成：{result['total_files']} 文件 / "
                f"释放约 {result['estimated_bytes_to_free'] / 1024 / 1024:.1f} MB"
            )
            self.finished_ok.emit(result)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n{traceback.format_exc()}")

    def _phase_to_percent(self, phase: str, done: int, total: int) -> int:
        """把内部阶段进度映射到全局 0-100%。"""
        ranges = {
            "analyzing": (0, 5),
            "sql_refs": (5, 40),
            "gc_blobs": (40, 95),
            "done": (100, 100),
            "failed": (100, 100),
        }
        lo, hi = ranges.get(phase, (0, 100))
        if total == 0 or phase in ("analyzing", "done", "failed"):
            return hi
        return int(lo + (done / total) * (hi - lo))

    def _phase_label(self, phase: str) -> str:
        return {
            "analyzing": "分析中",
            "sql_refs":  "清理数据库",
            "gc_blobs":  "GC blob文件",
            "done":      "完成",
            "failed":    "失败",
        }.get(phase, phase)
