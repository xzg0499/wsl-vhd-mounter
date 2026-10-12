#!/usr/bin/env python3
"""WSL VHD 自动挂载钩子 —— 发行版启动时由 systemd 拉起。

职责：
  1. 读取 Windows 侧配置文件（/mnt/c/.../WslVhdMounter/config.json）
  2. 对每张启用状态的 VHD 做幂等挂载（wsl.exe --mount --vhd + bind 到目标目录）
  3. start/stop 两个子命令（systemd oneshot）

本文件由 Windows 侧安装器写入 /usr/local/bin/wsl-vhd-hook.py，
CONFIG 路径在安装时替换占位符。
"""

import json
import os
import shlex
import subprocess
import sys
import time

CONFIG = "__CONFIG_PLACEHOLDER__/WslVhdMounter/config.json"
LOG = "/var/log/wsl-vhd-mounter.log"

PYTHON = sys.executable or "python3"

# systemd 服务环境没有 interop PATH，必须用绝对路径调 wsl.exe
WSL_EXE = "/mnt/c/Windows/System32/wsl.exe"
if not os.path.isfile(WSL_EXE):
    WSL_EXE = "wsl.exe"  # automount 关闭等极端情况的兜底（依赖 PATH）


def log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def decode(b: bytes) -> str:
    """wsl.exe 输出是 UTF-16LE（带 NUL 字节），按 NUL 占比启发式解码。"""
    if not b:
        return ""
    null_ratio = b.count(b"\x00") / max(len(b), 1)
    if null_ratio > 0.2:
        try:
            return b.decode("utf-16-le").lstrip("\ufeff")
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", errors="replace")


def sh(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """发行版内 shell 执行。"""
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"TIMEOUT: {cmd}")
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def q(s: str) -> str:
    return shlex.quote(s)


def find_attach_point(name: str) -> str:
    """返回实际 VM 挂载点：WSL 3.x 默认 /mnt/wsl/<name>，旧版 /mnt/<name>。"""
    for p in (f"/mnt/wsl/{name}", f"/mnt/{name}"):
        if sh(f"mountpoint -q {q(p)}").returncode == 0:
            return p
    return ""


def attached(name: str) -> bool:
    return bool(find_attach_point(name))


def target_mounted(target: str) -> bool:
    return sh(f"mountpoint -q {q(target)}").returncode == 0


def wsl_mount(vhd: str, name: str, partition: int) -> tuple[bool, str]:
    args = [WSL_EXE, "--mount", vhd, "--vhd", "--name", name]
    if partition > 0:
        args += ["--partition", str(partition)]
    try:
        r = subprocess.run(args, capture_output=True, timeout=180)
        if r.returncode == 0:
            return True, ""
        return False, decode(r.stderr or r.stdout).strip()[:300]
    except Exception as e:
        return False, str(e)


def find_new_device() -> str:
    """--bare 后通过 lsblk 差集探测新增块设备。"""
    before = sh("lsblk -dn -o NAME", timeout=30)
    if before.returncode != 0:
        return ""
    before_names = {ln.strip() for ln in before.stdout.splitlines() if ln.strip()}
    for _ in range(6):
        time.sleep(1)
        after = sh("lsblk -dn -o NAME", timeout=30)
        if after.returncode != 0:
            continue
        after_names = {ln.strip() for ln in after.stdout.splitlines() if ln.strip()}
        diff = after_names - before_names
        for dev in sorted(diff):
            if dev.startswith(("sd", "vd", "nvme")):
                return dev
    return ""


def mount_one(d: dict) -> None:
    name = d.get("name", "data")
    target = d.get("mount_target", "/data")
    vhd = d.get("vhd_path", "")
    partition = int(d.get("partition", 0) or 0)
    readonly = bool(d.get("readonly", False))
    bare_fallback = bool(d.get("bare_fallback", True))
    if not vhd:
        log(f"[{name}] 跳过：VHD 路径为空")
        return

    if target_mounted(target):
        log(f"[{name}] 已挂载，跳过")
        return

    if not attached(name):
        ok, err = wsl_mount(vhd, name, partition)
        if not ok:
            if bare_fallback and partition == 0:
                log(f"[{name}] 整盘挂载失败({err})，尝试 --bare 兜底")
                try:
                    r = subprocess.run(
                        [WSL_EXE, "--mount", vhd, "--vhd", "--bare"],
                        capture_output=True, timeout=180,
                    )
                except Exception as e:
                    log(f"[{name}] bare 调用异常: {e}")
                    return
                if r.returncode != 0:
                    log(f"[{name}] bare 挂载也失败: {decode(r.stderr or r.stdout).strip()[:300]}")
                    return
                dev = find_new_device()
                if not dev:
                    log(f"[{name}] bare 后未探测到新设备")
                    return
                if sh(f"mkdir -p {q(target)} && mount /dev/{dev} {q(target)}").returncode != 0:
                    log(f"[{name}] 挂载 /dev/{dev} 到 {target} 失败")
                    return
                log(f"[{name}] bare 挂载成功: /dev/{dev} -> {target}")
                return
            log(f"[{name}] 挂载失败: {err}")
            return

    attach_pt = find_attach_point(name)
    if not attach_pt:
        log(f"[{name}] 未找到实际挂载点(/mnt/wsl/{name} 或 /mnt/{name})")
        return
    if sh(f"mkdir -p {q(target)} && mount --bind {attach_pt} {q(target)}").returncode != 0:
        log(f"[{name}] bind 挂载 {attach_pt} -> {target} 失败")
        return

    if readonly:
        sh(f"mount -o remount,ro {q(attach_pt)}")
    log(f"[{name}] 挂载完成: {attach_pt} -> {target}")


def unmount_one(d: dict) -> None:
    name = d.get("name", "data")
    target = d.get("mount_target", "/data")
    vhd = d.get("vhd_path", "")
    sh(f"umount {q(target)} 2>/dev/null")
    try:
        subprocess.run([WSL_EXE, "--unmount", vhd],
                       capture_output=True, timeout=120)
    except Exception:
        pass
    for p in (f"/mnt/wsl/{name}", f"/mnt/{name}"):
        sh(f"umount {q(p)} 2>/dev/null")
    log(f"[{name}] 已卸载")


def load_config() -> list[dict]:
    # 等待 /mnt/c automount 就绪
    for _ in range(30):
        if os.path.isdir("/mnt/c"):
            break
        time.sleep(1)
    if not os.path.isdir("/mnt/c"):
        log("ERROR: /mnt/c 未就绪(automount 未生效)")
        return []
    if not os.path.isfile(CONFIG):
        log(f"ERROR: 配置文件不存在: {CONFIG}")
        return []
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        return [d for d in cfg.get("disks", []) if d.get("enabled")]
    except Exception as e:
        log(f"ERROR: 解析配置失败: {e}")
        return []


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    disks = load_config()
    if action == "stop":
        for d in disks:
            unmount_one(d)
        return 0
    for d in disks:
        mount_one(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
