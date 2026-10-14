"""验证页 —— L1 文件哈希校验（L2/L3 后续补）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QProgressBar, QPlainTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from ..workers.base import BaseWorker


class VerifyWorker(BaseWorker):
    """后台跑快照完整性校验。"""
    done = Signal(int, int)  # checked, corrupted

    def __init__(self, snapshot_id: int, store_dir=None):
        super().__init__()
        self.snapshot_id = snapshot_id
        self.store_dir = store_dir

    def run(self):
        try:
            from ...snapshots.store import SnapshotStore
            store = SnapshotStore(self.store_dir)
            files = store.get_snapshot_files(self.snapshot_id)
            total = len(files)
            corrupted = 0
            for i, f in enumerate(files):
                blob = store._blob_path(f["sha256"])
                if not blob.is_file():
                    self.log.emit(f"✗ blob 缺失: {f['rel_path']}")
                    corrupted += 1
                else:
                    actual = store.compute_sha256(blob)
                    if actual != f["sha256"]:
                        self.log.emit(f"✗ 损坏: {f['rel_path']}")
                        corrupted += 1
                self.progress.emit(int((i + 1) / total * 100), f"{i+1}/{total} {f['rel_path'][:60]}")
            store.close()
            self.log.emit(f"\n完成！共检查 {total} 个 blob，发现 {corrupted} 个损坏")
            self.done.emit(total, corrupted)
        except Exception as e:
            self.failed.emit(str(e))


class VerifyPage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self.worker: VerifyWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("验证")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel("L1 级校验：验证快照中每个 blob 的 SHA-256 完整性。")
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("选择快照 #"))
        self.snap_combo = QComboBox()
        self.snap_combo.setMinimumWidth(200)
        select_row.addWidget(self.snap_combo, 1)

        self.verify_btn = QPushButton("✅ 开始验证")
        self.verify_btn.clicked.connect(self._on_verify)
        select_row.addWidget(self.verify_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh_snap_list)
        select_row.addWidget(self.refresh_btn)
        select_row.addStretch()
        layout.addLayout(select_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("校验日志:"))
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)

        self.refresh_snap_list()

    def refresh_snap_list(self):
        self.snap_combo.clear()
        try:
            from ...snapshots.manager import list_snapshots
            snaps = list_snapshots(store_dir=self.app_state.store_dir)
            for s in snaps:
                label = f"#{s['id']} {s['name']}  integrity={'✓' if s['integrity_ok']==1 else '✗'}"
                self.snap_combo.addItem(label, s["id"])
        except Exception:
            pass

    def _on_verify(self):
        sid = self.snap_combo.currentData()
        if sid is None:
            QMessageBox.warning(self, "错误", "请先选择快照")
            return

        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.verify_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        self.worker = VerifyWorker(int(sid), self.app_state.store_dir)
        from PySide6.QtCore import Qt as _Qt
        self.worker.progress.connect(self._on_progress, _Qt.ConnectionType.QueuedConnection)
        self.worker.log.connect(lambda msg: self.log_area.appendPlainText(msg), _Qt.ConnectionType.QueuedConnection)
        cleanup = lambda: setattr(self, 'worker', None)
        self.worker.done.connect(lambda c, d: (self._on_done(c, d), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.failed.connect(lambda e: (self._on_failed(e), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)

    def _on_done(self, total: int, corrupted: int):
        self.status_label.setText("✓ 完成")
        self.verify_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        if corrupted == 0:
            QMessageBox.information(self, "✅ 完好", f"全部 {total} 个 blob 完整性通过！")
        else:
            QMessageBox.warning(self, "⚠️ 有损坏", f"{corrupted}/{total} 个 blob 已损坏，建议重新创建快照")

    def _on_failed(self, err: str):
        self.status_label.setText(f"✗ 失败: {err}")
        self.verify_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

    def _on_thread_finished(self):
        self.worker = None
