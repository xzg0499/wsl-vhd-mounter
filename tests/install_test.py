"""钩子安装实测：往指定发行版安装钩子并验证。

用法：venv/Scripts/python.exe tests/install_test.py [distro]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsl_vhd_mounter.installer import hook_log, install, is_installed  # noqa: E402

distro = sys.argv[1] if len(sys.argv) > 1 else "Ubuntu"
ok, msg = install(distro)
print("INSTALL:", ok, "|", msg)
print("IS_INSTALLED:", is_installed(distro))
print("--- hook log ---")
print(hook_log(distro, 30))
sys.exit(0 if ok else 1)
