"""冒烟测试：真实调用 wsl.exe + 发行版交互（配置隔离到临时 LOCALAPPDATA）。

用法：venv/Scripts/python.exe tests/smoke_test.py
"""

import os
import sys
import tempfile

# 隔离配置目录，避免污染真实配置
_tmp = tempfile.mkdtemp(prefix="wvhd_test_")
os.environ["LOCALAPPDATA"] = _tmp
os.environ.setdefault("WVHM_DEBUG", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsl_vhd_mounter import log, mounter  # noqa: E402
from wsl_vhd_mounter.config import AppConfig, DiskConfig, load, save  # noqa: E402

DISTRO = "Ubuntu"
FAILED = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILED.append(name)


# 1) config 读写（测试盘用独立名字，避免与真实环境已挂载盘冲突）
cfg = AppConfig()
d = DiskConfig(vhd_path="C:/nonexistent/disk.vhdx", name="smoketest", mount_target="/smoketest")
cfg.disks = [d]
save(cfg)
cfg2 = load()
check("config 保存/读取", cfg2.disks[0].name == "smoketest" and cfg2.distro == "Ubuntu")

# 2) 状态查询：不存在的盘 → UNMOUNTED
st = mounter.status_of(DISTRO, d)
check("status_of 未挂载", st.state == mounter.MountState.UNMOUNTED, f"-> {st.state.value} {st.detail}")

# 3) 挂载不存在的 VHD → ERROR（验证错误路径与 UTF-16 解码）
st2 = mounter.mount_disk(DISTRO, d)
check("mount 不存在路径返回 ERROR", st2.state == mounter.MountState.ERROR,
      f"-> {st2.state.value} | {st2.detail[:120]}")

# 4) 卸载不存在的 VHD → 不崩溃（返回 UNMOUNTED 或 ERROR 均可接受）
st3 = mounter.unmount_disk(DISTRO, d)
check("unmount 不存在路径不崩溃", st3.state in (mounter.MountState.UNMOUNTED, mounter.MountState.ERROR),
      f"-> {st3.state.value} {st3.detail}")

# 5) 空磁盘列表批量操作
cfg.disks = []
save(cfg)
r_all = mounter.mount_all(DISTRO, [])
check("mount_all 空列表", r_all == {})

print()
print("结果:", "全部通过" if not FAILED else f"{len(FAILED)} 项失败: {FAILED}")
print(f"日志: {log.ensure_logfile()}")
sys.exit(1 if FAILED else 0)
