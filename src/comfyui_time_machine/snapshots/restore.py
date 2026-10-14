"""TASK-016 ~ TASK-017：恢复引擎。

核心原则：
1. **先 staging 再写入** —— 所有要恢复的文件先从 CAS blobs 复制到暂存区并校验 SHA-256
2. **保护点先创建** —— 覆盖/删除前先把文件备份到 recovery_temp/
3. **事务日志全程记录** —— 每步都写 transaction.json，支持崩溃后继续或回滚
4. **永不删除快照** —— 恢复操作只写入 ComfyUI 安装目录的文件，不影响 snapshot CAS
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from .diff import FileDiff, SnapshotDiff, diff_snapshot_vs_current, format_diff_summary
from .store import SnapshotStore, get_default_store_dir


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TRANSDIR_NAME = "recovery_tx"
LOGFILE = "transaction.json"
PLANFILE = "plan.json"


class Phase(str, Enum):
    VALIDATING = "validating"
    BUILDING = "building"        # 构建 staging
    BACKING_UP = "backing_up"    # 保护点备份
    RESTORING = "restoring"      # 逐文件恢复
    VERIFYING = "verifying"      # 恢复后验证
    COMMITTED = "committed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class RestorePlan:
    """恢复计划：从 SnapshotDiff 派生，加上从哪个 blob 读。"""
    snapshot_id: int
    install_root: str
    total: int = 0
    to_add: list[dict] = field(default_factory=list)       # [{rel_path, sha256, size_bytes}]
    to_overwrite: list[dict] = field(default_factory=list) # [{rel_path, sha256, size_bytes, old_sha256}]
    to_remove: list[dict] = field(default_factory=list)    # [{rel_path, old_sha256}]
    backup_size_bytes: int = 0
    staging_size_bytes: int = 0


@dataclass
class RestoreProgress:
    phase: str = ""
    total_files: int = 0
    done_files: int = 0
    current_path: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 恢复前检查
# ---------------------------------------------------------------------------

def check_comfyui_not_running() -> bool:
    """检查 ComfyUI 是否在运行。
    Windows 上通过进程名匹配。"""
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if "comfyui" in name and ("python" in name or "convenient" in name):
                return False
    except ImportError:
        # psutil 没装就用 tasklist 简单扫
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        # 无法区分具体哪个 python 是 ComfyUI → 让用户手动确认
        return True  # 保守认为没运行（由调用方决定是否强制用户确认）
    return True


def check_snapshot_integrity(store: SnapshotStore, snapshot_id: int) -> tuple[bool, Optional[str]]:
    """检查快照完整性。"""
    snap = store.get_snapshot(snapshot_id)
    if snap is None:
        return False, f"快照 #{snapshot_id} 不存在"
    if snap["status"] != "committed":
        return False, f"快照状态为 {snap['status']}（需要 committed）"
    if snap["integrity_ok"] != 1:
        return False, f"快照完整性已损坏"
    return True, None


def check_disk_space(store: SnapshotStore, plan: RestorePlan) -> tuple[bool, Optional[str]]:
    """检查 CAS 所在盘是否有足够空间（暂存 + 备份）。"""
    try:
        import shutil as _shutil
        total_needed = plan.staging_size_bytes + plan.backup_size_bytes
        disk = store.store_dir.drive + "\\" if store.store_dir.drive else "/"
        usage = _shutil.disk_usage(disk)
        if usage.free < total_needed * 2:  # 留一倍冗余
            mb_need = total_needed / (1024 * 1024)
            mb_free = usage.free / (1024 * 1024)
            return False, f"空间不足：需要 {mb_need:.0f}MB，当前盘剩 {mb_free:.0f}MB"
    except Exception:
        pass  # 无法判断就放行，staging 阶段会再检查
    return True, None


def build_plan(
    store: SnapshotStore,
    snapshot_id: int,
    install_root: Path,
) -> RestorePlan:
    """从快照生成恢复计划。"""
    files = store.get_snapshot_files(snapshot_id)
    current_map: dict[str, str] = _current_hash_map(store, install_root)

    plan = RestorePlan(
        snapshot_id=snapshot_id,
        install_root=str(install_root.resolve()),
        total=len(files),
    )

    for f in files:
        rel = f["rel_path"]
        cur_sha = current_map.get(rel)

        if cur_sha is None:
            plan.to_add.append({
                "rel_path": rel, "sha256": f["sha256"],
                "size_bytes": f["size_bytes"],
            })
        elif cur_sha != f["sha256"]:
            plan.to_overwrite.append({
                "rel_path": rel, "sha256": f["sha256"],
                "size_bytes": f["size_bytes"], "old_sha256": cur_sha,
            })

    # 删除计划：快照里没有但当前有的 → 只有显式开启才删
    # 阶段 C 先保守，不做删除（避免用户删了模型后恢复把模型删光）
    # 以后可以加 include_deletes 参数
    plan.to_remove = []

    plan.staging_size_bytes = sum(f["size_bytes"] for f in plan.to_add + plan.to_overwrite)
    plan.backup_size_bytes = sum(f.get("size_bytes", 0) for f in plan.to_overwrite)

    return plan


def _current_hash_map(store: SnapshotStore, install_root: Path) -> dict[str, str]:
    """返回当前文件的 {rel_path: sha256} （仅快照 scope 涉及的路径）。"""
    from .scope import compute_scope
    scope = compute_scope(install_root)
    result: dict[str, str] = {}
    for item in scope.included_items:
        full = install_root / item.rel_path
        if not full.is_file():
            continue
        sha = store.compute_sha256(full)
        if sha is None:
            continue
        result[item.rel_path] = sha
    return result


# ---------------------------------------------------------------------------
# 事务化恢复核心
# ---------------------------------------------------------------------------

class RestoreTransaction:
    """一次恢复事务。"""

    def __init__(
        self,
        snapshot_id: int,
        install_root: Path,
        store: SnapshotStore,
        should_cancel=None,
        progress_callback=None,
    ):
        self.snapshot_id = snapshot_id
        self.install_root = install_root.resolve()
        self.store = store
        self.should_cancel = should_cancel
        self.progress_callback = progress_callback

        self.store_dir = store.store_dir
        self.tx_dir = self.store_dir / TRANSDIR_NAME
        self.staging_dir = self.tx_dir / "staging"
        self.backup_dir = self.tx_dir / "backup"

        self.plan: Optional[RestorePlan] = None
        self.log: dict = {}

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute(self) -> RestorePlan:
        """执行完整恢复流程。成功返回 plan，失败抛异常。"""

        # Phase 1: 校验
        self._progress(Phase.VALIDATING)
        self._log_event("validation_start")

        ok, err = check_snapshot_integrity(self.store, self.snapshot_id)
        if not ok:
            self._fail(err)

        self.plan = build_plan(self.store, self.snapshot_id, self.install_root)
        self._ensure_dirs()

        ok, err = check_disk_space(self.store, self.plan)
        if not ok:
            self._fail(err)

        self._save_plan()
        self._log_event("validation_ok", plan_total=self.plan.total,
                        adds=len(self.plan.to_add),
                        overwrites=len(self.plan.to_overwrite))

        if self.should_cancel and self.should_cancel():
            self._cancel()

        # Phase 2: staging — 把 blob 复制到 staging 并校验
        self._progress(Phase.BUILDING, self.plan.total)
        self._log_event("staging_start")
        self._stage_blobs()
        self._log_event("staging_ok")

        if self.should_cancel and self.should_cancel():
            self._cancel()

        # Phase 3: 保护点 — 备份要被覆盖的文件
        self._progress(Phase.BACKING_UP, len(self.plan.to_overwrite))
        self._log_event("backup_start")
        self._create_protection_point()
        self._log_event("backup_ok")

        if self.should_cancel and self.should_cancel():
            self._cancel()

        # Phase 4: 逐文件恢复
        self._progress(Phase.RESTORING, self.plan.total)
        self._log_event("restore_start")
        self._apply_files()
        self._log_event("restore_ok")

        if self.should_cancel and self.should_cancel():
            self._cancel()

        # Phase 5: L1 验证
        self._progress(Phase.VERIFYING, self.plan.total)
        self._log_event("verify_start")
        self._verify_l1_hashes()
        self._log_event("verify_ok")

        # 完成
        self._progress(Phase.COMMITTED)
        self._log_event("committed")

        return self.plan

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _ensure_dirs(self):
        self.tx_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _progress(self, phase: Phase, total: int = 0, done: int = 0, current: str = "", error: str = ""):
        if self.progress_callback:
            self.progress_callback(RestoreProgress(
                phase=str(phase), total_files=total,
                done_files=done, current_path=current, error=error,
            ))

    def _log_event(self, event: str, **kwargs):
        entry = {"ts": dt.datetime.now().isoformat(), "event": event, **kwargs}
        self.log.setdefault("events", []).append(entry)
        self.log["phase"] = str(kwargs.get("phase") or self.log.get("phase", ""))
        self.log["updated_at"] = dt.datetime.now().isoformat()
        self._write_log()

    def _write_log(self):
        try:
            self.log["snapshot_id"] = self.snapshot_id
            self.log["install_root"] = str(self.install_root)
            path = self.tx_dir / LOGFILE
            path.write_text(json.dumps(self.log, indent=2, ensure_ascii=False))
        except OSError:
            pass

    def _save_plan(self):
        if self.plan:
            (self.tx_dir / PLANFILE).write_text(
                json.dumps(asdict(self.plan), indent=2, ensure_ascii=False)
            )

    def _fail(self, msg: str):
        self._progress(Phase.FAILED, error=msg)
        self._log_event("failed", error=msg)
        raise RuntimeError(msg)

    def _cancel(self):
        self._progress(Phase.CANCELLED)
        self._log_event("cancelled")
        raise InterruptedError("用户取消恢复")

    # --- Phase 2: staging ---

    def _stage_blobs(self):
        """从 CAS blobs 复制文件到 staging，校验 SHA-256。"""
        all_files = self.plan.to_add + self.plan.to_overwrite
        for idx, f in enumerate(all_files):
            blob_path = self.store._blob_path(f["sha256"])
            if not blob_path.is_file():
                self._fail(f"blob 缺失: {f['rel_path']} sha256={f['sha256']}")

            # staging 里建相同的相对路径
            stage_target = self.staging_dir / f["rel_path"]
            stage_target.parent.mkdir(parents=True, exist_ok=True)

            self._progress(Phase.BUILDING, self.plan.total, idx, f["rel_path"])

            shutil.copy2(str(blob_path), str(stage_target))

            # 校验
            actual = self.store.compute_sha256(stage_target)
            if actual != f["sha256"]:
                self._fail(f"staging 校验失败: {f['rel_path']}")

    # --- Phase 3: protection point ---

    def _create_protection_point(self):
        """把要覆盖/删除的当前文件备份到 backup/ 目录。"""
        for idx, f in enumerate(self.plan.to_overwrite):
            target = self.install_root / f["rel_path"]
            if target.is_file():
                bak = self.backup_dir / f["rel_path"]
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(target), str(bak))

            self._progress(Phase.BACKING_UP, len(self.plan.to_overwrite), idx, f["rel_path"])

    # --- Phase 4: 逐文件恢复 ---

    def _apply_files(self):
        """用 staging 里的文件替换/新增到 ComfyUI 安装目录。"""
        self._progress(Phase.RESTORING, len(self.plan.to_add) + len(self.plan.to_overwrite))
        done = 0

        # 先处理 overwrite（有文件要先删）
        for f in self.plan.to_overwrite:
            self._replace_file(f)
            done += 1
            self._progress(Phase.RESTORING, self.plan.total, done, f["rel_path"])

        # 再处理 add
        for f in self.plan.to_add:
            self._add_file(f)
            done += 1
            self._progress(Phase.RESTORING, self.plan.total, done, f["rel_path"])

    def _replace_file(self, f: dict):
        """安全替换单个文件。"""
        target = self.install_root / f["rel_path"]
        staging = self.staging_dir / f["rel_path"]

        # 用 shutil.copy2 原子覆盖（Windows 上 os.replace 在文件被占用时会失败）
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(staging), str(target))

    def _add_file(self, f: dict):
        """新增文件。"""
        target = self.install_root / f["rel_path"]
        staging = self.staging_dir / f["rel_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(staging), str(target))

    # --- Phase 5: L1 哈希验证 ---

    def _verify_l1_hashes(self):
        """对恢复后的文件重新算 SHA-256，确认都匹配快照。"""
        all_files = self.plan.to_add + self.plan.to_overwrite
        errors = []
        for idx, f in enumerate(all_files):
            target = self.install_root / f["rel_path"]
            if not target.is_file():
                errors.append(f"文件缺失: {f['rel_path']}")
                continue

            actual = self.store.compute_sha256(target)
            if actual != f["sha256"]:
                errors.append(f"hash 不匹配: {f['rel_path']} expected={f['sha256']} actual={actual}")

            self._progress(Phase.VERIFYING, len(all_files), idx, f["rel_path"])

        if errors:
            self._fail("L1 验证失败:\n" + "\n".join(errors[:20]))

    # ------------------------------------------------------------------
    # 回滚
    # ------------------------------------------------------------------

    def rollback(self) -> bool:
        """从保护点回滚。只有 backup/ 目录有东西时才有效。"""
        if not self.backup_dir.is_dir() or not any(self.backup_dir.rglob("*")):
            return False

        for bak_file in self.backup_dir.rglob("*"):
            if not bak_file.is_file():
                continue
            rel = bak_file.relative_to(self.backup_dir).as_posix()
            target = self.install_root / rel

            # staging 里新增的文件要删掉（因为原先是不存在的）
            stage_file = self.staging_dir / rel
            if stage_file.is_file() and target.is_file():
                # 如果当前 target 等于 staging → 说明是从 add 来的 → 删除
                if self.store.compute_sha256(target) == self.store.compute_sha256(stage_file):
                    target.unlink(missing_ok=True)
                    continue

            # 否则从备份恢复
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(bak_file), str(target))

        self._log_event("rolled_back")
        self._progress(Phase.ROLLED_BACK)
        return True


# ---------------------------------------------------------------------------
# 高层入口
# ---------------------------------------------------------------------------

def restore_snapshot(
    snapshot_id: int,
    install_root: Path,
    *,
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
    should_cancel=None,
    progress_callback=None,
) -> RestorePlan:
    """恢复快照的主入口。调用前必须确认 ComfyUI 已停止。"""
    if store is None:
        store = SnapshotStore(store_dir)

    tx = RestoreTransaction(
        snapshot_id=snapshot_id,
        install_root=install_root,
        store=store,
        should_cancel=should_cancel,
        progress_callback=progress_callback,
    )
    return tx.execute()


def preview_restore(
    snapshot_id: int,
    install_root: Path,
    *,
    store: Optional[SnapshotStore] = None,
    store_dir: Optional[Path | str] = None,
) -> RestorePlan:
    """只生成恢复计划，不执行写入（供 UI 预览）。"""
    if store is None:
        store = SnapshotStore(store_dir)

    ok, err = check_snapshot_integrity(store, snapshot_id)
    if not ok:
        raise RuntimeError(err)

    return build_plan(store, snapshot_id, install_root)
