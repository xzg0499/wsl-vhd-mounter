"""后台任务线程：把 mounter 的阻塞操作搬出 UI 线程。"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

JobResult = tuple[bool, Any]  # (ok, payload)


class Worker(QThread):
    finished = Signal(object)  # JobResult

    def __init__(self, fn: Callable[..., Any], *args: Any, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self) -> None:  # noqa: D401
        try:
            payload = self._fn(*self._args)
            self.finished.emit((True, payload))
        except Exception as e:  # noqa: BLE001
            self.finished.emit((False, str(e)))
