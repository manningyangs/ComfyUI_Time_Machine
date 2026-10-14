"""TASK-014：差异比较 —— 当前 vs 快照 / 快照 vs 快照。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .scope import compute_scope
from .store import SnapshotStore


@dataclass
class FileDiff:
    rel_path: str
    change: str           # 'added' | 'removed' | 'modified' | 'unchanged'
    old_sha256: Optional[str] = None
    new_sha256: Optional[str] = None
    old_size: Optional[int] = None
    new_size: Optional[int] = None


@dataclass
class SnapshotDiff:
    from_source: str       # 'current' | 'snapshot:<id>'
    to_source: str         # 'snapshot:<id>' | 'current'
    created_at: str
    total: int = 0
    added: int = 0
    removed: int = 0
    modified: int = 0
    unchanged: int = 0
    file_diffs: list[FileDiff] = field(default_factory=list)

    def filter_by_change(self, change_type: str) -> list[FileDiff]:
        return [d for d in self.file_diffs if d.change == change_type]

    def filter_by_path(self, pattern: str) -> list[FileDiff]:
        low = pattern.lower()
        return [d for d in self.file_diffs if low in d.rel_path.lower()]


def _snapshot_files_map(store: SnapshotStore, snapshot_id: int) -> dict[str, dict]:
    """返回 {rel_path: {sha256, size_bytes}} 。"""
    files = store.get_snapshot_files(snapshot_id)
    return {f["rel_path"]: {"sha256": f["sha256"], "size": f["size_bytes"]} for f in files}


def _current_files_map(install_root: Path) -> dict[str, dict]:
    """返回当前文件状态的 {rel_path: {sha256, size}} （基于 scope 纳入的文件）。"""
    from .scope import compute_scope
    from .store import SnapshotStore

    scope = compute_scope(install_root)
    result: dict[str, dict] = {}

    for item in scope.included_items:
        full = install_root / item.rel_path
        if not full.is_file():
            continue
        sha = SnapshotStore.compute_sha256(full)  # 静态方法，不创建 store
        if sha is None:
            continue
        result[item.rel_path] = {
            "sha256": sha,
            "size": full.stat().st_size,
        }

    return result


def diff_snapshot_vs_current(
    snapshot_id: int,
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
) -> SnapshotDiff:
    """比较快照 vs 当前文件系统。"""
    if store is None:
        store = SnapshotStore(store_dir)

    snap = store.get_snapshot(snapshot_id)
    if snap is None:
        raise ValueError(f"快照 {snapshot_id} 不存在")

    install_root = Path(snap["install_root"])
    snap_files = _snapshot_files_map(store, snapshot_id)
    cur_files = _current_files_map(install_root)

    diff = SnapshotDiff(
        from_source=f"snapshot:{snapshot_id}",
        to_source="current",
        created_at=dt.datetime.now().isoformat(),
    )

    all_paths = sorted(set(snap_files.keys()) | set(cur_files.keys()))
    for path in all_paths:
        s = snap_files.get(path)
        c = cur_files.get(path)

        if s and not c:
            diff.file_diffs.append(FileDiff(
                rel_path=path, change="removed",
                old_sha256=s["sha256"], old_size=s["size"],
            ))
            diff.removed += 1
        elif c and not s:
            diff.file_diffs.append(FileDiff(
                rel_path=path, change="added",
                new_sha256=c["sha256"], new_size=c["size"],
            ))
            diff.added += 1
        elif s and c:
            if s["sha256"] != c["sha256"]:
                diff.file_diffs.append(FileDiff(
                    rel_path=path, change="modified",
                    old_sha256=s["sha256"], old_size=s["size"],
                    new_sha256=c["sha256"], new_size=c["size"],
                ))
                diff.modified += 1
            else:
                diff.unchanged += 1

    diff.total = diff.added + diff.removed + diff.modified + diff.unchanged
    return diff


def diff_snapshot_vs_snapshot(
    snapshot_a: int,
    snapshot_b: int,
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
) -> SnapshotDiff:
    """比较两个快照。"""
    if store is None:
        store = SnapshotStore(store_dir)

    a = _snapshot_files_map(store, snapshot_a)
    b = _snapshot_files_map(store, snapshot_b)

    diff = SnapshotDiff(
        from_source=f"snapshot:{snapshot_a}",
        to_source=f"snapshot:{snapshot_b}",
        created_at=dt.datetime.now().isoformat(),
    )

    all_paths = sorted(set(a.keys()) | set(b.keys()))
    for path in all_paths:
        fa = a.get(path)
        fb = b.get(path)

        if fa and not fb:
            diff.file_diffs.append(FileDiff(
                rel_path=path, change="removed",
                old_sha256=fa["sha256"], old_size=fa["size"],
            ))
            diff.removed += 1
        elif fb and not fa:
            diff.file_diffs.append(FileDiff(
                rel_path=path, change="added",
                new_sha256=fb["sha256"], new_size=fb["size"],
            ))
            diff.added += 1
        elif fa and fb:
            if fa["sha256"] != fb["sha256"]:
                diff.file_diffs.append(FileDiff(
                    rel_path=path, change="modified",
                    old_sha256=fa["sha256"], old_size=fa["size"],
                    new_sha256=fb["sha256"], new_size=fb["size"],
                ))
                diff.modified += 1
            else:
                diff.unchanged += 1

    diff.total = diff.added + diff.removed + diff.modified + diff.unchanged
    return diff


# ---------------------------------------------------------------------------
# CLI 友好输出
# ---------------------------------------------------------------------------

def format_diff_summary(diff: SnapshotDiff, max_items: int = 50) -> str:
    """生成人类可读的差异摘要。"""
    lines = [
        f"=== 快照差异 ===",
        f"  {diff.from_source} → {diff.to_source}",
        f"  总计 {diff.total} 项",
        f"  新增: {diff.added}",
        f"  删除: {diff.removed}",
        f"  修改: {diff.modified}",
        f"  未变: {diff.unchanged}",
    ]

    if diff.file_diffs:
        lines.append("")
        for d in diff.file_diffs[:max_items]:
            mark = {"added": "+", "removed": "-", "modified": "~"}.get(d.change, " ")
            lines.append(f"  [{mark}] ({d.change:8s}) {d.rel_path}")
        if len(diff.file_diffs) > max_items:
            lines.append(f"  ... 还有 {len(diff.file_diffs) - max_items} 项")

    return "\n".join(lines)
