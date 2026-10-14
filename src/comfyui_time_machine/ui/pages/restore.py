"""恢复页 —— 预览范围、确认、执行进度。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QProgressBar, QPlainTextEdit, QCheckBox,
)
from PySide6.QtCore import Qt

from ..workers.restore import RestoreWorker


class RestorePage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self.worker: RestoreWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("恢复")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        # 快照选择
        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("选择快照 #"))
        self.snap_combo = QComboBox()
        self.snap_combo.setMinimumWidth(200)
        select_row.addWidget(self.snap_combo, 1)

        self.preview_btn = QPushButton("🔍 预览影响")
        self.preview_btn.clicked.connect(self._on_preview)
        select_row.addWidget(self.preview_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh_snap_list)
        select_row.addWidget(self.refresh_btn)

        select_row.addStretch()
        layout.addLayout(select_row)

        # 预览结果
        self.preview_label = QLabel("选择快照后点击「预览影响」")
        self.preview_label.setStyleSheet("color: #666; background: #f8f9fa; padding: 12px; border-radius: 6px;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        # 确认提示
        self.confirm_box = QCheckBox(
            "我已停止 ComfyUI 并确认安装路径正确\n"
            "恢复会覆盖快照中记录的文件（当前有快照但快照里没有的文件不会被删除）"
        )
        self.confirm_box.setStyleSheet("color: #c0392b; font-size: 12px;")
        self.confirm_box.stateChanged.connect(self._update_restore_btn)
        layout.addWidget(self.confirm_box)

        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        # 按钮行
        btn_row = QHBoxLayout()
        self.restore_btn = QPushButton("🔄 开始恢复")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._on_restore)
        btn_row.addWidget(self.restore_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 日志
        layout.addWidget(QLabel("执行日志:"))
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)

        self.refresh_snap_list()

    def _update_restore_btn(self):
        self.restore_btn.setEnabled(self.confirm_box.isChecked())

    def refresh_snap_list(self):
        self.snap_combo.clear()
        try:
            from ...snapshots.manager import list_snapshots
            snaps = list_snapshots(store_dir=self.app_state.store_dir)
            for s in snaps:
                label = f"#{s['id']} {s['name']}  [{s['status']}]  integrity={'✓' if s['integrity_ok']==1 else '✗'}"
                self.snap_combo.addItem(label, s["id"])
        except Exception:
            pass

    def _on_preview(self):
        sid = self.snap_combo.currentData()
        if sid is None or not self.app_state.install_root:
            QMessageBox.warning(self, "错误", "请先选择快照并配置安装路径")
            return

        try:
            from ...snapshots.restore import preview_restore
            plan = preview_restore(int(sid), self.app_state.install_root, store_dir=self.app_state.store_dir)

            mb = plan.staging_size_bytes / (1024 * 1024)
            self.preview_label.setText(
                f"📋 恢复计划预览\n\n"
                f"  快照 #{sid} → {self.app_state.install_root}\n\n"
                f"  📥 要新增:   {len(plan.to_add)}  个文件\n"
                f"  🔁 要覆盖:   {len(plan.to_overwrite)}  个文件  ({mb:.1f} MB)\n"
                f"  🗑️  要删除:   {len(plan.to_remove)}  个文件（保守策略默认不删）\n\n"
                f"  暂存大小: {plan.staging_size_bytes / (1024**3):.2f} GB\n"
                f"  备份大小: {plan.backup_size_bytes / (1024**2):.1f} MB\n\n"
                f"  当前有但快照没有的文件会被保留（保守策略）"
            )
        except Exception as e:
            self.preview_label.setText(f"✗ 预览失败: {e}")

    def _on_restore(self):
        sid = self.snap_combo.currentData()
        if sid is None:
            return

        confirm = QMessageBox.warning(
            self, "⚠️ 确认恢复",
            f"即将把快照 #{sid} 恢复到：\n{self.app_state.install_root}\n\n"
            f"这将覆盖 {self.preview_label.text()} 的内容\n\n"
            f"请确认 ComfyUI 已经停止。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.preview_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_area.clear()
        self.log_area.appendPlainText("▶ 开始恢复...")

        self.worker = RestoreWorker(int(sid), self.app_state.install_root, store_dir=self.app_state.store_dir)
        from PySide6.QtCore import Qt as _Qt
        self.worker.progress.connect(self._on_progress, _Qt.ConnectionType.QueuedConnection)
        self.worker.log.connect(lambda msg: self.log_area.appendPlainText(msg), _Qt.ConnectionType.QueuedConnection)
        cleanup = lambda: setattr(self, 'worker', None)
        self.worker.finished_ok.connect(lambda p: (self._on_done(p), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.failed.connect(lambda e: (self._on_failed(e), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)

    def _on_done(self, plan):
        self.progress_bar.setValue(100)
        self.status_label.setText("✓ 恢复完成！")
        self.log_area.appendPlainText(f"\n✅ L1 哈希验证通过")
        self.log_area.appendPlainText(f"   staging: {plan.staging_size_bytes / (1024**2):.1f} MB")
        self.log_area.appendPlainText(f"   backup:   {plan.backup_size_bytes / (1024**2):.1f} MB")
        self.preview_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._update_restore_btn()

        QMessageBox.information(self, "✓ 恢复完成", "文件恢复 + L1 哈希校验全部通过！")

    def _on_failed(self, err: str):
        self.progress_bar.setValue(0)
        self.status_label.setText(f"✗ 失败: {err}")
        self.log_area.appendPlainText(f"✗ {err}")
        self.preview_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._update_restore_btn()

    def _on_thread_finished(self):
        self.worker = None
