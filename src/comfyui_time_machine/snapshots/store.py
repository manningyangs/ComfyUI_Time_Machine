"""TASK-012：SQLite 数据库管理 + 内容寻址对象存储（CAS）。

存储位置：默认 Time Machine 项目根目录下的 data/snapshots/
        绝对不放在 ComfyUI 安装目录内。

CAS 目录结构：
    data/snapshots/
    ├── db.sqlite3
    ├── blobs/
    │   ├── e3/b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    │   └── ...
    └── temp/
        └── {sha256}.tmp   临时写入，校验通过后 os.rename 到 blobs/
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Optional


def get_default_store_dir() -> Path:
    """获取默认快照存储目录。优先读 config，回退到项目根 data/snapshots。"""
    try:
        from .. import config as _cfg
        cfg = _cfg.load()
        if cfg.get("store_dir"):
            p = Path(cfg["store_dir"])
            # 如果配置的目录不存在但父级也不像是 exe 同级，回退到硬编码安全默认
            return p
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "snapshots"


class SnapshotStore:
    """快照存储核心类 —— SQLite + 内容寻址 blob。"""

    def __init__(self, store_dir: Optional[Path | str] = None):
        self.store_dir = Path(store_dir) if store_dir else get_default_store_dir()
        self.db_path = self.store_dir / "db.sqlite3"
        self.blobs_dir = self.store_dir / "blobs"
        self.temp_dir = self.store_dir / "temp"

        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # 锁：blob 写入按 SHA256 分片锁（同 SHA 竞争，不同 SHA 并行）
        self._blob_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            isolation_level=None,
            check_same_thread=False,  # 允许跨线程（WAL 模式 + Python 层锁已够安全）
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SnapshotStore 未打开")
        return self._conn

    def _init_schema(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            note            TEXT,
            type            TEXT NOT NULL,
            status          TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            completed_at    TEXT,
            install_root    TEXT NOT NULL,
            scope_json      TEXT NOT NULL,
            total_size      INTEGER,
            object_count    INTEGER,
            integrity_ok    INTEGER,
            integrity_error TEXT
        );

        CREATE TABLE IF NOT EXISTS snapshot_files (
            snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            rel_path     TEXT NOT NULL,
            sha256       TEXT NOT NULL,
            size_bytes   INTEGER NOT NULL,
            modified_at  TEXT,
            file_mode    TEXT NOT NULL DEFAULT 'blob',
            PRIMARY KEY (snapshot_id, rel_path)
        );

        CREATE TABLE IF NOT EXISTS blob_index (
            sha256       TEXT PRIMARY KEY,
            size_bytes   INTEGER NOT NULL,
            ref_count    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT NOT NULL,
            deleted_at   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_files_snapshot ON snapshot_files(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_files_sha256    ON snapshot_files(sha256);
        CREATE INDEX IF NOT EXISTS idx_snapshot_status ON snapshots(status);
        """
        self.conn.executescript(sql)

    # ------------------------------------------------------------------
    # Blob 路径
    # ------------------------------------------------------------------

    def _blob_path(self, sha256: str) -> Path:
        return self.blobs_dir / sha256[:2] / sha256

    def _temp_path(self, sha256: str) -> Path:
        return self.temp_dir / f"{sha256}.tmp"

    def blob_exists(self, sha256: str) -> bool:
        return self._blob_path(sha256).is_file()

    # ------------------------------------------------------------------
    # SHA-256
    # ------------------------------------------------------------------

    @staticmethod
    def compute_sha256(path: Path, max_bytes: int = 1024 * 1024 * 500) -> Optional[str]:
        try:
            h = hashlib.sha256()
            total = 0
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Blob 原子写入 — 只负责落盘 + blob_index 登记（ref_count=1 为初始值）
    # ref_count 增删由 create_snapshot / delete_snapshot 统一管理
    # ------------------------------------------------------------------

    def store_blob_atomic(self, src_path: Path) -> Optional[str]:
        """写入 blob 文件并登记 blob_index。已存在的 blob 只返回 sha256。

        blob_index.ref_count 初始设 0（表示"有 blob 文件存在但尚未被任何快照引用"）。
        create_snapshot 会对每个唯一 SHA 做 ref_count +1 建立真正的引用计数。

        多线程安全：全局锁保护 blob_exists + os.replace 的原子组合。
        """
        try:
            sha256 = self.compute_sha256(src_path)
            if sha256 is None:
                return None

            blob_file = self._blob_path(sha256)

            # 按 SHA256 获取分片锁
            with self._locks_guard:
                lock = self._blob_locks.setdefault(sha256, threading.Lock())
            with lock:
                if blob_file.is_file():
                    if not self._blob_index_exists(sha256):
                        self.conn.execute(
                            "INSERT OR IGNORE INTO blob_index (sha256, size_bytes, ref_count, created_at) VALUES (?, ?, 0, ?)",
                            (sha256, blob_file.stat().st_size, dt.datetime.now().isoformat()),
                        )
                    return sha256

                tmp = self._temp_path(sha256)
                blob_file.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(str(src_path), str(tmp))

                verify = self.compute_sha256(tmp)
                if verify != sha256:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                    return None

                os.replace(str(tmp), str(blob_file))

                size = blob_file.stat().st_size
            now = dt.datetime.now().isoformat()
            self.conn.execute(
                "INSERT OR IGNORE INTO blob_index (sha256, size_bytes, ref_count, created_at) VALUES (?, ?, 0, ?)",
                (sha256, size, now),
            )

            return sha256

        except Exception:
            try:
                tmp = self._temp_path(sha256)
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return None

    def _blob_index_exists(self, sha256: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM blob_index WHERE sha256=? AND deleted_at IS NULL",
            (sha256,),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # 快照创建
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        name: str,
        install_root: Path,
        files: list[dict],
        scope_json: str,
        note: str = "",
        snapshot_type: str = "full",
    ) -> int:
        if not files:
            raise ValueError("空快照没有意义")

        now = dt.datetime.now().isoformat()
        total_size = sum(f.get("size_bytes", 0) for f in files)

        cur = self.conn.execute(
            """INSERT INTO snapshots (name, note, type, status, created_at, install_root, scope_json, total_size, object_count)
               VALUES (?, ?, ?, 'verifying', ?, ?, ?, ?, ?)""",
            (name, note, snapshot_type, now, str(install_root), scope_json, total_size, len(files)),
        )
        snapshot_id = cur.lastrowid

        # 写入文件条目 + 对每个唯一 SHA 的 blob_index ref_count +1
        # 用显式 transaction + executemany 批量写入，减少 WAL 刷盘次数
        self.conn.execute("BEGIN")
        try:
            file_rows = [
                (
                    snapshot_id,
                    f["rel_path"],
                    f["sha256"],
                    f.get("size_bytes", 0),
                    f.get("modified_at"),
                    f.get("file_mode", "blob"),
                )
                for f in files
            ]
            self.conn.executemany(
                """INSERT INTO snapshot_files (snapshot_id, rel_path, sha256, size_bytes, modified_at, file_mode)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                file_rows,
            )

            # ref_count +1：每个唯一 SHA 对应这个快照
            unique_shas = list({f["sha256"] for f in files})
            self.conn.executemany(
                "UPDATE blob_index SET ref_count = ref_count + 1 WHERE sha256 = ? AND deleted_at IS NULL",
                [(sha,) for sha in unique_shas],
            )

            # 补登缺失的 blob_index（罕见）
            missing = []
            for sha in unique_shas:
                cur = self.conn.execute("SELECT ref_count FROM blob_index WHERE sha256 = ?", (sha,))
                if cur.fetchone() is None:
                    blob_file = self._blob_path(sha)
                    if blob_file.is_file():
                        missing.append((sha, blob_file.stat().st_size, dt.datetime.now().isoformat()))
            if missing:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO blob_index (sha256, size_bytes, ref_count, created_at) VALUES (?, ?, 1, ?)",
                    missing,
                )

            self.conn.commit()
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        # 完整性校验（轻量版：创建时只查 blob 存在性，SHA256 在 store_blob_atomic 时已原子校验）
        integrity_ok, error_msg = self._verify_snapshot_files(
            snapshot_id, check_sha=False  # 创建时跳过 SHA 重算，加快速度
        )

        completed = dt.datetime.now().isoformat()
        if integrity_ok:
            self.conn.execute(
                "UPDATE snapshots SET status='committed', completed_at=?, integrity_ok=1 WHERE id=?",
                (completed, snapshot_id),
            )
        else:
            self.conn.execute(
                "UPDATE snapshots SET status='broken', completed_at=?, integrity_ok=0, integrity_error=? WHERE id=?",
                (completed, error_msg, snapshot_id),
            )
            raise RuntimeError(f"快照完整性校验失败: {error_msg}")

        return snapshot_id

    def _verify_snapshot_files(self, snapshot_id: int, check_sha: bool = True) -> tuple[bool, Optional[str]]:
        """校验快照完整性。

        Args:
            snapshot_id: 快照 ID。
            check_sha: True = 重算每个 blob 的 SHA256 对比（深校验，慢）；
                       False = 只查 blob 文件是否存在（创建快照时用，快）。
        """
        rows = self.conn.execute(
            "SELECT rel_path, sha256 FROM snapshot_files WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()

        for rel_path, sha256 in rows:
            blob_file = self._blob_path(sha256)
            if not blob_file.is_file():
                return False, f"blob 缺失: rel={rel_path} sha256={sha256}"

            if check_sha:
                actual = self.compute_sha256(blob_file)
                if actual != sha256:
                    return False, f"blob hash 不匹配: rel={rel_path} expected={sha256} actual={actual}"

        return True, None

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_snapshots(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, name, note, type, status, created_at, completed_at,
                      install_root, total_size, object_count, integrity_ok, integrity_error
               FROM snapshots ORDER BY id DESC"""
        ).fetchall()
        cols = ["id", "name", "note", "type", "status", "created_at", "completed_at",
                "install_root", "total_size", "object_count", "integrity_ok", "integrity_error"]
        return [dict(zip(cols, row)) for row in rows]

    def get_snapshot(self, snapshot_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return None
        cols = ["id", "name", "note", "type", "status", "created_at", "completed_at",
                "install_root", "scope_json", "total_size", "object_count",
                "integrity_ok", "integrity_error"]
        return dict(zip(cols, row))

    def get_snapshot_files(self, snapshot_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT rel_path, sha256, size_bytes, modified_at, file_mode
               FROM snapshot_files WHERE snapshot_id=? ORDER BY rel_path""",
            (snapshot_id,),
        ).fetchall()
        cols = ["rel_path", "sha256", "size_bytes", "modified_at", "file_mode"]
        return [dict(zip(cols, row)) for row in rows]

    # ------------------------------------------------------------------
    # 删除 + 垃圾回收
    # ------------------------------------------------------------------

    def delete_snapshot(
        self, snapshot_id: int, dry_run: bool = False, progress_callback=None
    ) -> dict:
        snap = self.get_snapshot(snapshot_id)
        if snap is None:
            raise ValueError(f"快照 {snapshot_id} 不存在")

        files = self.get_snapshot_files(snapshot_id)
        unique_shas = sorted(set(f["sha256"] for f in files))

        progress_callback and progress_callback(
            "analyzing", 0, len(unique_shas), f"分析 {len(unique_shas)} 个 blob 的引用情况"
        )

        estimated_blobs_to_delete = []
        for sha in unique_shas:
            row = self.conn.execute(
                "SELECT ref_count, size_bytes FROM blob_index WHERE sha256=? AND deleted_at IS NULL",
                (sha,),
            ).fetchone()
            if row and row[0] == 1:
                estimated_blobs_to_delete.append((sha, row[1]))

        estimated_bytes = sum(sz for _, sz in estimated_blobs_to_delete)

        summary = {
            "snapshot_id": snapshot_id,
            "snapshot_name": snap["name"],
            "total_files": len(files),
            "unique_blobs": len(unique_shas),
            "blobs_to_delete": len(estimated_blobs_to_delete),
            "estimated_bytes_to_free": estimated_bytes,
            "dry_run": dry_run,
        }

        if dry_run:
            return summary

        now = dt.datetime.now().isoformat()

        # 1. 删除快照引用（executemany 加速）
        progress_callback and progress_callback(
            "sql_refs", 0, len(files), "从 SQLite 删除快照引用"
        )
        self.conn.execute("BEGIN")
        try:
            self.conn.execute("DELETE FROM snapshot_files WHERE snapshot_id=?", (snapshot_id,))
            self.conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))

            # 2. ref_count 递减（executemany）
            self.conn.executemany(
                "UPDATE blob_index SET ref_count = ref_count - 1 WHERE sha256=? AND deleted_at IS NULL",
                [(sha,) for sha in unique_shas],
            )
            self.conn.commit()
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        progress_callback and progress_callback(
            "sql_refs", len(files), len(files), "SQL 删除完成"
        )

        # 3. 清理 ref_count <= 0 的 blob
        orphan = self.conn.execute(
            "SELECT sha256 FROM blob_index WHERE ref_count <= 0 AND deleted_at IS NULL"
        ).fetchall()
        progress_callback and progress_callback(
            "gc_blobs", 0, len(orphan), f"GC {len(orphan)} 个孤儿 blob"
        )

        for idx, (sha,) in enumerate(orphan):
            self.conn.execute(
                "UPDATE blob_index SET deleted_at=? WHERE sha256=?", (now, sha)
            )
            blob_file = self._blob_path(sha)
            try:
                if blob_file.is_file():
                    blob_file.unlink()
            except OSError:
                pass
            progress_callback and progress_callback(
                "gc_blobs", idx + 1, len(orphan), f"删除 blob {idx + 1}/{len(orphan)}"
            )

        progress_callback and progress_callback("done", 1, 1, "删除完成")
        return summary
