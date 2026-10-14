"""主窗口 —— 左侧导航 + 右侧 QStackedWidget。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QStackedWidget,
    QMessageBox, QFileDialog, QInputDialog, QDialog, QLineEdit,
    QDialogButtonBox, QGroupBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from .state import AppState
from .pages.home import HomePage
from .pages.scan import ScanPage
from .pages.snapshots import SnapshotsPage
from .pages.compare import ComparePage
from .pages.restore import RestorePage
from .pages.verify import VerifyPage


NAV_ITEMS = [
    ("🏠", "首页", "home"),
    ("🔍", "扫描", "scan"),
    ("📸", "快照", "snapshots"),
    ("📊", "比较", "compare"),
    ("🔄", "恢复", "restore"),
    ("✅", "验证", "verify"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Time Machine")
        self.resize(1100, 700)

        self.app_state = AppState()
        self._auto_detect_install_root()

        self._build_ui()

        # 全局导航
        self.app_state.nav_to.connect(self._nav_to)

    def _auto_detect_install_root(self):
        """尝试自动探测常见位置，探测失败就让用户手动设置。"""
        candidates = [
            r"F:\2026-ComfyUI-V8.3",
            r"D:\ComfyUI_windows_portable",
            r"E:\ComfyUI_windows_portable",
            r"F:\ComfyUI_windows_portable",
        ]
        from ._detect import try_detect
        for c in candidates:
            result = try_detect(c)
            if result is not None:
                self.app_state.install_root = c
                self.app_state.install_type = result.type.value if result.type else ""
                return

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- 左侧导航 ----
        nav_frame = QWidget()
        nav_frame.setFixedWidth(180)
        nav_frame.setStyleSheet("""
            QWidget { background: #2c3e50; color: #ecf0f1; }
            QListWidget {
                background: #2c3e50; border: none; outline: none;
                color: #ecf0f1; padding: 8px; font-size: 14px;
            }
            QListWidget::item { padding: 12px 16px; border-radius: 6px; }
            QListWidget::item:selected { background: #3498db; }
            QListWidget::item:hover { background: #34495e; }
        """)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(8)

        app_title = QLabel("⏰ Time Machine")
        app_title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        nav_layout.addWidget(app_title)

        sub_title = QLabel("v0.1.0")
        sub_title.setStyleSheet("color: #95a5a6; font-size: 11px; padding: 0 8px 12px;")
        nav_layout.addWidget(sub_title)

        self.nav_list = QListWidget()
        self.nav_list.currentRowChanged.connect(self._on_nav_row_changed)
        for icon, label, key in NAV_ITEMS:
            item = QListWidgetItem(f"{icon}  {label}")
            item.setData(Qt.UserRole, key)
            self.nav_list.addItem(item)
        nav_layout.addWidget(self.nav_list, 1)

        # 设置按钮
        settings_btn = QPushButton("⚙️  配置")
        settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #ecf0f1;
                border: 1px solid #7f8c8d; border-radius: 6px;
                padding: 8px; font-size: 13px;
            }
            QPushButton:hover { background: #34495e; }
        """)
        settings_btn.clicked.connect(self._open_settings)
        nav_layout.addWidget(settings_btn)

        main_layout.addWidget(nav_frame)

        # ---- 右侧页面堆叠 ----
        self.stack = QStackedWidget()
        self.pages = {
            "home": HomePage(self.app_state),
            "scan": ScanPage(self.app_state),
            "snapshots": SnapshotsPage(self.app_state),
            "compare": ComparePage(self.app_state),
            "restore": RestorePage(self.app_state),
            "verify": VerifyPage(self.app_state),
        }
        # 按 NAV_ITEMS 顺序加入
        for _, _, key in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        main_layout.addWidget(self.stack, 1)

        # 默认选中首页
        self.nav_list.setCurrentRow(0)

        # 状态变化 → 刷新当前页
        self.app_state.updated.connect(self._refresh_current_page)

    def _on_nav_row_changed(self, row: int):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            current_page = self.stack.currentWidget()
            if hasattr(current_page, "refresh"):
                current_page.refresh()

    def _nav_to(self, key: str):
        for i, (_, _, k) in enumerate(NAV_ITEMS):
            if k == key:
                self.nav_list.setCurrentRow(i)
                return

    def _refresh_current_page(self):
        current_page = self.stack.currentWidget()
        if hasattr(current_page, "refresh"):
            current_page.refresh()

    def _open_settings(self):
        dlg = _SettingsDialog(self)
        dlg.install_edit.setText(str(self.app_state.install_root) if self.app_state.install_root else "")
        dlg.store_edit.setText(str(self.app_state.store_dir))

        if dlg.exec() != QDialog.Accepted:
            return

        new_install = dlg.install_edit.text().strip() or None
        new_store = dlg.store_edit.text().strip()

        # 如果快照存储目录变了，检查旧目录是否有数据
        old_store = self.app_state.store_dir
        if Path(new_store).resolve() != Path(old_store).resolve():
            old_store_resolved = Path(old_store)
            if old_store_resolved.is_dir():
                # 数一下旧目录的快照数量
                try:
                    old_db = old_store_resolved / "db.sqlite3"
                    if old_db.is_file():
                        import sqlite3
                        conn = sqlite3.connect(str(old_db))
                        old_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                        conn.close()
                        if old_count > 0:
                            ret = QMessageBox.warning(
                                self,
                                "⚠️ 切换快照存储位置",
                                f"旧位置有 {old_count} 份快照数据：\n{old_store_resolved}\n\n"
                                f"切换到新位置后，这些快照将不会在列表中显示。\n"
                                f"是否继续？",
                                QMessageBox.Yes | QMessageBox.No,
                            )
                            if ret != QMessageBox.Yes:
                                return
                except Exception:
                    pass

        # 应用新设置
        self.app_state.install_root = new_install
        self.app_state.store_dir = new_store

        # 持久化到 settings.json
        from .. import config as _cfg
        _cfg.save(new_install, new_store)

        QMessageBox.information(
            self, "✓ 设置已保存",
            f"安装路径：{new_install or '未配置'}\n快照存储：{new_store}"
        )


class _SettingsDialog(QDialog):
    """配置对话框 — ComfyUI 路径 + 快照存储路径。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 配置")
        self.resize(520, 280)

        v = QVBoxLayout(self)

        # ComfyUI 安装路径
        box1 = QGroupBox("ComfyUI 安装路径")
        lay1 = QHBoxLayout(box1)
        self.install_edit = QLineEdit()
        self.install_edit.setPlaceholderText("例如 F:\\2026-ComfyUI-V8.3")
        lay1.addWidget(self.install_edit, 1)
        browse1 = QPushButton("📂 浏览...")
        browse1.clicked.connect(self._browse_install)
        lay1.addWidget(browse1)
        v.addWidget(box1)

        # 快照存储路径
        box2 = QGroupBox("快照存储位置")
        lay2 = QHBoxLayout(box2)
        self.store_edit = QLineEdit()
        self.store_edit.setPlaceholderText("默认 exe 同级 data/snapshots")
        lay2.addWidget(self.store_edit, 1)
        browse2 = QPushButton("📂 浏览...")
        browse2.clicked.connect(self._browse_store)
        lay2.addWidget(browse2)
        v.addWidget(box2)

        hint = QLabel(
            "💡 快照存储位置可以选任何有足够磁盘空间的目录。\n"
            "切换存储位置不会删除旧数据，只是快照列表会显示新位置的快照。"
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addStretch()

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Save).setText("💾 保存")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        v.addWidget(btn_box)

    def _browse_install(self):
        path = QFileDialog.getExistingDirectory(self, "选择 ComfyUI 安装目录")
        if path:
            self.install_edit.setText(path)

    def _browse_store(self):
        path = QFileDialog.getExistingDirectory(self, "选择快照存储目录")
        if path:
            self.store_edit.setText(path)


def run_gui():
    """启动 GUI 主入口。"""
    import sys
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    # 高 DPI
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
