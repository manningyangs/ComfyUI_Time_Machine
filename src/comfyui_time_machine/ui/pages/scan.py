"""扫描页 —— 范围、进度、取消、警告。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt

from ..workers.scan import ScanWorker


class ScanPage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self.worker: ScanWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("扫描")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        # 当前路径 + 浏览
        path_row = QHBoxLayout()
        self.path_label = QLabel(str(self.app_state.install_root or "（未配置）"))
        self.path_label.setStyleSheet("color: #555;")
        path_row.addWidget(self.path_label, 1)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        # 状态文字
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        # 按钮行
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始扫描")
        self.start_btn.clicked.connect(self._start_scan)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 日志区域
        layout.addWidget(QLabel("扫描日志:"))
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("日志输出会出现在这里...")
        layout.addWidget(self.log_area, 1)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择 ComfyUI 安装目录")
        if d:
            self.app_state.install_root = d
            self.path_label.setText(d)

    def _start_scan(self):
        if not self.app_state.install_root:
            QMessageBox.warning(self, "无法开始", "请先配置 ComfyUI 安装路径")
            return

        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = ScanWorker(self.app_state.install_root)
        from PySide6.QtCore import Qt as _Qt
        self.worker.progress.connect(self._on_progress, _Qt.ConnectionType.QueuedConnection)
        self.worker.log.connect(self._on_log, _Qt.ConnectionType.QueuedConnection)
        cleanup = lambda: setattr(self, 'worker', None)
        self.worker.finished_ok.connect(lambda r: (self._on_done(r), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.failed.connect(lambda e: (self._on_failed(e), cleanup()), _Qt.ConnectionType.QueuedConnection)
        self.worker.start()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
            self.log_area.appendPlainText("取消请求已发送...")

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)

    def _on_log(self, msg: str):
        self.log_area.appendPlainText(msg)

    def _on_done(self, report: dict):
        self.progress_bar.setValue(100)
        self.status_label.setText("✓ 扫描完成")
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.app_state.last_scan = report
        self.app_state.updated.emit()
        self.log_area.appendPlainText(f"\n✓ 扫描成功完成！快照数量: {self.app_state.snapshot_count()}")

    def _on_failed(self, err: str):
        self.progress_bar.setValue(0)
        self.status_label.setText(f"✗ 失败: {err}")
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.log_area.appendPlainText(f"✗ {err}")

    def _on_thread_finished(self):
        self.worker = None

    def refresh(self):
        self.path_label.setText(str(self.app_state.install_root or "（未配置）"))
