"""轻量日志模块：Windows 侧日志写到 %LOCALAPPDATA%/WslVhdMounter/logs/。"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_LOGGER_INITED = False
_LOGFILE: Path | None = None


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "WslVhdMounter"


def ensure_logfile() -> Path:
    global _LOGGER_INITED, _LOGFILE
    if not _LOGGER_INITED:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        _LOGFILE = d / "wsl-vhd-mounter.log"
        _LOGGER_INITED = True
    assert _LOGFILE is not None
    return _LOGFILE


def log(level: str, msg: str) -> None:
    f = ensure_logfile()
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}\n"
    try:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    # GUI 模式之外也打到控制台
    if os.environ.get("WVHM_DEBUG"):
        sys.stderr.write(line)


def info(msg: str) -> None:
    log("INFO", msg)


def warn(msg: str) -> None:
    log("WARN", msg)


def error(msg: str) -> None:
    log("ERROR", msg)
