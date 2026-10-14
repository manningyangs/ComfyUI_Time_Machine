"""扫描 Worker —— 分阶段扫描，每阶段发真实进度。

不调 cli._build_report 黑盒，而是手动调用：
  identify_installation → scan_git → scan_custom_nodes → scan_python_env → scan_configs
这样每个阶段都能发独立的进度和日志，UI 有真实阶段感。
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseWorker


class ScanWorker(BaseWorker):
    """运行完整只读扫描，产出 JSON report dict。"""

    # 阶段定义：(进度范围%, 阶段名, 工作函数描述)
    PHASES = [
        (0, 10, "识别安装类型..."),
        (10, 25, "扫描 Git 状态..."),
        (25, 50, "扫描自定义节点..."),
        (50, 80, "扫描 Python 环境..."),   # pip list 最慢
        (80, 90, "扫描配置文件..."),
        (90, 100, "组装报告..."),
    ]

    def __init__(self, install_root: Path):
        super().__init__()
        self.install_root = install_root

    def _emit_phase(self, idx: int, msg: str = ""):
        """发某个阶段的起始进度。"""
        start_pct, end_pct, name = self.PHASES[idx]
        self.progress.emit(start_pct, name + " " + msg)

    def _emit_phase_done(self, idx: int, msg: str = ""):
        """发某个阶段完成的进度。"""
        _, end_pct, name = self.PHASES[idx]
        self.progress.emit(end_pct, (name if name else "") + " ✓ " + msg)

    def run(self):
        try:
            self.log.emit(f"开始扫描: {self.install_root}")

            # ------------------------------------------------------
            # Phase 1: 识别安装类型
            # ------------------------------------------------------
            self._emit_phase(0)
            from ...paths import identify_installation
            from ...models import DetectionStatus

            installation = identify_installation(self.install_root)

            if installation.status != DetectionStatus.DETECTED:
                self.failed.emit(
                    f"安装识别失败: status={installation.status.value} "
                    f"error={installation.error or ''}"
                )
                return

            self.log.emit(
                f"  ✓ 识别成功: type={installation.type.value}  "
                f"root={installation.root_path}"
            )
            self._emit_phase_done(0)

            # ------------------------------------------------------
            # Phase 2: Git 扫描
            # ------------------------------------------------------
            self._emit_phase(1)
            from ...scanners.core import scan_git_for_directory

            git_root = Path(installation.comfyui_path) if installation.comfyui_path else Path(self.install_root)
            git = scan_git_for_directory(git_root)

            if git.is_git_repo:
                self.log.emit(
                    f"  ✓ Git: commit={git.commit[:7] if git.commit else '?'}  "
                    f"branch={git.branch}  "
                    f"dirty={git.has_local_changes}"
                )
            else:
                self.log.emit(f"  Git: 不是 git 仓库")
            self._emit_phase_done(1)

            # ------------------------------------------------------
            # Phase 3: 自定义节点扫描（45 个节点，每个都会查 git）
            # ------------------------------------------------------
            self._emit_phase(2)
            from ...scanners.custom_nodes import scan_custom_nodes

            cn_dir = None
            if installation.custom_nodes_dir and installation.custom_nodes_dir.exists:
                cn_dir = Path(installation.custom_nodes_dir.path)
            elif installation.comfyui_path:
                cn_dir = Path(installation.comfyui_path) / "custom_nodes"

            nodes = scan_custom_nodes(cn_dir) if cn_dir else []

            git_nodes = sum(1 for n in nodes if n.git and n.git.is_git_repo)
            self.log.emit(f"  ✓ 自定义节点: {len(nodes)} 个 (Git={git_nodes}, 非Git={len(nodes) - git_nodes})")
            self._emit_phase_done(2)

            # ------------------------------------------------------
            # Phase 4: Python 环境扫描（pip list 最慢）
            # ------------------------------------------------------
            self._emit_phase(3)
            from ...scanners.python_env import scan_python_environment

            embed_dir = (
                Path(installation.python_embeded.path)
                if installation.python_embeded and installation.python_embeded.exists
                else None
            )

            py_env = scan_python_environment(embed_dir)
            self.log.emit(
                f"  ✓ Python {py_env.python_version}  "
                f"pip 包: {len(py_env.packages)} 个"
            )
            self._emit_phase_done(3)

            # ------------------------------------------------------
            # Phase 5: 配置文件扫描
            # ------------------------------------------------------
            self._emit_phase(4)
            from ...scanners.configs import scan_config_files

            configs = scan_config_files(Path(self.install_root))
            self.log.emit(f"  ✓ 配置文件: {len(configs)} 个")
            self._emit_phase_done(4)

            # ------------------------------------------------------
            # Phase 6: 组装报告
            # ------------------------------------------------------
            self._emit_phase(5)

            from ...cli import _build_report
            report = _build_report(str(self.install_root), installation, verbose=False)

            self._emit_phase_done(5)

            self.progress.emit(100, "完成")
            self.log.emit(f"\n✅ 扫描完成！")
            self.finished_ok.emit(report.to_dict())

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.failed.emit(f"扫描失败: {e}\n{tb}")
