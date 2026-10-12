"""状态面板：列出每张 VHD 的挂载状态，支持单盘/全部 挂载与卸载。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import installer, log
from ..config import AppConfig, DiskConfig
from ..mounter import MountState, mount_all, mount_disk, refresh, unmount_all, unmount_disk
from .worker import Worker

STATE_COLORS = {
    MountState.MOUNTED: "#1a7f37",
    MountState.ATTACHED: "#9a6700",
    MountState.UNMOUNTED: "#6e7781",
    MountState.ERROR: "#cf222e",
    MountState.DISABLED: "#8b949e",
}


class StatusWindow(QWidget):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._workers: list[Worker] = []
        self.setWindowTitle("WSL VHD 挂载状态")
        self.resize(760, 420)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新")
        self._btn_mount_all = QPushButton("全部挂载")
        self._btn_unmount_all = QPushButton("全部卸载")
        self._btn_log = QPushButton("查看日志")
        self._btn_install = QPushButton("安装钩子")
        self._btn_uninstall = QPushButton("卸载钩子")
        for b in (self._btn_refresh, self._btn_mount_all, self._btn_unmount_all,
                  self._btn_log, self._btn_install, self._btn_uninstall):
            bar.addWidget(b)
        bar.addStretch(1)
        self._hook_label = QLabel("钩子状态: 检测中…")
        bar.addWidget(self._hook_label)
        root.addLayout(bar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["VHD 文件", "挂载名", "目标目录", "状态", "操作"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 320)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 160)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table)

        # 信号
        self._btn_refresh.clicked.connect(self.refresh)
        self._btn_mount_all.clicked.connect(self.mount_all)
        self._btn_unmount_all.clicked.connect(self.unmount_all)
        self._btn_log.clicked.connect(self.show_log)
        self._btn_install.clicked.connect(self.install_hook)
        self._btn_uninstall.clicked.connect(self.uninstall_hook)

    # ---------- 数据 ----------
    def set_cfg(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self.refresh()

    def _set_busy(self, busy: bool) -> None:
        for b in (self._btn_refresh, self._btn_mount_all, self._btn_unmount_all,
                  self._btn_install, self._btn_uninstall):
            b.setEnabled(not busy)

    def refresh(self) -> None:
        self._set_busy(True)
        self._start_worker(refresh, self._cfg.distro, list(self._cfg.disks), self._apply_statuses)

    def _apply_statuses(self, statuses: dict[str, object]) -> None:
        self._set_busy(False)
        disks = self._cfg.disks
        self._table.setRowCount(len(disks))
        for row, d in enumerate(disks):
            st = statuses.get(d.disk_id)
            state = getattr(st, "state", MountState.UNMOUNTED)
            detail = getattr(st, "detail", "")
            self._table.setItem(row, 0, QTableWidgetItem(d.vhd_path))
            self._table.setItem(row, 1, QTableWidgetItem(d.name))
            self._table.setItem(row, 2, QTableWidgetItem(d.mount_target))
            cell = QTableWidgetItem(f"{state.value}  {detail}")
            cell.setForeground(Qt.GlobalColor.black)
            cell.setBackground(STATE_COLORS.get(state, "#6e7781"))
            self._table.setItem(row, 3, cell)
            # 操作列：单盘挂载/卸载
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(4, 2, 4, 2)
            bm = QPushButton("挂载")
            bu = QPushButton("卸载")
            bm.clicked.connect(lambda _=False, d=d: self.mount_one(d))
            bu.clicked.connect(lambda _=False, d=d: self.unmount_one(d))
            lay.addWidget(bm)
            lay.addWidget(bu)
            self._table.setCellWidget(row, 4, box)

    # ---------- 操作 ----------
    def mount_one(self, d: DiskConfig) -> None:
        self._start_worker(mount_disk, self._cfg.distro, d, lambda r: self._notify_op("挂载", r))

    def unmount_one(self, d: DiskConfig) -> None:
        self._start_worker(unmount_disk, self._cfg.distro, d, lambda r: self._notify_op("卸载", r))

    def mount_all(self) -> None:
        self._set_busy(True)
        self._start_worker(mount_all, self._cfg.distro, list(self._cfg.disks), self._after_all)

    def unmount_all(self) -> None:
        self._set_busy(True)
        self._start_worker(unmount_all, self._cfg.distro, list(self._cfg.disks), self._after_all)

    def _after_all(self, r: tuple[bool, object]) -> None:
        self._set_busy(False)
        if not r[0]:
            self._hook_label.setText(f"操作失败: {r[1]}")
        self.refresh()

    def _notify_op(self, op: str, r: tuple[bool, object]) -> None:
        ok, payload = r
        name = getattr(payload, "state", None)
        if ok and name is not None:
            self._hook_label.setText(f"{op}完成: {payload.state.value} {payload.detail}")
        else:
            self._hook_label.setText(f"{op}失败: {payload}")
        self.refresh()

    # ---------- 钩子管理 ----------
    def install_hook(self) -> None:
        self._set_busy(True)
        self._start_worker(installer.install, self._cfg.distro, self._after_hook_op)

    def uninstall_hook(self) -> None:
        self._set_busy(True)
        self._start_worker(installer.uninstall, self._cfg.distro, self._after_hook_op)

    def _after_hook_op(self, r: tuple[bool, object]) -> None:
        self._set_busy(False)
        ok, msg = r
        self._hook_label.setText(f"钩子: {msg if not ok else '已安装/启用'}")
        if not ok:
            log.error(f"钩子操作失败: {msg}")

    def check_hook(self) -> None:
        self._start_worker(installer.is_installed, self._cfg.distro, self._after_hook_check)

    def _after_hook_check(self, r: tuple[bool, object]) -> None:
        ok, installed = r
        self._hook_label.setText("钩子状态: " + ("已安装" if ok and installed else "未安装"))

    # ---------- 日志 ----------
    def show_log(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("日志")
        dlg.resize(640, 420)
        lay = QVBoxLayout(dlg)
        lbl = QLabel("WSL 钩子日志 (/var/log/wsl-vhd-mounter.log)：")
        lay.addWidget(lbl)
        from PySide6.QtWidgets import QPlainTextEdit
        te = QPlainTextEdit()
        te.setReadOnly(True)
        lay.addWidget(te)
        self._start_worker(installer.hook_log, self._cfg.distro, 100,
                           lambda r: te.setPlainText(r[1] if r[0] else f"读取失败: {r[1]}"))
        dlg.exec()

    # ---------- 工具 ----------
    def _start_worker(self, fn, *args, on_done=None) -> None:
        w = Worker(fn, *args)
        self._workers.append(w)
        if on_done:
            w.finished.connect(on_done)
        w.finished.connect(lambda _r: self._workers.remove(w) if w in self._workers else None)
        w.start()
