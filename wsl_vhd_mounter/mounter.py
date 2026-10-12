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


def _find_new_device(distro: str) -> str:
    """--bare 挂载后，对比挂载前后 lsblk 找新增块设备名。"""
    before = run_in_distro(distro, "lsblk -dn -o NAME,SIZE")
    if before.returncode != 0:
        return ""
    before_names = set()
    for line in before.stdout.splitlines():
        parts = line.split()
        if parts:
            before_names.add(parts[0])

    # 等设备出现（最多 5s）
    import time
    for _ in range(5):
        time.sleep(1)
        after = run_in_distro(distro, "lsblk -dn -o NAME")
        if after.returncode == 0:
            after_names = {line.strip() for line in after.stdout.splitlines() if line.strip()}
            diff = after_names - before_names
            if diff:
                # 优先取 sdx 类设备
                for name in sorted(diff):
                    if name.startswith("sd") or name.startswith("vd") or name.startswith("nvme"):
                        return name
    return ""


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
        _script(
            f"""
            mountpoint -q {target} && echo TARGET_OK || echo TARGET_MISS
            mountpoint -q /mnt/wsl/{name} && echo MNT_OK || echo MNT_MISS
            mountpoint -q /mnt/{name} && echo MNT_OK || true
            """
        ),
    )
    if chk.returncode != 0:
        return DiskStatus(MountState.ERROR, "发行版内状态检查失败: " + (chk.stderr or chk.stdout))
    out = chk.stdout
    if "TARGET_OK" in out:
        log.info(f"[{name}] 已挂载，跳过")
        return DiskStatus(MountState.MOUNTED, "已挂载")

    # 1) 若 VM 层挂载已存在，跳过 wsl --mount
    if "MNT_OK" not in out:
        args = ["--mount", vhd, "--vhd", "--name", name]
        if disk.partition > 0:
            args += ["--partition", str(disk.partition)]
        r = run_wsl(args)
        if r.returncode != 0:
            if disk.bare_fallback and disk.partition == 0:
                log.warn(f"[{name}] 整盘挂载失败，尝试 --bare 兜底")
                r = run_wsl(["--mount", vhd, "--vhd", "--bare"])
                if r.returncode != 0:
                    return DiskStatus(MountState.ERROR, "整盘与 bare 挂载均失败: " + (r.stderr or r.stdout))
                dev = _find_new_device(distro)
                if not dev:
                    return DiskStatus(MountState.ERROR, "bare 挂载成功但未探测到新设备(lsblk 无变化)")
                log.info(f"[{name}] bare 模式，新设备 /dev/{dev}")
                r2 = run_in_distro(
                    distro,
                    _script(
                        f"""
                        mkdir -p {target}
                        mount /dev/{dev} {target} || exit 10
                        """
                    ),
                )
                if r2.returncode != 0:
                    return DiskStatus(MountState.ERROR, f"挂载 /dev/{dev} 到 {target} 失败: " + (r2.stderr or r2.stdout))
                return _apply_readonly(distro, disk, target)
            return DiskStatus(MountState.ERROR, "wsl --mount 失败: " + (r.stderr or r.stdout))

    # 2) bind: 实际挂载点 -> <target>
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

    return _apply_readonly(distro, disk, target, attach_pt=attach_pt)


def _apply_readonly(distro: str, disk: DiskConfig, target: str, attach_pt: str | None = None) -> DiskStatus:
    if not disk.readonly:
        return DiskStatus(MountState.MOUNTED, f"已挂载到 {target}")
    src = attach_pt or f"/mnt/wsl/{disk.name}"
    r = run_in_distro(
        distro,
        _script(f"mount -o remount,ro {src} || mount -o remount,ro {target}"),
    )
    if r.returncode != 0:
        log.warn(f"[{disk.name}] 只读 remount 失败(忽略): {r.stderr or r.stdout}")
    return DiskStatus(MountState.MOUNTED, f"已挂载(只读)到 {target}")


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
        _script(
            f"""
            mountpoint -q {disk.mount_target} && echo TARGET_OK || echo TARGET_MISS
            mountpoint -q /mnt/wsl/{disk.name} && echo MNT_OK || echo MNT_MISS
            mountpoint -q /mnt/{disk.name} && echo MNT_OK || true
            """
        ),
        timeout=60,
    )
    if chk.returncode != 0:
        return DiskStatus(MountState.ERROR, "状态查询失败: " + (chk.stderr or chk.stdout))
    if "TARGET_OK" in chk.stdout:
        return DiskStatus(MountState.MOUNTED, f"已挂载到 {disk.mount_target}")
    if "MNT_OK" in chk.stdout:
        return DiskStatus(MountState.ATTACHED, "VM 层已挂载，等待绑定")
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
