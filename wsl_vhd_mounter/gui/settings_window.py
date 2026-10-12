"""设置窗口：编辑 VHD 列表（路径、挂载名、目标目录、分区、只读等）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import DiskConfig, save
from .. import autostart, log


class SettingsWindow(QWidget):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._rows: list[DiskConfig] = list(cfg.disks)
        self.setWindowTitle("WSL VHD 挂载设置")
        self.resize(860, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tip = QLabel("挂载点固定规则：wsl --mount 挂到 /mnt/<挂载名>，再 bind 到「目标目录」（如 /data）。"
                     "分区号 0 表示整盘/自动。")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["启用", "VHD 文件", "挂载名", "目标目录", "分区", "只读", "bare兜底", "删除"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w in enumerate([50, 0, 80, 110, 60, 50, 70, 60]):
            if w:
                self._table.setColumnWidth(i, w)
        root.addWidget(self._table)
        self._populate()

        bar = QHBoxLayout()
        self._btn_add = QPushButton("添加 VHD")
        self._btn_save = QPushButton("保存")
        self._btn_cancel = QPushButton("取消")
        self._btn_add.clicked.connect(self.add_row)
        self._btn_save.clicked.connect(self.save)
        self._btn_cancel.clicked.connect(self.close)
        bar.addWidget(self._btn_add)
        bar.addStretch(1)
        bar.addWidget(self._btn_save)
        bar.addWidget(self._btn_cancel)
        root.addLayout(bar)

        # 开机自启（仅打包后的 exe 可用）
        self._chk_autostart = QCheckBox("开机自动启动（常驻托盘）")
        if autostart.is_frozen():
            self._chk_autostart.setChecked(autostart.is_enabled())
        else:
            self._chk_autostart.setEnabled(False)
            self._chk_autostart.setToolTip("仅打包后的 exe 支持（python 源码运行时不生效）")
        root.addWidget(self._chk_autostart)

    # ---------- 行编辑 ----------
    def _populate(self) -> None:
        self._table.setRowCount(len(self._rows))
        for row, d in enumerate(self._rows):
            self._fill_row(row, d)

    def _fill_row(self, row: int, d: DiskConfig) -> None:
        en = QCheckBox()
        en.setChecked(d.enabled)
        self._table.setCellWidget(row, 0, en)

        path_box = QWidget()
        lay = QHBoxLayout(path_box)
        lay.setContentsMargins(0, 0, 0, 0)
        ed = QLineEdit(d.vhd_path)
        ed.setObjectName(f"path_{row}")
        browse = QPushButton("…")
        browse.setFixedWidth(28)
        browse.clicked.connect(lambda _=False, r=row: self._browse(r))
        lay.addWidget(ed)
        lay.addWidget(browse)
        self._table.setCellWidget(row, 1, path_box)

        self._table.setCellWidget(row, 2, self._line(d.name, f"name_{row}"))
        self._table.setCellWidget(row, 3, self._line(d.mount_target, f"target_{row}"))

        sp = QSpinBox()
        sp.setRange(0, 32)
        sp.setValue(d.partition)
        sp.setObjectName(f"part_{row}")
        sp.setToolTip("分区号：0 = 整盘自动（无分区表数据盘必选 0）；>0 = 挂指定分区")
        self._table.setCellWidget(row, 4, sp)

        ro = QCheckBox()
        ro.setChecked(d.readonly)
        self._table.setCellWidget(row, 5, ro)

        bf = QCheckBox()
        bf.setChecked(d.bare_fallback)
        self._table.setCellWidget(row, 6, bf)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _=False, r=row: self._del_row(r))
        self._table.setCellWidget(row, 7, del_btn)

    @staticmethod
    def _line(text: str, obj: str) -> QLineEdit:
        ed = QLineEdit(text)
        ed.setObjectName(obj)
        return ed

    def _browse(self, row: int) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "选择 VHD 文件", "", "VHD 磁盘 (*.vhdx *.vhd);;所有文件 (*.*)"
        )
        if p:
            ed = self._table.cellWidget(row, 1).findChild(QLineEdit)
            if ed:
                ed.setText(p)

    def add_row(self) -> None:
        d = DiskConfig(vhd_path="", name=f"data{len(self._rows)}", mount_target="/data")
        self._rows.append(d)
        self._table.insertRow(len(self._rows) - 1)
        self._fill_row(len(self._rows) - 1, d)

    def _del_row(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            self._rows.pop(row)
            self._table.removeRow(row)

    # ---------- 收集保存 ----------
    @staticmethod
    def _line_edit(cell) -> QLineEdit | None:
        """cell 可能是容器(QWidget+QLineEdit)或直接的 QLineEdit。"""
        if isinstance(cell, QLineEdit):
            return cell
        if cell is not None:
            return cell.findChild(QLineEdit)
        return None

    def _collect(self) -> list[DiskConfig]:
        disks: list[DiskConfig] = []
        for row in range(self._table.rowCount()):
            w_en = self._table.cellWidget(row, 0)
            w_path = self._table.cellWidget(row, 1)
            w_name = self._table.cellWidget(row, 2)
            w_target = self._table.cellWidget(row, 3)
            w_part = self._table.cellWidget(row, 4)
            w_ro = self._table.cellWidget(row, 5)
            w_bf = self._table.cellWidget(row, 6)
            if not all([w_en, w_path, w_name, w_target, w_part, w_ro, w_bf]):
                continue
            ed_path = self._line_edit(w_path)
            ed_name = self._line_edit(w_name)
            ed_target = self._line_edit(w_target)
            if not (ed_path and ed_name and ed_target):
                continue
            old = self._rows[row] if row < len(self._rows) else None
            disks.append(DiskConfig(
                disk_id=old.disk_id if old else DiskConfig().disk_id,
                vhd_path=ed_path.text().strip(),
                name=ed_name.text().strip(),
                mount_target=ed_target.text().strip(),
                partition=w_part.value(),
                readonly=w_ro.isChecked(),
                bare_fallback=w_bf.isChecked(),
                enabled=w_en.isChecked(),
            ))
        return disks

    def save(self) -> None:
        disks = self._collect()
        errs: list[str] = []
        for d in disks:
            errs.extend(d.validate())
        if errs:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "配置有误", "\n".join(errs[:6]))
            return
        self._cfg.disks = disks
        try:
            save(self._cfg)
            # 应用开机自启设置
            if autostart.is_frozen():
                autostart.set_enabled(self._chk_autostart.isChecked())
        except OSError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "保存失败", str(e))
            return
        except RuntimeError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "自启设置失败", str(e))
            return
        log.info(f"设置已保存: {len(disks)} 张磁盘")
        self.close()
