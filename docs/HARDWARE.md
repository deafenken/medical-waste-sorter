# 硬件档案 · Hardware Inventory

> 本项目实际部署所用硬件的**完整记录**——包括型号、参数、接线、网络配置、
> 软件环境。所有别的文档（BOM 通用方案、PANTHERA_HT 协议适配、HAILO 部署）
> 是从功能角度切的横截面，本文是从"实物"角度的纵切面。
>
> 出问题时第一份要打开的是它。

---

## 1. 计算终端：Raspberry Pi 5 16GB

### 1.1 主板参数

| 项 | 值 |
|---|---|
| 型号 | Raspberry Pi 5 |
| 内存 | **16GB** LPDDR4X |
| SoC | BCM2712（4×Cortex-A76 @ 2.4GHz） |
| 架构 | aarch64（ARM64） |
| GPU | VideoCore VII |
| 接口 | USB-C 电源、双 micro-HDMI、2× USB 3.0 (蓝口)、2× USB 2.0 (黑口)、千兆以太网、PCIe 2.0 x1 (M.2) |

### 1.2 USB 端口分配（**重要，别接错**）

```
正面看 Pi 5（电源口朝下）：
┌────────────────────────────────┐
│  micro-HDMI 0   micro-HDMI 1   │ ← 接显示器
│  USB-C (电源)                   │
│                                │
│  ⬛ 黑口  ⬛ 黑口   ← USB 2.0   │ ← Panthera USB-FDCAN 调试板 / 键盘
│  🔵 蓝口  🔵 蓝口   ← USB 3.0   │ ← D405 必须插这里
│                                │
│  🌐 RJ45 (千兆以太网)            │ ← 备用
└────────────────────────────────┘
```

⚠️ **D405 必须插 USB 3.0 蓝口**，否则 `pipeline.start()` 会失败。

### 1.3 散热

满载 YOLO + RealSense 双流 + 多进程会持续 4 核满载。**没主动风扇会触发降频**，FPS 直接腰斩。

```bash
vcgencmd measure_temp                        # 满载稳定 < 70°C OK；> 80°C 已降频
```

### 1.4 系统

| 项 | 值 |
|---|---|
| OS | **Ubuntu 24.04.4 LTS (noble) ARM64** |
| Python | 3.11.15 (uv 管理；系统 Python 是 3.12.3 但项目锁 3.11) |
| 包管理 | uv（不是 pip + venv） |
| 网络栈 | NetworkManager (`nmcli` 命令) |
| 主机名 | `selabpi5` |
| 用户名 | `winbeau` |

> ⚠️ **不是 Raspberry Pi OS Bookworm**：实际部署用的是 Ubuntu noble。
> 影响：Intel librealsense 的 apt 源**没 noble 包**，所以 D405 必须源码
> 编译 librealsense（脚本 `REALSENSE_FROM_SOURCE=1` 自动处理）。

---

## 2. 视觉传感器：Intel RealSense D405

| 项 | 值 |
|---|---|
| 型号 | Intel RealSense **D405** |
| 工作距离 | **7–50 cm**（近距） |
| 最佳精度区 | 12-30 cm |
| 接口 | USB 3.0 Type-C |
| 深度技术 | 双目 IR 主动结构光 |
| 默认 depth_scale | ≈ 0.0001 m/单位（开机时由 SDK 读出） |
| 推荐分辨率 | 1280×720 / **848×480** / 640×480，全部 @30fps |
| 当前选用 | 848×480 @30 fps |
| 内参（典型，**首次启动需校对**） | fx≈430, fy≈430, cx≈424, cy≈240 |
| Python SDK | `pyrealsense2` |

**首次启动需校对内参**：`RealsenseCamera.__init__` 会在日志里打印设备真实内参。把 `fx/fy/cx/cy` 填回 `config.yaml -> camera.intrinsics`，否则手眼标定会偏。

