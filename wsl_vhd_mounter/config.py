"""配置管理：JSON 存于 %LOCALAPPDATA%/WslVhdMounter/config.json。

WSL 钩子脚本通过 /mnt/c/<LOCALAPPDATA 对应路径>/WslVhdMounter/config.json 读取同一份配置。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import log


@dataclass
class DiskConfig:
    vhd_path: str = ""
    name: str = "data"             # wsl --mount --name，挂载到 /mnt/<name>
    mount_target: str = "/data"    # WSL 内 bind 目标目录
    partition: int = 0             # 0 = 整盘/自动；>0 = 挂指定分区
    readonly: bool = False
    bare_fallback: bool = True     # 整盘挂载失败时尝试 --bare + 手动 mount
    enabled: bool = True
    disk_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.disk_id,
            "vhd_path": self.vhd_path,
            "name": self.name,
            "mount_target": self.mount_target,
            "partition": self.partition,
            "readonly": self.readonly,
            "bare_fallback": self.bare_fallback,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DiskConfig":
        return cls(
            disk_id=str(d.get("id", uuid.uuid4().hex[:8])),
            vhd_path=str(d.get("vhd_path", "")),
            name=str(d.get("name", "data")),
            mount_target=str(d.get("mount_target", "/data")),
            partition=int(d.get("partition", 0)),
            readonly=bool(d.get("readonly", False)),
            bare_fallback=bool(d.get("bare_fallback", True)),
            enabled=bool(d.get("enabled", True)),
        )

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.vhd_path:
            errs.append(f"[{self.name}] VHD 路径为空")
        elif not Path(self.vhd_path).exists():
            errs.append(f"[{self.name}] VHD 文件不存在: {self.vhd_path}")
        if not self.name.strip():
            errs.append(f"[{self.vhd_path}] 挂载名称为空")
        if not self.mount_target.startswith("/"):
            errs.append(f"[{self.name}] 挂载目标必须是绝对路径(以 / 开头): {self.mount_target}")
        return errs


@dataclass
class AppConfig:
    distro: str = "Ubuntu"
    disks: list[DiskConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"distro": self.distro, "disks": [d.to_dict() for d in self.disks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        return cls(
            distro=str(d.get("distro", "Ubuntu")),
            disks=[DiskConfig.from_dict(x) for x in d.get("disks", [])],
        )


def config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "WslVhdMounter"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> AppConfig:
    p = config_path()
    if not p.exists():
        cfg = AppConfig()
        save(cfg)
        return cfg
    try:
        with open(p, encoding="utf-8") as fh:
            return AppConfig.from_dict(json.load(fh))
    except Exception as e:  # 配置损坏时兜底
        log.warn(f"读取配置失败({e})，使用默认配置")
        return AppConfig()


def save(cfg: AppConfig) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    tmp = config_path().with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path())
    log.info(f"配置已保存: {config_path()}")
