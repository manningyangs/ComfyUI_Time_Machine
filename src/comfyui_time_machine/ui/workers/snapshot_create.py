"""快照创建 Worker。"""

from __future__ import annotations

from pathlib import Path

from .base import BaseWorker
from ...snapshots.manager import create_snapshot, CreateProgress


class SnapshotCreateWorker(BaseWorker):
    """后台创建快照。"""

    def __init__(self, install_root: Path, name: str, note: str = "", store_dir: Path | str | None = None):
        super().__init__()
        self.install_root = install_root
        self.name = name
        self.note = note
        self.store_dir = store_dir

    def run(self):
        try:
            self.log.emit(f"创建快照 '{self.name}' ...")

            def cb(p: CreateProgress):
                label = p.phase_label()
                if p.total_items > 0:
                    detail = f"{p.done_items}/{p.total_items}"
                elif p.stored_blobs > 0:
                    detail = f"{p.stored_blobs} blob"
                else:
                    detail = ""
                path_tail = p.current_path[-50:] if len(p.current_path) > 50 else p.current_path
                msg = f"{label}...  {detail}  {path_tail}"
                self.progress.emit(int(p.percent), msg)
                if self.cancelled:
                    raise InterruptedError("用户取消")

            def cancel_check():
                return self.cancelled

            sid = create_snapshot(
                self.install_root,
                name=self.name,
                note=self.note,
                store_dir=self.store_dir,
                progress_callback=cb,
                should_cancel=cancel_check,
            )

            self.log.emit(f"✓ 快照 #{sid} 创建完成")
            self.finished_ok.emit(sid)

        except InterruptedError:
            self.failed.emit("已取消")
        except Exception as e:
            self.failed.emit(f"快照创建失败: {e}")
