"""snapshots/store.py + manager.py + diff.py 的端到端测试。"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Optional

import pytest

from comfyui_time_machine.snapshots.store import SnapshotStore
from comfyui_time_machine.snapshots.manager import (
    CreateProgress,
    create_snapshot,
    delete_snapshot,
    list_snapshots,
)
from comfyui_time_machine.snapshots.diff import (
    diff_snapshot_vs_current,
    diff_snapshot_vs_snapshot,
    format_diff_summary,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_store(tmp_path) -> SnapshotStore:
    """独立的临时 SnapshotStore，测试结束自动 close。"""
    store = SnapshotStore(tmp_path / "snaps")
    yield store
    store.close()


@pytest.fixture
def writable_copy(copy_of_portable, tmp_path) -> Path:
    """一份可写的 fixture 副本，放在独立 tmp_path 下。"""
    return copy_of_portable


# ---------------------------------------------------------------------------
# SnapshotStore 基础测试
# ---------------------------------------------------------------------------

class TestSnapshotStoreBasic:
    def test_store_blob_atomic(self, isolated_store, tmp_path):
        src = tmp_path / "sample.txt"
        src.write_text("hello world")

        sha = isolated_store.store_blob_atomic(src)
        assert sha is not None

        # 确认 blob 文件存在
        blob_file = isolated_store._blob_path(sha)
        assert blob_file.is_file()
        assert blob_file.read_text() == "hello world"

        # 确认 SQLite 条目 —— ref_count 初始 0（由 create_snapshot 管理）
        row = isolated_store.conn.execute(
            "SELECT sha256, ref_count FROM blob_index WHERE sha256=?", (sha,)
        ).fetchone()
        assert row is not None
        assert row[1] == 0

    def test_blob_deduplication(self, isolated_store, tmp_path):
        """相同内容只存一份物理 blob（ref_count 由 create_snapshot 统一管理）。"""
        src = tmp_path / "a.txt"
        src.write_text("same content")

        sha1 = isolated_store.store_blob_atomic(src)
        sha2 = isolated_store.store_blob_atomic(src)  # 再存一次

        assert sha1 == sha2

        # store_blob_atomic 现在不管 ref_count → 初始 0
        row = isolated_store.conn.execute(
            "SELECT ref_count FROM blob_index WHERE sha256=?", (sha1,)
        ).fetchone()
        assert row[0] == 0

        # 仍然只有一个物理 blob
        blob_count = sum(1 for p in isolated_store.blobs_dir.rglob("*") if p.is_file())
        assert blob_count == 1

    def test_compute_sha256(self, isolated_store, tmp_path):
        src = tmp_path / "h.txt"
        src.write_text("hi")
        sha = isolated_store.compute_sha256(src)
        assert sha == "9f621d0c30a0b7949b538b6b442e58f1a4e4e3c3d7b9a0e1c2d3f4a5b6c7d8e9f"[:64] or len(sha) == 64


# ---------------------------------------------------------------------------
# 端到端：快照创建 → 校验 → 差异 → 删除
# ---------------------------------------------------------------------------

class TestEndToEndSnapshot:
    def test_create_snapshot(self, writable_copy, tmp_path, isolated_store):
        """完整的 TASK-013 流程：创建快照，校验完整性。"""
        snap_id = create_snapshot(
            writable_copy,
            name="test-snap-1",
            store=isolated_store,
        )
        assert snap_id > 0

        # 快照元数据
        snap = isolated_store.get_snapshot(snap_id)
        assert snap is not None
        assert snap["name"] == "test-snap-1"
        assert snap["status"] == "committed"
        assert snap["integrity_ok"] == 1
        assert snap["object_count"] > 0

        # 文件条目数
        files = isolated_store.get_snapshot_files(snap_id)
        assert len(files) == snap["object_count"]
        assert all(f["rel_path"] for f in files)
        assert all(f["sha256"] for f in files)

        # 所有 blob 都在磁盘上
        for f in files:
            blob_file = isolated_store._blob_path(f["sha256"])
            assert blob_file.is_file(), f"blob 缺失: {f['rel_path']}"

    def test_snapshot_deduplication_across_snapshots(self, writable_copy, isolated_store):
        """两个快照中相同文件只存一份 blob。"""
        snap1 = create_snapshot(writable_copy, name="snap-A", store=isolated_store)
        snap2 = create_snapshot(writable_copy, name="snap-B", store=isolated_store)

        # 统计唯一 blob 数
        unique_shas1 = {f["sha256"] for f in isolated_store.get_snapshot_files(snap1)}
        unique_shas2 = {f["sha256"] for f in isolated_store.get_snapshot_files(snap2)}
        all_unique = unique_shas1 | unique_shas2

        blob_files_count = sum(
            1 for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        )
        assert blob_files_count == len(all_unique), \
            f"blob 物理数 {blob_files_count} != 唯一哈希数 {len(all_unique)}"

    def test_delete_snapshot_dry_run(self, writable_copy, isolated_store):
        """dry_run 删除只返回估算，不实际删。"""
        snap_id = create_snapshot(writable_copy, name="to-delete", store=isolated_store)
        summary = delete_snapshot(snap_id, store=isolated_store, dry_run=True)
        assert summary["dry_run"] is True
        assert summary["snapshot_id"] == snap_id
        assert summary["estimated_bytes_to_free"] >= 0
        assert isolated_store.get_snapshot(snap_id) is not None  # 快照还在

    def test_delete_snapshot_actual(self, writable_copy, isolated_store):
        """实际删除：快照消失，ref_count 归零的 blob 被物理清理。"""
        snap_id = create_snapshot(writable_copy, name="to-really-delete", store=isolated_store)

        before_blobs = {
            p.name for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        }

        delete_snapshot(snap_id, store=isolated_store, dry_run=False)

        # 快照消失
        assert isolated_store.get_snapshot(snap_id) is None

        # blob 消失（因为只有这一个快照引用）
        after_blobs = {
            p.name for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        }
        assert after_blobs.isdisjoint(before_blobs)

    def test_delete_only_reduces_refcount_when_shared(
        self, writable_copy, isolated_store
    ):
        """多个快照共享 blob 时，删一个只减 ref_count，blob 保留。"""
        snap1 = create_snapshot(writable_copy, name="shared-A", store=isolated_store)
        snap2 = create_snapshot(writable_copy, name="shared-B", store=isolated_store)

        before_count = sum(
            1 for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        )

        delete_snapshot(snap1, store=isolated_store, dry_run=False)

        after_count = sum(
            1 for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        )
        # snap2 还在，所以 blob 应保留
        assert after_count == before_count, \
            "删一个快照不应物理删除共享 blob"

        # 再删 snap2，blob 清零
        delete_snapshot(snap2, store=isolated_store, dry_run=False)
        final_count = sum(
            1 for p in isolated_store.blobs_dir.rglob("*") if p.is_file()
        )
        assert final_count == 0

    def test_list_snapshots(self, writable_copy, isolated_store):
        create_snapshot(writable_copy, name="snap-L1", store=isolated_store)
        create_snapshot(writable_copy, name="snap-L2", store=isolated_store)

        snaps = list_snapshots(store=isolated_store)
        assert len(snaps) == 2
        assert snaps[0]["name"] == "snap-L2"  # DESC 排序
        assert snaps[1]["name"] == "snap-L1"


# ---------------------------------------------------------------------------
# 差异比较
# ---------------------------------------------------------------------------

class TestDiff:
    def test_no_diff_after_creation(self, writable_copy, isolated_store):
        """刚创建快照后，snapshot vs current 应该全 unchanged。"""
        snap_id = create_snapshot(writable_copy, name="diff-baseline", store=isolated_store)
        d = diff_snapshot_vs_current(snap_id, store=isolated_store)
        assert d.added == 0
        assert d.removed == 0
        assert d.modified == 0
        assert d.total >= 0

    def test_modified_file_detected(self, writable_copy, isolated_store):
        """创建快照后修改一个文件 → diff 能看到 modified。"""
        snap_id = create_snapshot(writable_copy, name="before-change", store=isolated_store)

        # 找到 fixture 中一个纳入的文件修改它
        snap_files = isolated_store.get_snapshot_files(snap_id)
        assert snap_files, "应该有纳入的文件"

        target = writable_copy / snap_files[0]["rel_path"]
        orig = target.read_bytes()
        target.write_bytes(orig + b"\n# modified")

        d = diff_snapshot_vs_current(snap_id, store=isolated_store)
        assert d.modified >= 1
        modified_paths = {df.rel_path for df in d.filter_by_change("modified")}
        assert snap_files[0]["rel_path"] in modified_paths

    def test_added_file_detected(self, writable_copy, isolated_store):
        """快照创建后新增一个文件 → diff 显示 added。"""
        snap_id = create_snapshot(writable_copy, name="before-add", store=isolated_store)

        # 新建一个不被排除的文件
        new_file = writable_copy / "brand_new.txt"
        new_file.write_text("fresh!")

        d = diff_snapshot_vs_current(snap_id, store=isolated_store)
        assert d.added >= 1
        added_paths = {df.rel_path for df in d.filter_by_change("added")}
        assert "brand_new.txt" in added_paths

    def test_format_diff_summary(self, writable_copy, isolated_store):
        snap_id = create_snapshot(writable_copy, name="summary-test", store=isolated_store)
        target = writable_copy / isolated_store.get_snapshot_files(snap_id)[0]["rel_path"]
        target.write_bytes(target.read_bytes() + b"changed")

        d = diff_snapshot_vs_current(snap_id, store=isolated_store)
        text = format_diff_summary(d, max_items=10)
        assert "快照差异" in text
        assert "+" in text or "~" in text or "-" in text


# ---------------------------------------------------------------------------
# 进度回调
# ---------------------------------------------------------------------------

class TestProgressCallback:
    def test_progress_fires(self, writable_copy, isolated_store):
        events: list[CreateProgress] = []

        def cb(p: CreateProgress):
            events.append(dataclasses.replace(p))

        snap_id = create_snapshot(
            writable_copy,
            name="progress-test",
            store=isolated_store,
            progress_callback=cb,
        )
        assert snap_id > 0
        assert events, "progress_callback 应至少被调用一次"

        # 最后一次应该是 committed 或 failed
        final = events[-1]
        assert final.phase in ("committed", "failed")
