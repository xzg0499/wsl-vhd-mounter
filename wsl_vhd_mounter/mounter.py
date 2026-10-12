"""挂载/卸载/状态核心逻辑（Windows 侧驱动 wsl.exe）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from . import log
from .config import DiskConfig
from .wsl_core import run_in_distro, run_wsl

_LOCK = threading.Lock()


class MountState(Enum):
    UNMOUNTED = "未挂载"
    ATTACHED = "已挂载(未绑定目标)"
    MOUNTED = "已挂载"
    ERROR = "错误"
    DISABLED = "已禁用"


@dataclass
class DiskStatus:
    state: MountState
    detail: str = ""


def _script(text: str) -> str:
    return text.strip()


def _find_data_device(distro: str) -> str:
    """发行版内找未挂载数据盘：TYPE=disk、无挂载点、非 swap、容量最大（单位换算）。"""
    r = run_in_distro(
        distro,
        _script(
            """
            python3 - <<'PY'
            import subprocess
            out = subprocess.run(["lsblk", "-dn", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS"],
                                 capture_output=True, text=True).stdout
            cands = []
            for ln in out.splitlines():
                p = ln.split()
                if len(p) < 3:
                    continue
                name, size, typ = p[0], p[1], p[2]
                mnt = " ".join(p[3:])
                if typ != "disk" or mnt:
                    continue
                s = size.upper()
                try:
                    if s.endswith("T"):
                        v = int(float(s[:-1]) * 1048576)
                    elif s.endswith("G"):
                        v = int(float(s[:-1]) * 1024)
                    elif s.endswith("M"):
                        v = int(float(s[:-1]))
                    else:
                        continue
                except ValueError:
                    continue
                cands.append((v, name))
            print(sorted(cands, reverse=True)[0][1] if cands else "")
            PY
            """
        ),
        timeout=60,
    )
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def mount_disk(distro: str, disk: DiskConfig) -> DiskStatus:
    if not disk.enabled:
        return DiskStatus(MountState.DISABLED)
    with _LOCK:
        return _mount_disk_locked(distro, disk)


def _attach_path_script(name: str) -> str:
    """探测实际 VM 挂载点：WSL 3.x /mnt/wsl/<name>，旧版 /mnt/<name>。"""
    return _script(
        f"""
        for p in /mnt/wsl/{name} /mnt/{name}; do
            mountpoint -q "$p" && echo "ATTACH_PT=$p" && break
        done
        """
    )


def _mount_disk_locked(distro: str, disk: DiskConfig) -> DiskStatus:
    name = disk.name
    target = disk.mount_target
    vhd = disk.vhd_path

    # 0) 幂等：目标目录已挂载 → 直接成功
    chk = run_in_distro(
        distro,
        _script(f"mountpoint -q {target} && echo TARGET_OK || echo TARGET_MISS"),
    )
    if chk.returncode != 0:
        return DiskStatus(MountState.ERROR, "发行版内状态检查失败: " + (chk.stderr or chk.stdout))
    if "TARGET_OK" in chk.stdout:
        log.info(f"[{name}] 已挂载，跳过")
        return DiskStatus(MountState.MOUNTED, "已挂载")

    if disk.partition > 0:
        return _mount_partition(distro, disk, name, target, vhd)

    # 1) 整盘：--bare 附加（幂等：已附加视为成功）
    r = run_wsl(["--mount", vhd, "--vhd", "--bare"])
    if r.returncode != 0 and "ALREADY_ATTACHED" not in (r.stderr or r.stdout):
        return DiskStatus(MountState.ERROR, "磁盘附加失败: " + (r.stderr or r.stdout))

    # 2) 发行版内装载
    import time
    dev = ""
    for _ in range(8):
        dev = _find_data_device(distro)
        if dev:
            break
        time.sleep(1)
    if not dev:
        return DiskStatus(MountState.ERROR, "未探测到数据盘设备(lsblk)")
    opts = " -o ro" if disk.readonly else ""
    rb = run_in_distro(
        distro,
        _script(f"mkdir -p {target} && mount{opts} /dev/{dev} {target}"),
    )
    if rb.returncode != 0:
        return DiskStatus(MountState.ERROR, f"挂载 /dev/{dev} 到 {target} 失败: " + (rb.stderr or rb.stdout))

    log.info(f"[{name}] 挂载完成: /dev/{dev} -> {target}")
    return DiskStatus(MountState.MOUNTED, f"已挂载到 {target}" + ("(只读)" if disk.readonly else ""))


def _mount_partition(distro: str, disk: DiskConfig, name: str, target: str, vhd: str) -> DiskStatus:
    """多分区场景：wsl --mount --name 自动装载，bind 到目标目录。"""
    # 若 VM 层挂载已存在（/mnt/wsl/<name> 或 /mnt/<name>），跳过 wsl --mount
    chk = run_in_distro(
        distro,
        _script(
            f"""
            mountpoint -q /mnt/wsl/{name} && echo MNT_OK || echo MNT_MISS
            mountpoint -q /mnt/{name} && echo MNT_OK || true
            """
        ),
    )
    if "MNT_OK" not in chk.stdout:
        args = ["--mount", vhd, "--vhd", "--name", name, "--partition", str(disk.partition)]
        r = run_wsl(args)
        if r.returncode != 0:
            return DiskStatus(MountState.ERROR, "wsl --mount 失败: " + (r.stderr or r.stdout))

    ap = run_in_distro(distro, _attach_path_script(name))
    attach_pt = ""
    for line in ap.stdout.splitlines():
        if line.startswith("ATTACH_PT="):
            attach_pt = line.split("=", 1)[1]
    if not attach_pt:
        return DiskStatus(MountState.ERROR, f"未找到实际挂载点(/mnt/wsl/{name} 或 /mnt/{name})")
    rb = run_in_distro(
        distro,
        _script(
            f"""
            mountpoint -q {target} || {{ mkdir -p {target} && mount --bind {attach_pt} {target} || exit 10; }}
            """
        ),
    )
    if rb.returncode != 0:
        return DiskStatus(MountState.ERROR, f"bind 挂载 {target} 失败: " + (rb.stderr or rb.stdout))
    if disk.readonly:
        run_in_distro(distro, _script(f"mount -o remount,ro {attach_pt}"))
    return DiskStatus(MountState.MOUNTED, f"已挂载到 {target}")


def unmount_disk(distro: str, disk: DiskConfig) -> DiskStatus:
    with _LOCK:
        name, target = disk.name, disk.mount_target
        # 1) 发行版内卸载 bind 目标
        run_in_distro(distro, _script(f"umount {target} 2>/dev/null; true"))
        # 2) VM 层卸载磁盘（wsl --unmount 是顶层命令，非 --mount 子参数）
        r = run_wsl(["--unmount", disk.vhd_path], timeout=120)
        if r.returncode != 0:
            # 发行版内兜底卸载 VM 挂载点（新旧两个位置都试）
            r2 = run_in_distro(
                distro,
                _script(f"umount /mnt/wsl/{name} 2>/dev/null; umount /mnt/{name} 2>/dev/null; true"),
            )
            if r2.returncode != 0:
                return DiskStatus(MountState.ERROR, "卸载失败: " + (r.stderr or r.stdout))
        # 3) 确认
        chk = run_in_distro(distro, _script(f"mountpoint -q {target} && echo STILL || echo GONE"))
        if "STILL" in chk.stdout:
            return DiskStatus(MountState.ERROR, f"{target} 仍处于挂载状态")
        log.info(f"[{name}] 已卸载")
        return DiskStatus(MountState.UNMOUNTED, "已卸载")


def status_of(distro: str, disk: DiskConfig) -> DiskStatus:
    if not disk.enabled:
        return DiskStatus(MountState.DISABLED)
    chk = run_in_distro(
        distro,
        _script(f"mountpoint -q {disk.mount_target} && echo TARGET_OK || echo TARGET_MISS"),
        timeout=60,
    )
    if chk.returncode != 0:
        return DiskStatus(MountState.ERROR, "状态查询失败: " + (chk.stderr or chk.stdout))
    if "TARGET_OK" in chk.stdout:
        return DiskStatus(MountState.MOUNTED, f"已挂载到 {disk.mount_target}")
    return DiskStatus(MountState.UNMOUNTED, "未挂载")


def mount_all(distro: str, disks: list[DiskConfig]) -> dict[str, DiskStatus]:
    results: dict[str, DiskStatus] = {}
    for d in disks:
        results[d.disk_id] = mount_disk(distro, d)
    return results


def unmount_all(distro: str, disks: list[DiskConfig]) -> dict[str, DiskStatus]:
    results: dict[str, DiskStatus] = {}
    for d in disks:
        results[d.disk_id] = unmount_disk(distro, d)
    return results


def refresh(distro: str, disks: list[DiskConfig]) -> dict[str, DiskStatus]:
    return {d.disk_id: status_of(distro, d) for d in disks}
