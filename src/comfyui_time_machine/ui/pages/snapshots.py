"""快照页 —— 列表、创建、删除、完整性状态。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QLineEdit, QTextEdit, QDialogButtonBox, QMessageBox,
    QProgressBar, QPlainTextEdit,
)
from PySide6.QtCore import Qt

from ..workers.snapshot_create import SnapshotCreateWorker


class SnapshotsPage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("快照管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        self.create_btn = QPushButton("📸 创建快照")
        self.create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(self.create_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)

        self.delete_btn = QPushButton("🗑️ 删除选中")
        self.delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self.delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 快照表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID", "名称", "状态", "完整性", "文件数", "大小", "创建时间",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.refresh()

    def refresh(self):
        from ...snapshots.manager import list_snapshots
        snaps = list_snapshots(store_dir=self.app_state.store_dir)
        self.table.setRowCount(len(snaps))
        for row, s in enumerate(snaps):
            self.table.setItem(row, 0, QTableWidgetItem(str(s["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(s["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(s["status"]))
            integrity = "✓" if s["integrity_ok"] == 1 else "✗"
            self.table.setItem(row, 3, QTableWidgetItem(integrity))
            self.table.setItem(row, 4, QTableWidgetItem(str(s["object_count"])))
            size_mb = (s["total_size"] or 0) / (1024 * 1024)
            self.table.setItem(row, 5, QTableWidgetItem(f"{size_mb:.1f} MB"))
            self.table.setItem(row, 6, QTableWidgetItem(s["created_at"]))

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return int(item.text())

    def _on_create(self):
        dlg = CreateSnapshotDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        if not self.app_state.install_root:
            QMessageBox.warning(self, "错误", "请先配置安装路径")
            return

        name, note = dlg.name_edit.text(), dlg.note_edit.toPlainText()
        if not name.strip():
            QMessageBox.warning(self, "错误", "快照名称不能为空")
            return

        self.create_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        worker = SnapshotCreateWorker(self.app_state.install_root, name.strip(), note.strip(), store_dir=self.app_state.store_dir)

        # 存在 self 上防止 GC 回收
        self._progress_dlg = _CreateProgressDialog(self)
        self._progress_dlg.setWindowTitle(f"创建快照 — {name.strip()}")
        self._progress_dlg.setModal(False)
        self._progress_dlg.cancel_btn.clicked.connect(worker.cancel)
        self._progress_dlg.closeEvent = lambda e: None  # 不允许关，必须等完成

        from PySide6.QtCore import Qt as _Qt
        dlg_ref = self._progress_dlg  # 持有引用避免闭包 GC
        worker.progress.connect(dlg_ref.on_progress, _Qt.ConnectionType.QueuedConnection)
        worker.log.connect(dlg_ref.on_log, _Qt.ConnectionType.QueuedConnection)
        cleanup = lambda: (self.create_btn.setEnabled(True), self.refresh_btn.setEnabled(True))

        def on_ok(sid):
            dlg_ref.mark_completed()
            self._on_created(sid, dlg_ref)
            cleanup()

        def on_err(err):
            dlg_ref.mark_failed()
            self._on_create_failed(err, dlg_ref)
            cleanup()

        worker.finished_ok.connect(on_ok, _Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(on_err, _Qt.ConnectionType.QueuedConnection)
        worker.start()

        self._progress_dlg.show()

    def _on_created(self, sid: int, dlg):
        # 先刷新列表（必须在任何模态对话框之前，否则可能被阻塞）
        self.refresh()
        self.app_state.updated.emit()
        QMessageBox.information(self, "✓ 完成", f"快照 #{sid} 创建成功！")
        self._progress_dlg = None  # 释放引用允许 GC

    def _on_create_failed(self, err: str, dlg):
        # mark_failed 已在 on_err 里调过
        QMessageBox.critical(self, "✗ 失败", err)
        self._progress_dlg = None  # 释放引用允许 GC

    def _on_delete(self):
        sid = self._selected_id()
        if sid is None:
            QMessageBox.warning(self, "提示", "请先选中要删除的快照")
            return

        confirm = QMessageBox.question(
            self, "确认删除",
            f"确定要删除快照 #{sid} 吗？\n\n会释放其独占的磁盘空间。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        from ...ui.workers.snapshot_delete import SnapshotDeleteWorker

        self.delete_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        worker = SnapshotDeleteWorker(sid, store_dir=self.app_state.store_dir)
        self._delete_dlg = _CreateProgressDialog(self)  # 复用同一进度对话框类
        self._delete_dlg.setWindowTitle(f"删除快照 — #{sid}")
        self._delete_dlg.setModal(False)
        self._delete_dlg.cancel_btn.setEnabled(False)  # 删除不允许取消

        from PySide6.QtCore import Qt as _Qt
        dlg_ref = self._delete_dlg
        worker.progress.connect(dlg_ref.on_progress, _Qt.ConnectionType.QueuedConnection)
        worker.log.connect(dlg_ref.on_log, _Qt.ConnectionType.QueuedConnection)

        def on_ok(result):
            dlg_ref.mark_completed()
            self._on_deleted(result, dlg_ref)

        def on_err(err):
            dlg_ref.mark_failed()
            self._on_delete_failed(err, dlg_ref)

        worker.finished_ok.connect(on_ok, _Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(on_err, _Qt.ConnectionType.QueuedConnection)
        worker.start()
        self._delete_dlg.show()

    def _on_deleted(self, result: dict, dlg):
        # 先刷新列表，再弹对话框
        self.refresh()
        self.app_state.updated.emit()
        mb = QMessageBox(self)
        mb.setWindowTitle("✓ 删除完成")
        mb.setText(
            f"快照 #{result['snapshot_id']} 已删除\n"
            f"释放空间: {result['estimated_bytes_to_free'] / (1024**2):.1f} MB"
        )
        mb.setIcon(QMessageBox.Information)
        mb.exec()
        self.delete_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._delete_dlg = None

    def _on_delete_failed(self, err: str, dlg):
        QMessageBox.critical(self, "✗ 删除失败", err)
        self.delete_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._delete_dlg = None


class CreateSnapshotDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建快照")
        self.resize(400, 300)

        v = QVBoxLayout(self)

        v.addWidget(QLabel("快照名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 v8.3-baseline-20261014")
        v.addWidget(self.name_edit)

        v.addWidget(QLabel("备注:"))
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("选填，描述这份快照的用途...")
        v.addWidget(self.note_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)


class _CreateProgressDialog(QDialog):
    """快照创建进度对话框（真正带 QProgressBar 的那个）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建快照")
        self.resize(520, 360)
        self.setWindowModality(Qt.WindowModal)

        v = QVBoxLayout(self)

        self.status_label = QLabel("准备中...")
        v.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        v.addWidget(self.progress_bar)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumBlockCount(200)
        v.addWidget(self.log_area, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("取消")
        btn_row.addWidget(self.cancel_btn)
        v.addLayout(btn_row)

        self._cancelled = False

    def on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        if msg:
            self.log_area.appendPlainText(msg)

    def on_log(self, msg: str):
        self.log_area.appendPlainText(msg)

    def mark_completed(self):
        """完成后：进度条满、按钮换成关闭。"""
        self.progress_bar.setValue(100)
        self.cancel_btn.setText("关闭")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.close)
        self.setWindowTitle("快照创建 — 完成 ✓")

    def mark_failed(self):
        """失败后：按钮换成关闭。"""
        self.cancel_btn.setText("关闭")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.close)
        self.setWindowTitle("快照创建 — 失败 ✗")
