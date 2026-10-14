"""首页 —— 安装信息、快照数量、磁盘空间概览。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt


class HomePage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 标题
        title = QLabel("ComfyUI Time Machine")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("保存、对比、恢复你的 ComfyUI 环境")
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        # 信息卡片
        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)

        card_style = """
        QFrame {
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 16px;
        }
        """

        def make_card(title: str, value: str, subtitle: str = "") -> QFrame:
            frame = QFrame()
            frame.setStyleSheet(card_style)
            v = QVBoxLayout(frame)
            t = QLabel(title)
            t.setStyleSheet("color: #888; font-size: 12px;")
            v.addWidget(t)
            val = QLabel(value)
            val.setStyleSheet("font-size: 18px; font-weight: bold;")
            v.addWidget(val)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setStyleSheet("color: #aaa; font-size: 11px;")
                v.addWidget(sub)
            return frame

        state = self.app_state
        install_card = make_card(
            "安装位置",
            str(state.install_root) if state.install_root else "未配置",
            f"类型: {state.install_type}" if state.install_type else "点击右上角齿轮配置",
        )
        cards.addWidget(install_card, 0, 0)

        snap_count = state.snapshot_count()
        snap_card = make_card(
            "快照数量",
            str(snap_count),
            "可用" if snap_count > 0 else "还没有快照",
        )
        cards.addWidget(snap_card, 0, 1)

        store_card = make_card(
            "快照存储",
            str(state.store_dir),
            self._disk_usage_hint(state.store_dir),
        )
        cards.addWidget(store_card, 1, 0)

        scan_card = make_card(
            "最近扫描",
            "暂无" if not state.last_scan else state.last_scan.get("scan_completed_at", ""),
            f"文件数: {state.last_scan.get('installation', {}).get('main_py', {}).get('exists', '')}" if state.last_scan else "",
        )
        cards.addWidget(scan_card, 1, 1)

        layout.addLayout(cards)

        # 快速按钮
        layout.addSpacing(8)
        btn_row = QHBoxLayout()

        scan_btn = QPushButton("🔍 开始扫描")
        scan_btn.clicked.connect(lambda: self.app_state.nav_to.emit("scan"))
        btn_row.addWidget(scan_btn)

        snap_btn = QPushButton("📸 创建快照")
        snap_btn.clicked.connect(lambda: self.app_state.nav_to.emit("snapshots"))
        btn_row.addWidget(snap_btn)

        diff_btn = QPushButton("📊 比较差异")
        diff_btn.clicked.connect(lambda: self.app_state.nav_to.emit("compare"))
        btn_row.addWidget(diff_btn)

        restore_btn = QPushButton("🔄 恢复")
        restore_btn.clicked.connect(lambda: self.app_state.nav_to.emit("restore"))
        btn_row.addWidget(restore_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

    def _disk_usage_hint(self, store_dir: Path) -> str:
        try:
            import shutil
            usage = shutil.disk_usage(str(store_dir.drive + "\\"))
            free_gb = usage.free / (1024**3)
            return f"剩余空间: {free_gb:.1f} GB"
        except Exception:
            return ""

    def refresh(self):
        # 首页刷新比较简单，暂时全重建
        from PySide6.QtWidgets import QFrame, QGridLayout, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
        # 让主窗口调用 refresh 时重新加载卡片数据
        pass
