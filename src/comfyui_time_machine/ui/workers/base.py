"""Worker 基类 —— QObject + Python threading + Qt QueuedConnection。

放弃 Qt C++ QThread（这台机器 Windows 11 25H2 + Qt 6.x 会栈溢出崩溃）。
改用 Python threading + Qt QueuedConnection：
  - run() 在 daemon Python 线程里执行
  - 所有 Signal.connect 默认用 Qt.ConnectionType.QueuedConnection
  - emit 时 Qt 自动把信号投递到主线程事件循环
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Qt


class BaseWorker(QObject):
    """通用 worker：Python threading + Qt QueuedConnection。

    用法：
        worker = SomeWorker(...)
        worker.progress.connect(on_prog, Qt.ConnectionType.QueuedConnection)
        worker.start()  # 启动 daemon Python 线程
    """

    # 进度（百分比 + 当前路径/描述）
    progress = Signal(int, str)
    # 通用日志
    log = Signal(str)
    # 完成（结果对象）
    finished_ok = Signal(object)
    # 失败（错误消息）
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._thread: threading.Thread | None = None
        self._cancelled = False

    # ---------- 控制 ----------

    def start(self):
        """启动后台线程（daemon=True，主线程退出自动清理）。"""
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._safe_run,
            daemon=True,
            name=f"Worker-{self.__class__.__name__}",
        )
        self._thread.start()

    def cancel(self):
        """标记取消。子类在 run() 里检查 self.cancelled。"""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def wait(self, timeout: float | None = None) -> bool:
        """等待线程结束。"""
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    # ---------- 内部 ----------

    def _safe_run(self):
        """run() 包装：顶层异常都转成 failed Signal。"""
        try:
            self.run()
        except SystemExit:
            raise
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.failed.emit(f"{e}\n{tb}")

    def run(self):
        """子类实现。"""
        raise NotImplementedError
