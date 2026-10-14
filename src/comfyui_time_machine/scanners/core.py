"""scanners/core.py —— 共享子进程安全 helper + Git 扫描器。

子进程安全原则：
1. 永远 shell=False，用参数数组
2. 每个调用都设置超时
3. 所有异常都被捕获并返回结构化结果
4. 不执行 .bat / 项目代码 / 用户脚本
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import DetectionStatus, GitInfo


# 默认超时（秒）—— Git 和 pip 都不应该超过这个时间
DEFAULT_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 安全子进程 helper
# ---------------------------------------------------------------------------

@dataclass
class SafeRunResult:
    """一次受控子进程执行的结果。"""
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


def safe_run(
    cmd: list[str],
    *,
    cwd: Optional[str | Path] = None,
    timeout: int = DEFAULT_TIMEOUT,
    encoding: str = "utf-8",
    capture_stderr: bool = True,
) -> SafeRunResult:
    """安全执行一个外部命令，永远不使用 shell=True。

    参数：
        cmd: 命令和参数列表（必须是 list[str]）
        cwd: 工作目录（可选）
        timeout: 超时秒数，默认 15
        encoding: 输出编码，utf-8 不可用时回退 cp936（Windows）
        capture_stderr: 是否捕获 stderr

    返回：SafeRunResult，永远不会抛异常。
    """
    if not cmd:
        return SafeRunResult(-1, "", "", error="空命令")

    # 防御：cmd 必须是 list，不能让字符串混进去
    if isinstance(cmd, str):
        return SafeRunResult(-1, "", "", error="cmd 必须是 list[str]，不能是 str")

    stdout_pipe = subprocess.PIPE
    stderr_pipe = subprocess.PIPE if capture_stderr else subprocess.DEVNULL

    # Windows 下隐藏子进程命令行窗口（PyInstaller GUI app 里 subprocess 会闪 cmd）
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        creationflags = CREATE_NO_WINDOW
        STARTF_USESHOWWINDOW = 0x00000001
        startupinfo = subprocess.STARTUPINFO(dwFlags=STARTF_USESHOWWINDOW, wShowWindow=0)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            shell=False,           # 硬规则 2：永远不用 shell=True
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",      # 无法解码的字符替换，不让整个调用崩
            timeout=timeout,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        elapsed = time.monotonic() - start
        return SafeRunResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return SafeRunResult(
            returncode=-1,
            stdout="",
            stderr="",
            timed_out=True,
            error=f"超时（{timeout}s）",
        )
    except FileNotFoundError:
        return SafeRunResult(-1, "", "", error=f"命令不存在：{cmd[0]}")
    except PermissionError as e:
        return SafeRunResult(-1, "", "", error=f"权限不足：{e}")
    except OSError as e:
        return SafeRunResult(-1, "", "", error=f"系统错误：{e}")
    except Exception as e:
        return SafeRunResult(-1, "", "", error=f"未知错误：{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Git 扫描
# ---------------------------------------------------------------------------

def _is_git_available() -> bool:
    """快速检查 git 是否在 PATH 中可用。"""
    r = safe_run(["git", "--version"], timeout=3)
    return r.ok


def scan_git_for_directory(dir_path: Path) -> GitInfo:
    """采集指定目录的 Git 状态（只读）。

    返回 GitInfo 结构体，涵盖各种异常情况：
    - 目录不存在 / 不是目录 → NOT_CHECKED + error
    - .git 是 file（worktree）→ is_worktree=True 也继续
    - .git 完全不存在 → not_git_managed
    - git 命令不可用 → error
    - 命令超时 → error
    - 正常采集 → commit / branch / has_local_changes
    """
    info = GitInfo(status=DetectionStatus.NOT_CHECKED)

    d = Path(dir_path)
    if not d.exists() or not d.is_dir():
        info.status = DetectionStatus.NOT_PRESENT
        info.error = f"目录不存在或不是目录：{d}"
        return info

    # 1. 检查 .git 存在性（目录或文件都算）
    git_path = d / ".git"
    if not git_path.exists():
        info.is_git_repo = False
        info.status = DetectionStatus.NOT_PRESENT
        return info

    # .git 是文件（worktree）
    if git_path.is_file():
        info.is_worktree = True

    # 2. git 命令是否可用
    if not _is_git_available():
        info.is_git_repo = True  # 有 .git 就算是仓库
        info.status = DetectionStatus.ERROR
        info.error = "git 命令不可用，无法采集提交信息"
        return info

    info.is_git_repo = True

    # 3. 采集 HEAD 提交号
    r_commit = safe_run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        timeout=5,
    )
    if r_commit.timed_out:
        info.status = DetectionStatus.ERROR
        info.error = f"git rev-parse 超时"
        return info
    if r_commit.returncode != 0:
        # 不是 git 仓库（可能 .git 残留）
        info.is_git_repo = False
        info.status = DetectionStatus.NOT_PRESENT
        info.error = f"rev-parse 失败（可能不是有效仓库）：{r_commit.stderr.strip()[:200]}"
        return info
    info.commit = r_commit.stdout.strip()

    # 4. 采集当前分支
    r_branch = safe_run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=d,
        timeout=5,
    )
    if r_branch.ok:
        br = r_branch.stdout.strip()
        info.branch = br if br != "HEAD" else None  # detached HEAD

    # 5. 采集工作区脏状态（只看 porcelain，不拿差异正文）
    r_status = safe_run(
        ["git", "status", "--porcelain"],
        cwd=d,
        timeout=5,
    )
    if r_status.ok:
        # 有任何输出 = 有未提交修改
        info.has_local_changes = bool(r_status.stdout.strip())

    info.status = DetectionStatus.DETECTED
    return info
