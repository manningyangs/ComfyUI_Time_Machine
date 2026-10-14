"""恢复 Worker。"""

from __future__ import annotations

from pathlib import Path

from .base import BaseWorker
from ...snapshots.restore import restore_snapshot, RestoreProgress


class RestoreWorker(BaseWorker):
    """后台恢复快照。"""

    def __init__(self, snapshot_id: int, install_root: Path, store_dir: Path | str | None = None):
        super().__init__()
        self.snapshot_id = snapshot_id
        self.install_root = install_root
        self.store_dir = store_dir

    def run(self):
        try:
            self.log.emit(f"开始恢复快照 #{self.snapshot_id} ...")

            def cb(p: RestoreProgress):
                self.progress.emit(
                    int((p.done_files / max(p.total_files, 1)) * 100) if p.total_files else 0,
                    f"[{p.phase}] {p.current_path or ''}"
                )

            plan = restore_snapshot(
                self.snapshot_id,
                self.install_root,
                store_dir=self.store_dir,
                progress_callback=cb,
            )

            self.log.emit(f"✓ 恢复完成！staging={plan.staging_size_bytes} bytes  backup={plan.backup_size_bytes} bytes")
            self.finished_ok.emit(plan)

        except Exception as e:
            self.failed.emit(f"恢复失败: {e}")
