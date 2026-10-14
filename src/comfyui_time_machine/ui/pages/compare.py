"""比较页 —— 当前 vs 快照 / 快照 vs 快照。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget,
)
from PySide6.QtCore import Qt


class ComparePage(QWidget):
    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("差异比较")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        # 快照选择
        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("快照 #"))
        self.snap_combo = QComboBox()
        self.snap_combo.setMinimumWidth(200)
        select_row.addWidget(self.snap_combo, 1)

        self.compare_btn = QPushButton("🔍 比较与当前")
        self.compare_btn.clicked.connect(self._on_compare)
        select_row.addWidget(self.compare_btn)

        self.refresh_btn = QPushButton("🔄 刷新列表")
        self.refresh_btn.clicked.connect(self.refresh_snap_list)
        select_row.addWidget(self.refresh_btn)

        select_row.addStretch()
        layout.addLayout(select_row)

        # 统计
        self.stats_label = QLabel("选择快照后点击比较")
        self.stats_label.setStyleSheet("color: #666;")
        layout.addWidget(self.stats_label)

        # 差异表格（按类型分 tab）
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._add_tab("新增 (+)")
        self._add_tab("修改 (~)")
        self._add_tab("删除 (-)")

        self.refresh_snap_list()

    def _add_tab(self, title: str) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["路径", "旧 SHA", "新 SHA", "大小变化"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(table, title)
        return table

    def refresh_snap_list(self):
        self.snap_combo.clear()
        try:
            from ...snapshots.manager import list_snapshots
            snaps = list_snapshots(store_dir=self.app_state.store_dir)
            for s in snaps:
                label = f"#{s['id']} {s['name']}  [{s['status']}]"
                self.snap_combo.addItem(label, s["id"])
        except Exception:
            pass

    def _on_compare(self):
        sid = self.snap_combo.currentData()
        if sid is None:
            self.stats_label.setText("请先选择快照")
            return

        try:
            from ...snapshots.diff import diff_snapshot_vs_current
            from ...snapshots.store import SnapshotStore

            store = SnapshotStore(self.app_state.store_dir)
            diff = diff_snapshot_vs_current(int(sid), store=store)

            self.stats_label.setText(
                f"总计 {diff.total}  |  新增: {diff.added}  修改: {diff.modified}  删除: {diff.removed}  未变: {diff.unchanged}"
            )

            # 填充 tab
            self._fill_tab(0, diff.filter_by_change("added"))
            self._fill_tab(1, diff.filter_by_change("modified"))
            self._fill_tab(2, diff.filter_by_change("removed"))

            store.close()

        except Exception as e:
            self.stats_label.setText(f"✗ 比较失败: {e}")

    def _fill_tab(self, tab_idx: int, diffs: list):
        table: QTableWidget = self.tabs.widget(tab_idx)
        table.setRowCount(len(diffs))
        for row, d in enumerate(diffs):
            table.setItem(row, 0, QTableWidgetItem(d.rel_path))
            table.setItem(row, 1, QTableWidgetItem((d.old_sha256 or "")[:16]))
            table.setItem(row, 2, QTableWidgetItem((d.new_sha256 or "")[:16]))
            old_sz = d.old_size or 0
            new_sz = d.new_size or 0
            delta = new_sz - old_sz
            if delta > 0:
                sz_text = f"+{delta}"
            elif delta < 0:
                sz_text = str(delta)
            else:
                sz_text = "—"
            table.setItem(row, 3, QTableWidgetItem(sz_text))
