"""ComfyUI Time Machine CLI —— 当前版本仅支持 scan 子命令。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .models import (
    ComfyUIInstallation,
    DetectionStatus,
    InstallationType,
    ScanReport,
    ScanWarning,
)
from .paths import identify_installation, expected_custom_nodes_dir
from .scanners.core import scan_git_for_directory
from .scanners.custom_nodes import scan_custom_nodes
from .scanners.python_env import scan_python_environment
from .scanners.configs import scan_config_files


PROGRAM_NAME = "comfyui-time-machine"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="ComfyUI Time Machine — Windows ComfyUI Portable 只读环境扫描器（v0.1）",
        epilog="当前仅实现扫描功能。快照与恢复功能将在后续版本加入。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {__version__}",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出更详细的扫描过程信息",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")
    subparsers.required = True

    # scan 子命令
    scan_parser = subparsers.add_parser(
        "scan",
        help="扫描指定的 ComfyUI 安装并生成 JSON 报告",
    )
    scan_parser.add_argument(
        "--root", "-r",
        required=True,
        help="ComfyUI Portable 根目录路径（例如 D:\\AI\\ComfyUI_windows_portable）",
    )
    scan_parser.add_argument(
        "--out", "-o",
        default=None,
        help="报告输出路径（JSON）。默认写入当前工作目录的 scan_report.json",
    )
    scan_parser.add_argument(
        "--force",
        action="store_true",
        help="即使检测路径不是支持的安装类型也继续（仅用于调试）",
    )

    return parser


# ---------------------------------------------------------------------------
# scan 实现
# ---------------------------------------------------------------------------

def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(f"[verbose] {msg}")


def _run_all_scans(
    installation: ComfyUIInstallation,
    verbose: bool,
) -> ScanReport:
    """对已识别的安装执行全部扫描器。任何子扫描失败都不会中断其他。"""
    report = ScanReport(
        schema_version="0.1",
        app_version=__version__,
        scan_started_at=dt.datetime.now(),
        os_info=f"{os.name} {sys.platform}",
        platform_info=sys.platform,
        installation=installation,
        scope={
            "scan_phase": "initial_readonly",
            "excludes": [
                "models/**", "output/**", "input/**", "cache/**", "temp/**",
            ],
        },
    )

    # --- TASK-004: 核心 Git 扫描 ---
    _log(verbose, "TASK-004 采集 ComfyUI Git 状态")
    if installation.comfyui_path is not None:
        try:
            git = scan_git_for_directory(installation.comfyui_path)
            installation.git = git
            if git.status == DetectionStatus.ERROR:
                report.warnings.append(ScanWarning(
                    level="warning", category="git",
                    message=f"ComfyUI Git 扫描出错",
                    detail=git.error,
                ))
        except Exception as e:
            report.warnings.append(ScanWarning(
                level="error", category="git",
                message="ComfyUI Git 扫描异常",
                detail=str(e),
            ))

    # --- TASK-005: 自定义节点扫描 ---
    _log(verbose, "TASK-005 扫描 custom_nodes")
    try:
        cn_dir = expected_custom_nodes_dir(installation)
        report.custom_nodes = scan_custom_nodes(cn_dir)
    except Exception as e:
        report.warnings.append(ScanWarning(
            level="error", category="custom_nodes",
            message="自定义节点扫描异常",
            detail=str(e),
        ))

    # --- TASK-006: Python 环境扫描 ---
    _log(verbose, "TASK-006 扫描 Python 环境")
    try:
        embed_dir = installation.python_embeded.path if installation.python_embeded.exists else None
        report.python_env = scan_python_environment(embed_dir)
        if report.python_env.status == DetectionStatus.ERROR:
            report.warnings.append(ScanWarning(
                level="warning", category="python_env",
                message="Python 环境扫描出错",
                detail=report.python_env.error,
            ))
    except Exception as e:
        report.warnings.append(ScanWarning(
            level="error", category="python_env",
            message="Python 环境扫描异常",
            detail=str(e),
        ))

    # --- TASK-007: 配置文件扫描 ---
    _log(verbose, "TASK-007 扫描配置文件")
    try:
        report.config_files = scan_config_files(installation.comfyui_path)
    except Exception as e:
        report.warnings.append(ScanWarning(
            level="error", category="config",
            message="配置文件扫描异常",
            detail=str(e),
        ))

    report.scan_completed_at = dt.datetime.now()
    return report


def _build_report(root_path: str, installation: ComfyUIInstallation, verbose: bool = False) -> ScanReport:
    """把识别结果装成完整 ScanReport。

    当 installation.status != DETECTED 时，只装基础字段，不深入扫描。
    """
    report = ScanReport(
        schema_version="0.1",
        app_version=__version__,
        scan_started_at=dt.datetime.now(),
        os_info=f"{os.name} {sys.platform}",
        platform_info=sys.platform,
        installation=installation,
    )

    # 安装识别失败时加 warning，不进入子扫描
    if installation.status != DetectionStatus.DETECTED:
        report.warnings.append(ScanWarning(
            level="error" if installation.status == DetectionStatus.ERROR else "warning",
            category="installation_detection",
            message=f"安装识别状态：{installation.status.value}",
            detail=installation.error,
        ))
        report.scan_successful = False
        report.top_level_error = installation.error
        report.scan_completed_at = dt.datetime.now()
        return report

    # 识别成功 → 运行全部子扫描
    return _run_all_scans(installation, verbose)


def _write_report(report: ScanReport, out_path: Optional[str]) -> Path:
    """把 JSON 报告写到指定位置。"""
    if out_path:
        target = Path(out_path)
    else:
        target = Path.cwd() / "scan_report.json"

    # 禁止默默写入 ComfyUI 根目录
    # （保守：如果路径解析后落在 ComfyUI 根内，提示用户但不阻止）
    if target.parent == report.installation.root_path:
        print(
            f"[隐私提示] 报告路径落在 ComfyUI 根目录下：{target}，建议改到其他位置。",
            file=sys.stderr,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report.to_json(), encoding="utf-8")
    return target


def _print_human_summary(report: ScanReport) -> None:
    """在控制台打印人类可读的摘要。"""
    inst = report.installation
    print()
    print("=" * 60)
    print(f"  ComfyUI Time Machine — 扫描摘要  v{report.app_version}")
    print("=" * 60)

    print(f"  安装类型    : {inst.type.value}")
    print(f"  识别状态    : {inst.status.value}")
    if inst.root_path:
        print(f"  Portable 根 : {inst.root_path}")
    if inst.comfyui_path:
        print(f"  ComfyUI 目录: {inst.comfyui_path}")
    if inst.python_embeded.exists:
        print(f"  Python 环境 : {inst.python_embeded.path}")
    else:
        print(f"  Python 环境 : 未找到")

    # --- Git ---
    git = inst.git
    if git.status == DetectionStatus.DETECTED:
        git_label = f"是 Git 仓库  commit={git.commit[:8] if git.commit else '?'}  "
        git_label += f"branch={git.branch or '(detached)'}"
        if git.has_local_changes:
            git_label += "  [有未提交修改]"
        print(f"  ComfyUI Git : {git_label}")
    elif git.is_git_repo:
        print(f"  ComfyUI Git : 有 .git 但状态不明（{git.status.value}）")
    else:
        print(f"  ComfyUI Git : 非 Git 仓库")

    # --- Python 环境 ---
    pe = report.python_env
    if pe.status == DetectionStatus.DETECTED:
        ver = pe.python_version or "?"
        pkg_count = len(pe.packages)
        pip_mark = "✓ pip 可用" if pe.pip_available else f"✗ pip 不可用"
        print(f"  嵌入式 Python: {ver}  包数: {pkg_count}  {pip_mark}")
    elif pe.status == DetectionStatus.NOT_PRESENT:
        print(f"  嵌入式 Python: 未找到 python.exe")
    elif pe.error:
        print(f"  嵌入式 Python: 扫描错误 —— {pe.error}")

    # --- 自定义节点 ---
    if report.custom_nodes:
        git_count = sum(1 for n in report.custom_nodes if n.git.is_git_repo)
        plain_count = sum(1 for n in report.custom_nodes if not n.git.is_git_repo and not n.out_of_scope)
        scope_count = sum(1 for n in report.custom_nodes if n.out_of_scope)
        print(f"  自定义节点   : 共 {len(report.custom_nodes)} 个  Git={git_count}  非Git={plain_count}  超出范围={scope_count}")
    else:
        print(f"  自定义节点   : （无 custom_nodes 目录或为空）")

    # --- 配置 ---
    existing_cfgs = [c for c in report.config_files if c.exists]
    if existing_cfgs:
        names = ", ".join(c.path.name for c in existing_cfgs)
        print(f"  配置文件     : {len(existing_cfgs)} 个 —— {names}")

    print()
    if report.warnings:
        print(f"  警告/错误   : {len(report.warnings)} 条")
        for w in report.warnings:
            mark = {"error": "✗", "warning": "!", "info": "·"}.get(w.level, "·")
            print(f"    [{mark}] ({w.category}) {w.message}")
            if w.detail:
                print(f"         {w.detail}")
    else:
        print("  警告/错误   : 无")

    print()
    if report.top_level_error:
        print(f"  结果        : ✗ 扫描未成功完成 —— {report.top_level_error}")
    else:
        print(f"  结果        : ✓ 扫描完成")
    print("=" * 60)
    print()


def cmd_scan(args: argparse.Namespace) -> int:
    """scan 子命令的主流程。返回退出码。"""
    root = args.root
    verbose = args.verbose

    if verbose:
        print(f"[verbose] 正在识别路径：{root}")

    installation = identify_installation(root)

    if verbose:
        print(f"[verbose] 识别结果: type={installation.type.value}, status={installation.status.value}")

    if installation.status in (DetectionStatus.ERROR, DetectionStatus.NOT_PRESENT) and not args.force:
        report = _build_report(root, installation, verbose)
        _print_human_summary(report)
        # 这种情况下也写报告，方便用户排查
        out = _write_report(report, args.out)
        print(f"报告已写入: {out}")
        return 2

    if installation.type == InstallationType.UNSUPPORTED and not args.force:
        report = _build_report(root, installation, verbose)
        _print_human_summary(report)
        print("\n[提示] 当前版本仅正式支持 ComfyUI Portable (Windows)。", file=sys.stderr)
        print("       如需继续调试，请添加 --force 参数。", file=sys.stderr)
        out = _write_report(report, args.out)
        print(f"报告已写入: {out}")
        return 3

    report = _build_report(root, installation, verbose)
    _print_human_summary(report)
    out = _write_report(report, args.out)
    print(f"报告已写入: {out}")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return cmd_scan(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
