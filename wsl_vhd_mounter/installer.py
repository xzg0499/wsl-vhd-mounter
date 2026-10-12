"""WSL 钩子安装/卸载。

原理：把 wsl_guest/ 下的钩子脚本与 systemd unit 经 base64 管道写入发行版，
并确保 /etc/wsl.conf 开启 systemd。
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from . import log
from .config import config_dir
from .wsl_core import run_in_distro, run_wsl

HOOK_NAME = "wsl-vhd-hook.py"
SERVICE_NAME = "wsl-vhd-mount.service"
HOOK_PATH = f"/usr/local/bin/{HOOK_NAME}"
SERVICE_PATH = f"/etc/systemd/system/{SERVICE_NAME}"


def _guest_file(name: str) -> Path:
    """定位 wsl_guest 资源文件（兼容 PyInstaller 打包）。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "wsl_guest" / name
        if p.exists():
            return p
    p = Path(__file__).resolve().parent.parent / "wsl_guest" / name
    return p


def _windows_path_to_mnt(path: str) -> str:
    # 例: C:/Users/x 或 C:\Users\x -> /mnt/c/Users/x
    if len(path) >= 2 and path[1] == ":":
        return "/mnt/" + path[0].lower() + path[2:].replace("\\", "/")
    return path


def _b64_pipe(content: str) -> str:
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"echo {b64} | base64 -d"


def _wslconf_script() -> str:
    """确保 /etc/wsl.conf 的 [boot] 段含 systemd=true（幂等合并）。"""
    return r"""
import re
from pathlib import Path
p = Path('/etc/wsl.conf')
text = p.read_text(encoding='utf-8') if p.exists() else ''
if re.search(r'(?m)^\s*systemd\s*=\s*true\s*$', text):
    print('systemd already enabled')
else:
    lines = text.splitlines(keepends=True)
    boot_idx = None
    nxt_idx = len(lines)
    for i, ln in enumerate(lines):
        if re.match(r'^\s*\[', ln):
            if boot_idx is not None:
                nxt_idx = i
                break
            if ln.strip().lower() == '[boot]':
                boot_idx = i
    if boot_idx is None:
        out = text
        if out and not out.endswith('\n'):
            out += '\n'
        out += '\n[boot]\nsystemd=true\n'
    else:
        insert = '\n' if boot_idx > 0 else ''
        out = ''.join(lines[:boot_idx+1]) + insert + 'systemd=true\n' + ''.join(lines[boot_idx+1:])
    p.write_text(out, encoding='utf-8')
    print('systemd=true written to [boot]')
"""


def install(distro: str) -> tuple[bool, str]:
    """安装钩子：wsl.conf + 钩子脚本 + systemd 服务。"""
    # 1) wsl.conf 开启 systemd
    b64 = base64.b64encode(_wslconf_script().encode("utf-8")).decode("ascii")
    r = run_in_distro(
        distro,
        f"echo {b64} | base64 -d > /tmp/wvhd_wslconf.py && python3 /tmp/wvhd_wslconf.py && rm -f /tmp/wvhd_wslconf.py",
        timeout=60,
    )
    if r.returncode != 0:
        return False, "wsl.conf 配置失败: " + (r.stderr or r.stdout)

    # 2) 写入钩子脚本（替换配置路径占位符；config_dir().parent = LOCALAPPDATA，
    #    模板自带的 /WslVhdMounter/config.json 后缀保留）
    hook_tpl = _guest_file(HOOK_NAME).read_text(encoding="utf-8")
    mnt_cfg = _windows_path_to_mnt(str(config_dir().parent))
    hook_src = hook_tpl.replace("__CONFIG_PLACEHOLDER__", mnt_cfg)
    r = run_in_distro(
        distro,
        f"{_b64_pipe(hook_src)} > {HOOK_PATH} && chmod +x {HOOK_PATH}",
        timeout=60,
    )
    if r.returncode != 0:
        return False, "写入钩子脚本失败: " + (r.stderr or r.stdout)

    # 3) 写入 systemd unit
    unit_src = _guest_file(SERVICE_NAME).read_text(encoding="utf-8")
    r = run_in_distro(
        distro,
        f"{_b64_pipe(unit_src)} > {SERVICE_PATH}",
        timeout=60,
    )
    if r.returncode != 0:
        return False, "写入 systemd unit 失败: " + (r.stderr or r.stdout)

    # 4) 启用并启动（发行版可能尚未运行 systemd：用 symlink 兜底 enable）
    r = run_in_distro(
        distro,
        "systemctl daemon-reload 2>/dev/null; "
        f"ln -sf {SERVICE_PATH} /etc/systemd/system/multi-user.target.wants/{SERVICE_NAME}; "
        f"systemctl enable {SERVICE_NAME} 2>/dev/null || true; "
        f"systemctl start {SERVICE_NAME} 2>/dev/null || echo NO_SYSTEMD_YET; "
        "echo done",
        timeout=120,
    )
    if r.returncode != 0:
        return False, "启用服务失败: " + (r.stderr or r.stdout)

    log.info(f"钩子已安装到发行版 {distro}")
    hint = "（若当前未运行 systemd：WSL 重启后自动生效）" if "NO_SYSTEMD_YET" in r.stdout else ""
    return True, f"钩子已安装并启用{hint}"


def uninstall(distro: str) -> tuple[bool, str]:
    r = run_in_distro(
        distro,
        f"systemctl disable --now {SERVICE_NAME} 2>/dev/null; "
        f"rm -f {SERVICE_PATH} {HOOK_PATH} "
        f"/etc/systemd/system/multi-user.target.wants/{SERVICE_NAME}; "
        "systemctl daemon-reload 2>/dev/null; echo done",
        timeout=120,
    )
    if r.returncode != 0:
        return False, "卸载失败: " + (r.stderr or r.stdout)
    log.info(f"钩子已从发行版 {distro} 卸载（wsl.conf 的 systemd=true 保留，无害）")
    return True, "钩子已卸载（systemd=true 保留）"


def is_installed(distro: str) -> bool:
    r = run_in_distro(
        distro,
        f"[ -f {SERVICE_PATH} ] && [ -f {HOOK_PATH} ] && echo INSTALLED || echo MISSING",
        timeout=60,
    )
    return "INSTALLED" in r.stdout


def hook_log(distro: str, tail: int = 50) -> str:
    r = run_in_distro(distro, f"tail -n {tail} /var/log/wsl-vhd-mounter.log 2>/dev/null || echo '(日志不存在)'", timeout=60)
    return r.stdout or r.stderr or "(无输出)"
