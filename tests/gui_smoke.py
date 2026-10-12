"""GUI 冒烟测试：offscreen 模式下创建托盘/窗口，跑一次真实状态刷新。

用法：QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe tests/gui_smoke.py
"""

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="wvhd_gui_")
os.environ["LOCALAPPDATA"] = _tmp  # 隔离配置

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from wsl_vhd_mounter.config import load  # noqa: E402
from wsl_vhd_mounter.gui.tray import TrayApp  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

cfg = load()
tray = TrayApp(app, cfg)
print("TRAY_ICON_VISIBLE:", tray._icon.isVisible())
print("STATUS_WINDOW_CREATED:", tray._status is not None)
print("SETTINGS_WINDOW_CREATED:", tray._settings is not None)

# 真实刷新：worker 线程跑 wsl 状态查询，等它完成
tray._status.refresh()
loop = QEventLoop()
QTimer.singleShot(25_000, loop.quit)
loop.exec()

rows = tray._status._table.rowCount()
print("TABLE_ROWS:", rows, "(expect 0, 空配置)")
print("HOOK_LABEL:", tray._status._hook_label.text())

tray._status.close()
tray._settings.close()
print("GUI_SMOKE_DONE")
