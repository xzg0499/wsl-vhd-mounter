"""入口：python -m wsl_vhd_mounter 启动托盘工具。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox

from . import log
from .config import load
from .gui.tray import TrayApp


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("WslVhdMounter")
    app.setQuitOnLastWindowClosed(False)  # 关窗口不退出，托盘常驻

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "WSL VHD 挂载工具", "系统托盘不可用，无法常驻。")
        return 1

    cfg = load()
    tray = TrayApp(app, cfg)
    log.info(f"托盘工具启动：{len(cfg.disks)} 张磁盘配置，发行版 {cfg.distro}")
    # 启动时后台检查一次钩子状态
    tray._status.check_hook()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
