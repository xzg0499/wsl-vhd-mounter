# WSL VHD 挂载工具 (WslVhdMounter)

Windows 侧常驻托盘工具：管理 WSL2 自动挂载 VHD/VHDX 虚拟磁盘，挂载点默认 `/data`（GUI 可改）。

## 架构

```
┌──────── Windows 侧（Python + PySide6 托盘常驻）────────┐
│  状态面板 / 设置窗口 / 手动挂卸 / 钩子安装卸载 / 日志    │
└──────────────────────┬──────────────────────────────────┘
                       │ wsl.exe --mount --vhd <路径> --name <名>
                       │ wsl -d Ubuntu -u root -- mount --bind ...
                       ▼
┌──────── WSL 内部（systemd 服务 + 钩子脚本）─────────────┐
│  每次发行版启动：幂等挂载 VHD → bind 到 /data            │
└──────────────────────────────────────────────────────────┘
```

- 挂载：`wsl.exe --mount "C:\path\disk.vhdx" --vhd --name <名>`（VM 级挂载到 `/mnt/wsl/<名>`，WSL 3.x 默认；旧版 WSL 在 `/mnt/<名>`，工具两者自动探测）
- 绑定：发行版内 `mount --bind <实际挂载点> <目标目录>`（默认 `/data`）
- 卸载：`wsl.exe --unmount "C:\path\disk.vhdx"`（**顶层命令**，不是 `--mount` 子参数）
- 配置：`%LOCALAPPDATA%\WslVhdMounter\config.json`，GUI 与 WSL 钩子共享（钩子经 `/mnt/c` 读取）

## 开发调试

```bash
# 首次：创建 venv（Windows 下注意用原生路径，中文目录别用 MSYS 路径建 venv）
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt

# 运行（托盘常驻）
venv/Scripts/python.exe -m wsl_vhd_mounter

# 测试
venv/Scripts/python.exe tests/smoke_test.py        # 核心逻辑（真实调用 wsl.exe）
venv/Scripts/python.exe tests/install_test.py      # 钩子安装到发行版
QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe tests/gui_smoke.py  # GUI 冒烟
```

## GUI 使用

1. 运行后常驻托盘（图标"V"），双击打开状态面板
2. 设置 → 添加 VHD → 填路径/挂载名/目标目录（默认 `/data`）→ 保存
3. 状态面板 → 「安装钩子」：把 systemd 服务写入 WSL 发行版
4. 重启 WSL 生效：`wsl --shutdown` 后重新打开终端，VHD 自动挂到 `/data`

## 配置字段

| 字段 | 说明 |
|---|---|
| `distro` | 目标发行版（默认 Ubuntu） |
| `vhd_path` | VHD/VHDX 文件绝对路径 |
| `name` | 挂载名（`/mnt/<name>`），默认 `data` |
| `mount_target` | bind 目标目录，默认 `/data` |
| `partition` | 分区号，`0` = 整盘自动 |
| `readonly` | 只读挂载 |
| `bare_fallback` | 整盘挂载失败时尝试 `--bare` + 手动 mount |
| `enabled` | 是否参与自动挂载 |

## 钩子原理

- 安装器往发行版写入 `/usr/local/bin/wsl-vhd-hook.py` 与 systemd unit `wsl-vhd-mount.service`
- 同时确保 `/etc/wsl.conf` 的 `[boot]` 段含 `systemd=true`（幂等合并，保留用户原有内容）
- 每次发行版启动，systemd 拉起钩子：等待 `/mnt/c` 就绪 → 读配置 → 幂等挂载每张盘 → bind 到目标目录
- 钩子日志：`/var/log/wsl-vhd-mounter.log`；Windows 侧日志：`%LOCALAPPDATA%\WslVhdMounter\wsl-vhd-mounter.log`

## 已知问题与限制

- **WSL 已知 bug**：`wsl.exe --unmount` 对**路径含空格**的 VHD 无法卸载（microsoft/WSL#11451）。规避：路径避免空格，或 `wsl --shutdown` 强制卸载
- **VHDX 结构适配待实测**：工具已实现「有分区表（`--partition N`）」「无分区表（`--bare` fallback + lsblk 探测设备）」两条路径，但需要真实 VHDX 文件校准（当前项目尚无 VHD 文件）
- **首次安装**：若发行版当前未运行 systemd，钩子经 symlink 预启用，`wsl --shutdown` 后自动生效
- 挂载不跨 `wsl --shutdown` 持久：这是 WSL 机制决定的，钩子的意义就是每次启动自动重挂

## 打包成 exe（免安装，支持开机自启）

```bash
venv/Scripts/python.exe -m pip install pyinstaller
venv/Scripts/pyinstaller.exe --noconfirm --onefile --windowed \
  --name WslVhdMounter --add-data "wsl_guest;wsl_guest" \
  wsl-vhd-mounter.py
```

`dist/WslVhdMounter.exe` 即最终工具：

- **免安装**：单文件，拷到任何目录双击即用（`wsl_guest` 资源已内嵌）
- **开机自启**：设置窗口勾选「开机自动启动（常驻托盘）」→ 写 HKCU Run 注册表（免管理员）
  - exe 路径写在注册表里，**移动 exe 后需重新勾选一次**刷新路径
- 开机后托盘常驻；WSL 每次启动由发行版内 systemd 钩子自动挂载 VHD，托盘负责配置/状态/手动挂卸
