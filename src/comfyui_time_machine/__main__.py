"""允许通过 `python -m comfyui_time_machine` 运行 CLI 或 GUI。

行为：
- 双击 exe / 无参数 / 带 --gui  → 启动 GUI
- 有 scan / --version / -h / --help  → 走 CLI
"""

import sys


def main():
    args = sys.argv[1:]

    # 明确的 CLI 命令 → 走 CLI
    cli_first_args = {"scan", "--version", "-h", "--help", "--verbose"}
    if args and args[0] in cli_first_args:
        from comfyui_time_machine.cli import main as cli_main
        raise SystemExit(cli_main())

    # 其他情况（无参数 / --gui / 其他未知参数）→ 启动 GUI
    from comfyui_time_machine.ui.main_window import run_gui
    run_gui()


if __name__ == "__main__":
    main()
