"""托盘常驻入口：托盘图标 + 菜单，管理状态/设置窗口。"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import AppConfig
from ..mounter import mount_all, unmount_all
from .settings_window import SettingsWindow
from .status_window import StatusWindow
from .worker import Worker


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#2563eb"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("white"))
    f = p.font()
    f.setPointSize(24)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "V")
    p.end()
    return QIcon(pm)


class TrayApp:
    def __init__(self, app, cfg: AppConfig):
        self._app = app
        self._cfg = cfg
        self._workers: list[Worker] = []

        self._icon = QSystemTrayIcon(make_icon(), app)
        self._icon.setToolTip("WSL VHD 挂载工具")

        self._status = StatusWindow(cfg)
        self._status.closeEvent = lambda e: (e.ignore(), self._status.hide())
        self._settings = SettingsWindow(cfg)
        self._settings.closeEvent = lambda e: (e.ignore(), self._settings.hide())

        self._build_menu()
        self._icon.show()
        self._icon.activated.connect(self._on_activated)

        self._timer = QTimer(app)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---------- 菜单 ----------
    def _build_menu(self) -> None:
        m = QMenu()
        self._act_status = QAction("状态面板", self._app)
        self._act_settings = QAction("设置…", self._app)
        self._act_mount_all = QAction("全部挂载", self._app)
        self._act_unmount_all = QAction("全部卸载", self._app)
        self._act_log = QAction("查看日志", self._app)
        self._act_quit = QAction("退出", self._app)

        self._act_status.triggered.connect(self.show_status)
        self._act_settings.triggered.connect(self.show_settings)
        self._act_mount_all.triggered.connect(self.mount_all)
        self._act_unmount_all.triggered.connect(self.unmount_all)
        self._act_log.triggered.connect(self.show_log)
        self._act_quit.triggered.connect(self._app.quit)

        m.addAction(self._act_status)
        m.addAction(self._act_settings)
        m.addSeparator()
        m.addAction(self._act_mount_all)
        m.addAction(self._act_unmount_all)
        m.addSeparator()
        m.addAction(self._act_log)
        m.addSeparator()
        m.addAction(self._act_quit)
        self._icon.setContextMenu(m)

    # ---------- 窗口 ----------
    def show_status(self) -> None:
        self._status.show()
        self._status.raise_()
        self._status.activateWindow()
        self._status.refresh()

    def show_settings(self) -> None:
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def show_log(self) -> None:
        self._status.show_log()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_status()

    # ---------- 操作 ----------
    def mount_all(self) -> None:
        self._start_worker(mount_all, self._cfg.distro, list(self._cfg.disks))

    def unmount_all(self) -> None:
        self._start_worker(unmount_all, self._cfg.distro, list(self._cfg.disks))

    def _start_worker(self, fn, *args) -> None:
        w = Worker(fn, *args)
        self._workers.append(w)
        w.finished.connect(lambda _r: self._workers.remove(w) if w in self._workers else None)
        w.finished.connect(lambda _r: self._status.refresh())
        w.start()

    def _poll(self) -> None:
        if self._status.isVisible():
            self._status.refresh()

    def set_cfg(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._status.set_cfg(cfg)
