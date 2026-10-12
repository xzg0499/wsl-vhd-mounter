"""wsl.exe 调用封装。

要点：
- 用 CREATE_NO_WINDOW 避免弹出黑窗；
- wsl.exe 部分输出是 UTF-16LE（带 NUL 字节），按 NUL 占比启发式解码；
- 发行版内的多行脚本统一走 base64 管道，避免引号/编码问题。
"""

from __future__ import annotations

import base64
import shlex
import subprocess
from typing import Sequence

from . import log

WSL_EXE = "wsl.exe"


def _decode(data: bytes) -> str:
    if not data:
        return ""
    null_ratio = data.count(b"\x00") / max(len(data), 1)
    if null_ratio > 0.2:
        try:
            return data.decode("utf-16-le").lstrip("\ufeff").strip()
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace").strip()


def run_wsl(args: Sequence[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """直接调 wsl.exe 顶层命令（--mount / --shutdown / -l 等）。"""
    cmd = [WSL_EXE, *args]
    log.info(f"$ {shlex.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        log.error(f"wsl.exe 超时: {shlex.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 124, b"", b"timeout")
    except OSError as e:
        log.error(f"无法启动 wsl.exe: {e}")
        return subprocess.CompletedProcess(cmd, 127, b"", str(e).encode())
    proc.stdout = _decode(proc.stdout)
    proc.stderr = _decode(proc.stderr)
    if proc.returncode != 0:
        log.warn(f"wsl.exe 返回 {proc.returncode}: {proc.stderr or proc.stdout}")
    return proc


def run_in_distro(distro: str, script: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """在发行版内以 root 执行一段 bash 脚本（base64 传输，杜绝引号转义问题）。"""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    # sh -c 的参数是纯 ASCII base64，无转义风险
    return run_wsl(
        ["-d", distro, "-u", "root", "-e", "sh", "-c", f"echo {b64} | base64 -d | bash"],
        timeout=timeout,
    )


def run_in_distro_args(distro: str, cmd: Sequence[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """在发行版内以 root 执行简单单命令（无引号嵌套时用，省一次 bash 开销）。"""
    return run_wsl(["-d", distro, "-u", "root", "-e", *cmd], timeout=timeout)


def wsl_available() -> tuple[bool, str]:
    """检查 wsl.exe 可用性与版本信息。"""
    p = run_wsl(["--version"], timeout=60)
    if p.returncode != 0:
        return False, p.stderr or p.stdout or "wsl.exe 调用失败"
    return True, p.stdout
