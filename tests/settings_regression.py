"""设置窗口回归：添加行 → 填数据 → _collect 收集（复现 findChild None bug）。"""

import os
import sys
import tempfile

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="wvhd_set_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from wsl_vhd_mounter.config import load  # noqa: E402
from wsl_vhd_mounter.gui.settings_window import SettingsWindow  # noqa: E402

app = QApplication(sys.argv)
cfg = load()
w = SettingsWindow(cfg)

# 用户操作：添加两行，分别用两种方式填路径
w.add_row()
w.add_row()

# 行0：路径列(容器)填值；名/目标列(直接 QLineEdit)填值
w._table.cellWidget(0, 1).findChild(QLineEdit).setText("C:/test/disk1.vhdx")
w._table.cellWidget(0, 2).setText("data")
w._table.cellWidget(0, 3).setText("/data")

# 行1：全走容器式/直接式混合
w._table.cellWidget(1, 1).findChild(QLineEdit).setText("D:/test/disk2.vhdx")
w._table.cellWidget(1, 2).setText("media")
w._table.cellWidget(1, 3).setText("/media")

disks = w._collect()
print("COLLECTED:", len(disks))
for d in disks:
    print(f"  {d.name} -> {d.mount_target} | {d.vhd_path} | part={d.partition} ro={d.readonly} bare={d.bare_fallback} en={d.enabled}")
assert len(disks) == 2, "应收集到 2 行"
assert disks[0].name == "data" and disks[0].mount_target == "/data"
assert disks[1].name == "media" and disks[1].vhd_path == "D:/test/disk2.vhdx"
print("SETTINGS_REGRESSION_PASS")