详见 [PANTHERA_HT.md §4](PANTHERA_HT.md#4-相机方案intel-realsense-d405)。

---

## 3. 机械臂：Panthera-HT 6-DOF

### 3.1 整机参数

| 项 | 值 |
|---|---|
| 产品型号 | Panthera-HT |
| 自由度 | 6 |
| 站立尺寸 | 860 mm |
| 折叠尺寸 | 460 mm |
| 重量 | 4.35 kg |
| 最大负载 | 3.5 kg |
| 末端最大速度 | 0.8 m/s |
| 重复定位精度 | 0.1 mm |
| 最大关节扭矩（峰值） | 36 Nm |
| 工作电压 | **24 V** |
| 通信方式 | FDCAN（**实际经 USB-FDCAN 调试板转 `/dev/ttyACM*`**） |
| 控制 SDK | [HighTorque-Robotics/Panthera-HT_SDK](https://github.com/HighTorque-Robotics/Panthera-HT_SDK)（MIT） |
| SDK 单位 | **米 + 弧度**（wrapper 自动转 mm） |
| 末端工具 | 自带 1-DOF 夹爪 |

### 3.2 关节运动范围

| 关节 | 范围 | 说明 |
|---|---|---|
| J1（基座旋转） | -180° ~ 180° | 360° 无死区 |
| J2（大臂俯仰） | **0° ~ 200°** | ⚠️ 不能向下，注意安装方向 |
| J3（小臂俯仰） | 0° ~ 230° | |
| J4（腕部 1） | -90° ~ 90° | |
| J5（腕部 2） | -90° ~ 90° | |
| J6（末端旋转） | -180° ~ 180° | 360° 无死区 |

### 3.3 关节电机型号（base → tip）

```
HTDW-6056-36-NE       <- J1 (最强，承担整臂扭矩)
HTDW-5047-36-NE-JC    <- J2
HTDW-5047-36-NE       <- J3
HTDW-4438-30-NE       <- J4
HTDW-3536-32-NE       <- J5/J6 (腕部，更小)
```

### 3.4 套件清单

```
机械臂 *1
通用盒子底板 *1（七路 CAN 板带外壳）         <- 总线集线 / 电源分配
USB 转 FDCAN 调试板 *1                       <- PC/Pi 接入口
G 型夹 *2                                    <- 安装夹具
220V 转 24V 电源适配器 *1
DC 母头转 XT60 母头 *1                       <- 适配电源接口
XT30 (2+2) *2                                <- 内部电源
末端电阻 *1                                  <- ⚠️ CAN 总线必装 120Ω 终端电阻
杯头 M6*10 *4                                <- 底座固定螺丝
USB 转 Type-C *1
主臂操作手柄 + D405 相机支架 *1              <- teleop leader + 相机机架
```

### 3.5 SDK 关键接口

```python
from Panthera_lib import Panthera

robot = Panthera()                                   # 默认读 Leader.yaml
robot.get_current_pos()                              # ndarray [6,] rad
robot.moveJ(pos=[...], duration=5.0, iswait=True)
robot.inverse_kinematics(target_position=[x,y,z],    # 米
                         target_rotation=R3x3,
                         init_q=robot.get_current_pos())
robot.gripper_open(vel=0.5, max_tqu=0.5)
robot.gripper_close(pos=0.0, vel=0.5, max_tqu=0.5)
robot.set_stop()                                     # 软急停
```

### 3.6 平台支持现状

| 项 | 状态 |
|---|---|
| Python 版本 | 3.9 / 3.10 / 3.11 / 3.12 |
| 预编译 wheel | **仅 x86_64** |
| ARM64（Pi 5） | 必须**源码编译**（`PANTHERA_SDK=1 ./scripts/install_pi.sh` 自动尝试） |

---

## 4. AI 加速器：Hailo-8 26 TOPS（部署目标）

| 项 | 值 |
|---|---|
| 型号 | Hailo-8 |
| 算力 | **26 TOPS**（INT8） |
| 接口 | M.2 Key M / Key B (PCIe Gen2/3 x1) |
| 实测性能 | YOLOv8n @ 640×640 ≈ **30+ FPS** |
| 运行时 | HailoRT（闭源，需注册下载） |
| Python 包 | `hailo_platform` |
| 模型格式 | `.hef`（编译于 x86_64 PC） |

**HailoRT 不能 pip 装**——必须从 [hailo.ai/developer-zone](https://hailo.ai/developer-zone/) 注册下载 `.deb` (ARM64) + `.whl` (cp311 aarch64)，scp 到 Pi 的 `~/hailo/` 目录后 `HAILO_SDK=1 ./scripts/install_pi.sh`。

详见 [HAILO.md](HAILO.md)。

---

## 5. 末端 / 标定附件

| 项 | 规格 |
|---|---|
| 夹爪 | Panthera 自带 1-DOF |
| ArUco 标定卡 | **5cm × 5cm**，DICT_7X7_100 字典 |
| 工作台 | 深色平面，**不要白纸**（深度图过曝） |
| 分类垃圾桶 | 黄色（感染性）、红色（病理性）、利器盒（损伤性） |
| 急停按钮 | 串联在 24V 电源链路上（强烈建议自加） |

---

## 6. 电源链路

```
墙插 220V AC ─→ [220V→24V 适配器] ─→ DC 母头 ─→ XT60 转接 ─→ [七路 CAN 板]
                                                                  │
                                                                  ├→ 机械臂主线
                                                                  └→ Panthera 夹爪

(可选) 24V 急停按钮串在适配器输出端

Pi 5 独立供电：USB-C PD 27W 充电器（不要从机械臂供电链路取电）
```

⚠️ **24V 链路必须独立于 Pi 5 的 5V**——机械臂启动电流大，会拉低 Pi 电压触发 SoC 降频或重启。

---

## 7. 网络配置（实验室）

### 7.1 当前拓扑

```
[校园主网] ─── WAN ─── [实验室路由器]
                         │
                         ├── Wi-Fi (192.168.3.0/24)
                         │     ├── Mac (192.168.3.18)
                         │     └── Pi (192.168.3.87)  ← selabpi5.local
                         │
                         └── 有线 LAN 口 (192.168.137.0/24)
                               (跟 Wi-Fi 不同网段，AP 隔离)
```

**关键**：实验室路由器把 Wi-Fi 和有线放在不同 VLAN/不同 DHCP 池。Pi 走 Wi-Fi（192.168.3.x）才能和 Mac 互通；走有线（192.168.137.x）则隔离。

### 7.2 Pi 网络设置

| 项 | 值 |
|---|---|
| 主连接 | Wi-Fi（实验室）|
| 静态/DHCP | DHCP |
| Pi 当前 IP | 192.168.3.87（DHCP 分配，**可能变化**） |
| 主机名 | `selabpi5`（→ `selabpi5.local` via mDNS） |
| 优先级配置 | `connection.autoconnect-priority = 100`（Wi-Fi 永远赢有线） |
| 开机自连 | `connection.autoconnect = yes` |

### 7.3 Mac 端 SSH 配置

`~/.ssh/config` 永久绕过 V2rayN 代理（局域网设备直连）：

```
Host selabpi5 selabpi5.local pi
    User winbeau
    HostName selabpi5.local
    ProxyCommand none
    StrictHostKeyChecking accept-new

Host 192.168.3.* 192.168.137.*
    ProxyCommand none
```

### 7.4 V2rayN 代理（Mac 上）

| 端口 | 协议 |
|---|---|
| 10808 | SOCKS5（默认开） |
| 10809 | HTTP（**当前未开**） |

**已知坑**：V2rayN 在 Mac 是 TUN 模式，会拦截 SSH 到 LAN 设备。已通过 `~/.ssh/config` + V2rayN 路由规则 `geoip:private → direct` 解决。

### 7.5 镜像配置（中国大陆访问 GitHub / PyPI）

**Mac 上**（git push 需要走代理）：

```bash
git config --global http.proxy socks5://127.0.0.1:10808
git config --global https.proxy socks5://127.0.0.1:10808
```

**Pi 上**（git clone github 走 ghfast.top 镜像，pypi 走清华源）：

```bash
git config --global url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"

# pip 清华源（pip 直接生效；uv 不读 pip.conf，要单独配 env，见下）
mkdir -p ~/.config/pip
cat > ~/.config/pip/pip.conf <<'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF

# uv 必须额外两个环境变量（写进 ~/.bashrc 永久生效）
# 1. uv 自己的 PyPI 源（不继承 pip.conf）
# 2. uv venv --python 3.11 时下载 standalone Python 走 ghfast.top
#    （uv 直接 HTTP 拉 github releases，不走 git，所以 insteadOf 无效）
cat >> ~/.bashrc <<'EOF'
export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export UV_PYTHON_INSTALL_MIRROR="https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"
EOF
source ~/.bashrc
```

> ⚠️ **不配第二条会卡 10+ 分钟**：`uv venv --python 3.11` 在背地里下载 ~30MB 的 Python
> standalone 包，直连 github.com 在国内基本拉不动，且 uv 不打印任何进度，看上去像死了。
> `scripts/install_pi.sh` 默认会自动 export 这两个变量（设 `NO_CN_MIRROR=1` 可跳过）。

---

## 8. 串口设备清单

部署时各 USB 设备在 Pi 上的设备节点：

| 设备 | 接 Pi 哪个口 | 节点名 | 备注 |
|---|---|---|---|
| Intel RealSense D405 | **USB 3.0 蓝口** | n/a（用 librealsense2 直接打开） | USB-3 必须 |
| Panthera USB-FDCAN 调试板 | USB 2.0 黑口（任选） | `/dev/ttyACM0` 或 `/dev/ttyACM1` | CDC 串口 |
| 键盘（调试用） | USB 2.0 黑口 | n/a | |
| (备用) USB-TTL 调试 | 任选 | `/dev/ttyUSB0`（CH340） | 调机械臂用 |

查实际节点：

```bash
ls /dev/ttyACM* /dev/ttyUSB*
dmesg | grep -i tty | tail
lsusb -t                              # 看 USB 拓扑 + 速率（5000M=USB3, 480M=USB2）
```

---

## 9. 工作空间几何（运行时填）

| 项 | 当前值 | 备注 |
|---|---|---|
| 相机安装方式 | (待定，方案 B：固定俯视 50cm) | 方案 A：装在末端做手眼 |
| 工作台中心（机械臂坐标） | `[0, 350, 400]` mm（占位） | 部署时实测填 |
| 病理桶位置 | `[400, -200, 200]` mm（占位） | |
| 感染桶位置 | `[400, 200, 200]` mm（占位） | |
| 利器盒位置 | `[-300, 0, 200]` mm（占位） | |
| TCP→ArUco 偏移 | `[0, 35, 0]` mm（默认） | 标定卡贴在末端时实测 |
| 抓取下压量 `pick_offset_z` | -25 mm（默认） | 抓不到调更负 |
| 接近高度 `approach_offset_z` | +80 mm（默认） | 防撞起点 |

✏️ **这一节随部署进度更新**。

---

## 10. 软件后端选择（当前）

| 后端 | 当前选择 | 备选 |
|---|---|---|
| `arm.backend` | `panthera_ht` | `gcode`（fallback） |
| `camera.backend` | `realsense` | `orbbec` / `usb` |
| `detector.backend` | `ncnn`（CPU fallback） | `hailo`（拿到设备后切） |

---

## 11. 已知踩坑速查

| 现象 | 原因 | 解决 |
|---|---|---|
| `ssh selabpi5` 报 `Connection closed by 127.0.0.1 port 10808` | V2rayN TUN 模式拦截 | 退出 V2rayN 或加 `domain:local→direct` 规则 |
| `git clone` 卡 `Recv failure: Connection reset by peer` | github.com 被墙 | Mac 上配 git 走 SOCKS5；Pi 上配 ghfast.top 镜像 |
| `git clone` 卡 `192.168.137.1:10808` 超时 | Pi 上有遗留 git proxy 配置 | `git config --global --unset http.proxy https.proxy` |
| Pi 拿到 `192.168.137.x` IP，跟 Mac 不通 | Pi 走有线，落到不同 VLAN | Pi 改走实验室 Wi-Fi |
| `command not found: pip` | Bookworm 默认无系统 pip | 走 uv（`./scripts/install_pi.sh` 装好） |
| 抓 `192.168.137.1:10808` SSH 超时 | 旧的 SSH `~/.ssh/config` 有 ProxyCommand | `grep -i proxy ~/.ssh/config` |
| `uv venv --python 3.11` 静默卡 10+ 分钟，`ps` 看进程还在但没输出 | uv 在背地里从 `github.com/astral-sh/python-build-standalone` 直链下载 Python，国内基本拉不动；`pip.conf` / `git insteadOf` 都救不了它 | export `UV_PYTHON_INSTALL_MIRROR` 走 ghfast.top + `UV_INDEX_URL` 走清华，详见 §7.5；`scripts/install_pi.sh` 已默认 export，可设 `NO_CN_MIRROR=1` 关闭 |
| `import pyrealsense2` → `ModuleNotFoundError`，`rs-enumerate-devices not found` | Ubuntu noble + aarch64 上 PyPI **没** `pyrealsense2` wheel，且 Intel apt 源**没有 noble 的包**——脚本旧版本两步都静默吞错 | 用 `REALSENSE_FROM_SOURCE=1 ./scripts/install_pi.sh` 源码编译 librealsense（30-45 分钟）。脚本会自动把 `pyrealsense2` 软链进 venv |

---

## 12. 维护这份文档的规则

- **加新设备**或换硬件时立刻更新对应章节
- §9 工作空间几何在每次重新标定后填实测值
- §7.2 Pi IP 如果改成静态了，把"DHCP"改成静态 IP
- §10 后端切换（如切到 Hailo）后更新当前选择
- 新踩的坑加到 §11
