"""TASK-011：快照范围配置。

明确哪些文件会被快照引擎纳入，哪些排除。
规则硬编码，不读取外部配置（用户以后可能需要手动调整）。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# 这些目录/文件/扩展名**总是排除**（大目录、缓存、运行时产物）
ALWAYS_EXCLUDED_DIR_NAMES = {
    # 模型 / 输出 / 输入
    "checkpoints", "clip", "clip_vision", "configs", "controlnet",
    "diffusers", "embeddings", "gligen", "hypernetworks", "loras",
    "safetensors", "sd-models", "style_models", "unet", "vae", "vae_approx",
    "output", "input", "temp", "tmp", "cache", "__pycache__",
    # 运行时 / 缓存
    ".cache", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "logs", "log", "errors",
    # 版本控制内部
    ".git", ".hg", ".svn",
    # Python 虚拟环境（不是嵌入式 Python）
    "venv", ".venv", "env",
    # 临时文件
    "thumbs.db", "desktop.ini", ".ds_store",
}

# 这些扩展名**总是排除**
ALWAYS_EXCLUDED_SUFFIXES = {
    ".safetensors", ".ckpt", ".bin", ".pt", ".pth", ".onnx",
    ".gif", ".mp4", ".mov", ".avi", ".webm", ".wav", ".flac",
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff",
    ".zip", ".7z", ".rar", ".tar", ".gz",
    ".pyc", ".pyo",
    ".log",
}

# 在嵌入式 Python 目录内部，这些子目录/文件排除（体积大且可重新 pip install）
PYTHON_EMBEDED_EXCLUDED_DIRS = {
    "Lib/site-packages",  # 体积大，记录包清单即可
    "Lib/distutils",
    "Lib/lib2to3",
    "Lib/test",
}


@dataclass
class ScopeItem:
    """范围中的一个条目。"""
    rel_path: str                    # 相对 install_root 的路径
    reason: str = ""                 # 纳入/排除原因
    included: bool = True            # True=纳入快照
    excluded_by: str = ""            # 匹配到的排除规则名称（如果 excluded=True）


@dataclass
class SnapshotScope:
    """快照范围配置。"""

    # 核心目录总是纳入（排除大文件后）
    include_core_code: bool = True
    include_custom_nodes: bool = True
    include_python_embedded: bool = True    # 纳入 python.exe + DLL + 核心库，排除 site-packages
    include_configs: bool = True

    # 外部节点目录默认排除
    include_external_custom_nodes: bool = False

    # 明细
    included_items: list[ScopeItem] = field(default_factory=list)
    excluded_items: list[ScopeItem] = field(default_factory=list)

    # 估算
    estimated_total_bytes: Optional[int] = None
    estimation_method: str = "recursive_walk"  # recursive_walk | unknown

    def describe(self) -> str:
        """生成人类可读的范围说明。"""
        lines = ["快照范围："]
        for it in self.included_items[:20]:
            lines.append(f"  ✓ 纳入: {it.rel_path}  ({it.reason})")
        if len(self.included_items) > 20:
            lines.append(f"  ... 还有 {len(self.included_items) - 20} 个纳入项")

        if self.excluded_items:
            lines.append(f"  共 {len(self.excluded_items)} 项排除")
            for it in self.excluded_items[:10]:
                lines.append(f"  ✗ 排除: {it.rel_path}  (规则: {it.excluded_by})")

        if self.estimated_total_bytes is not None:
            mb = self.estimated_total_bytes / (1024 * 1024)
            lines.append(f"\n  预计数据量: {mb:.1f} MB")
        else:
            lines.append(f"\n  预计数据量: 不确定")

        return "\n".join(lines)


def _is_excluded_by_name(name: str) -> Optional[str]:
    """按文件名判断排除规则。"""
    if name.lower() in ALWAYS_EXCLUDED_DIR_NAMES:
        return "always_excluded_dir"
    low = name.lower()
    for suf in ALWAYS_EXCLUDED_SUFFIXES:
        if low.endswith(suf):
            return "always_excluded_suffix"
    return None


def compute_scope(install_root: Path) -> SnapshotScope:
    """遍历 ComfyUI 安装目录，决定哪些文件纳入快照。

    返回 SnapshotScope（不含任何写入操作）。
    """
    scope = SnapshotScope()
    install_root = install_root.resolve()

    cn_dir = install_root / "custom_nodes"
    py_dir = _find_python_dir(install_root)

    total_bytes = 0

    # 遍历策略：
    # 1. install_root 作为核心 walk_root，覆盖根目录顶级文件 + ComfyUI 源码
    # 2. 自定义排除 custom_nodes / python_embeded（它们会被单独 walk）
    # 3. custom_nodes 和 python_embedded 各自独立 walk
    excluded_dir_names_in_root: set[str] = set()
    if cn_dir.is_dir():
        excluded_dir_names_in_root.add("custom_nodes")
    if py_dir is not None and py_dir.is_dir():
        excluded_dir_names_in_root.add(py_dir.name)  # python / python_embeded

    walk_roots: list[tuple[Path, str, Optional[Path], set[str]]] = [
        (install_root, "core_code", None, excluded_dir_names_in_root),
    ]

    if scope.include_custom_nodes and cn_dir.is_dir():
        walk_roots.append((cn_dir, "custom_nodes", None, set()))

    if scope.include_python_embedded and py_dir is not None and py_dir.is_dir():
        walk_roots.append((py_dir, "python_embedded", py_dir, set()))

    for root, category, py_root, root_excludes in walk_roots:
        _walk_scope(root, category, scope, py_root, install_root, root_excludes)

    # 估算总大小
    try:
        # 快速累加已纳入项的文件大小
        for it in scope.included_items:
            # 我们没有存大小，但 items 里的路径还没存 stat...
            # 简化估算：先不做精确计算，后面在创建快照时才精确统计
            pass
        scope.estimation_method = "recursive_walk"
    except Exception:
        scope.estimation_method = "unknown"

    scope.estimated_total_bytes = None  # 精确估算留给创建时

    return scope


def _find_python_dir(install_root: Path) -> Optional[Path]:
    """找嵌入式 Python 目录。"""
    for name in ("python_embeded", "python_embedded", "python"):
        d = install_root / name
        if d.is_dir():
            return d
    return None


def _walk_scope(
    root: Path,
    category: str,
    scope: SnapshotScope,
    py_root: Optional[Path],
    install_root: Path,
    root_excludes: Optional[set[str]] = None,
) -> None:
    """递归遍历 root，填充 scope 的 included / excluded 列表。

    root_excludes：该 walk_root 内要跳过的顶级子目录名（防止被其他 walk_root 重复处理）。
    """
    root_excludes = root_excludes or set()

    for dirpath, dirnames, filenames in _safe_walk(root):
        # 在 dirnames 上就地修改，剪枝 walk（避免进入被排除的大目录）
        kept_dirs = []
        for d in list(dirnames):
            # root_excludes 优先：跳过自定义的排除目录名
            if Path(dirpath).resolve() == root.resolve() and d in root_excludes:
                scope.excluded_items.append(ScopeItem(
                    rel_path=(Path(dirpath) / d).relative_to(install_root).as_posix(),
                    reason="其他 walk_root 单独处理",
                    included=False, excluded_by="walk_root_split",
                ))
                continue

            full = Path(dirpath) / d
            rel = full.relative_to(install_root).as_posix()
            excluded_by = _is_excluded_by_name(d)

            # 嵌入式 Python 内的额外排除
            if py_root is not None:
                py_rel = full.relative_to(py_root).as_posix()
                if py_rel in PYTHON_EMBEDED_EXCLUDED_DIRS:
                    scope.excluded_items.append(ScopeItem(
                        rel_path=rel, reason="嵌入式 Python site-packages 等",
                        included=False, excluded_by="python_embedded_site_packages",
                    ))
                    continue

            if excluded_by is not None:
                scope.excluded_items.append(ScopeItem(
                    rel_path=rel, reason="排除规则",
                    included=False, excluded_by=excluded_by,
                ))
            else:
                kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in filenames:
            full = Path(dirpath) / fname
            rel = full.relative_to(install_root).as_posix()

            # 排除规则
            excl = _is_excluded_by_name(fname)

            # .git/ 内部：只保留 HEAD / config / refs / packed-refs 等元数据
            # 排除 objects/（我们不存 Git 对象）和 index（临时的 stat cache）
            if "/.git/" in rel or rel.startswith(".git/"):
                if "/objects/" in rel or rel.endswith("/objects"):
                    excl = "git_objects"
                elif fname == "index":
                    excl = "git_index_stat_cache"
                # 其他 .git 文件保留（HEAD/config/refs 等）

            if excl is not None:
                scope.excluded_items.append(ScopeItem(
                    rel_path=rel, reason="排除规则",
                    included=False, excluded_by=excl,
                ))
            else:
                scope.included_items.append(ScopeItem(
                    rel_path=rel, reason=category,
                ))


def _safe_walk(root: Path):
    """pathlib 风格的安全 walk（不跟随 symlink，跳过无权限目录）。"""
    try:
        import os
        for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
            yield dirpath, dirnames, filenames
    except PermissionError:
        return
