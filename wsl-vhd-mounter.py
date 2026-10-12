"""启动入口：python wsl-vhd-mounter.py（等价于 python -m wsl_vhd_mounter）。"""

import sys

from wsl_vhd_mounter.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
