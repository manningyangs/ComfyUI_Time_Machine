"""TASK-013：创建 / 校验 / 删除快照的高层编排。"""

from __future__ import annotations

import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ..models import (
    ComfyUIInstallation,
    CustomNodeInfo,
    DetectionStatus,
    GitInfo,
    PythonEnvInfo,
    ScanReport,
)
from .scope import SnapshotScope, ScopeItem, compute_scope
from .store import SnapshotStore


@dataclass
class CreateProgress:
    """创建快照过程中的进度信息（供 CLI / GUI 显示）。"""
    total_items: int = 0
    done_items: int = 0
    current_path: str = ""
    phase: str = ""           # walking | hashing | storing | verifying | committed | failed
    error: Optional[str] = None
    cancelled: bool = False
    stored_blobs: int = 0
    skipped_duplicates: int = 0

    # 阶段 → 全局进度区间 (min%, max%)
    _PHASE_RANGE = {
        "walking":   (0, 5),     # 计算范围，不慢
        "hashing":   (5, 55),    # 逐文件算 SHA-256，主要耗时
        "storing":   (55, 95),   # 原子写入 blob
        "verifying": (95, 99),   # SQLite 登记 + 回校验
        "committed": (100, 100),
        "failed":    (100, 100),
        "cancelled": (100, 100),
    }

    @property
    def percent(self) -> float:
        """全局单调递增百分比（0-100）。"""
        lo, hi = self._PHASE_RANGE.get(self.phase, (0, 100))
        if self.phase in ("walking", "committed", "failed", "cancelled", "verifying"):
            return float(hi)
        if self.total_items == 0:
            return float(lo)
        sub = min(self.done_items, self.total_items) / self.total_items
        return lo + sub * (hi - lo)

    def phase_label(self) -> str:
        """阶段中文名。"""
        return {
            "walking":   "计算范围",
            "hashing":   "计算 SHA-256",
            "storing":   "写入 blob",
            "verifying": "校验快照",
            "committed": "完成",
            "failed":    "失败",
            "cancelled": "已取消",
        }.get(self.phase, self.phase)


def create_snapshot(
    install_root: Path,
    *,
    name: str,
    note: str = "",
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
    progress_callback=None,      # callback(CreateProgress)
    should_cancel=None,           # callable() -> bool
    scope: Optional[SnapshotScope] = None,
) -> int:
    """为指定 ComfyUI 安装创建一份快照。

    流程：
    1. 计算快照范围（scope）
    2. 遍历 scope 中的所有纳入文件，计算 SHA-256
    3. 逐个原子写入 blob（重复内容跳过）
    4. SQLite 登记快照
    5. 完整性校验

    返回 snapshot_id。取消 / 失败时会清理临时文件，但不会留下半成品快照。
    """
    if store is None:
        store = SnapshotStore(store_dir)

    progress = CreateProgress()

    try:
        # Phase 1: 计算范围
        progress.phase = "walking"
        progress_callback and progress_callback(progress)

        if scope is None:
            scope = compute_scope(install_root)

        # Phase 2: 并行计算 SHA-256（hashlib + I/O 混合，多线程有效）
        progress.phase = "hashing"
        progress.total_items = len(scope.included_items)

        files_for_snapshot: list[dict] = []
        max_workers = min(32, (os.cpu_count() or 8) + 4)

        def _hash_one(item_rel_path: str):
            full = install_root / item_rel_path
            if not full.is_file():
                return None
            sha = store.compute_sha256(full)
            if sha is None:
                return None
            st = full.stat()
            return {
                "rel_path": item_rel_path,
                "sha256": sha,
                "size_bytes": st.st_size,
                "modified_at": dt.datetime.fromtimestamp(st.st_mtime).isoformat(),
                "file_mode": "blob",
            }

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_hash_one, item.rel_path): item.rel_path
                for item in scope.included_items
            }
            done_count = 0
            for fut in as_completed(futures):
                if should_cancel and should_cancel():
                    progress.cancelled = True
                    progress.phase = "cancelled"
                    progress_callback and progress_callback(progress)
                    store.close()
                    raise InterruptedError("快照创建已取消")

                done_count += 1
                result = fut.result()
                if result is not None:
                    files_for_snapshot.append(result)

                progress.done_items = done_count
                progress.current_path = result["rel_path"] if result else futures[fut]
                progress_callback and progress_callback(progress)

        progress.done_items = progress.total_items
        progress_callback and progress_callback(progress)

        if should_cancel and should_cancel():
            progress.cancelled = True
            progress.phase = "cancelled"
            progress_callback and progress_callback(progress)
            store.close()
            raise InterruptedError("快照创建已取消")

        # Phase 3: 并行存储 blob（每个 blob 路径不同，天然线程安全）
        progress.phase = "storing"
        progress.total_items = len(files_for_snapshot)
        progress.done_items = 0

        def _store_one(f: dict):
            src_path = install_root / f["rel_path"]
            if store.blob_exists(f["sha256"]):
                return ("skip", f["rel_path"])
            else:
                store.store_blob_atomic(src_path)
                return ("store", f["rel_path"])

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_store_one, f): f for f in files_for_snapshot}
            done_count = 0
            for fut in as_completed(futures):
                if should_cancel and should_cancel():
                    progress.cancelled = True
                    progress.phase = "cancelled"
                    progress_callback and progress_callback(progress)
                    store.close()
                    raise InterruptedError("快照创建已取消")

                done_count += 1
                action, rel = fut.result()
                progress.current_path = rel
                progress.done_items = done_count
                if action == "skip":
                    progress.skipped_duplicates += 1
                else:
                    progress.stored_blobs += 1
                progress_callback and progress_callback(progress)

        # Phase 4: 写入 SQLite
        progress.phase = "verifying"
        progress_callback and progress_callback(progress)

        scope_json = json.dumps({
            "included": [asdict(it) for it in scope.included_items],
            "excluded": [asdict(it) for it in scope.excluded_items],
        }, ensure_ascii=False)

        snapshot_id = store.create_snapshot(
            name=name,
            install_root=install_root,
            files=files_for_snapshot,
            scope_json=scope_json,
            note=note,
        )

        progress.phase = "committed"
        progress_callback and progress_callback(progress)

        return snapshot_id

    except (InterruptedError, RuntimeError, Exception) as e:
        progress.error = str(e)
        progress.phase = "failed"
        progress_callback and progress_callback(progress)
        # 清理临时目录
        _clean_temp_dir(store.temp_dir)
        raise


def _clean_temp_dir(temp_dir: Path) -> None:
    """清理临时目录下残留的 .tmp 文件。"""
    try:
        if not temp_dir.is_dir():
            return
        for f in temp_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def delete_snapshot(
    snapshot_id: int,
    *,
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
    dry_run: bool = False,
    progress_callback=None,
) -> dict:
    """删除快照。dry_run=True 时只返回影响估算，不实际删除。

    progress_callback(phase: str, done: int, total: int, detail: str)
      phase: "analyzing" | "sql_refs" | "gc_blobs" | "done" | "failed"
    """
    if store is None:
        store = SnapshotStore(store_dir)
    return store.delete_snapshot(
        snapshot_id, dry_run=dry_run, progress_callback=progress_callback
    )


def list_snapshots(
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
) -> list[dict]:
    if store is None:
        store = SnapshotStore(store_dir)
    return store.list_snapshots()
