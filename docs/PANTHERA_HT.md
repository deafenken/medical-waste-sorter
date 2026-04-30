# Panthera-HT 机械臂适配档案

> 本项目最初按 G-code 3 轴桌面臂（GRBL/Marlin 风格）写的。当部署用 Panthera-HT
> 这种 6-DOF FDCAN 协作臂时，需要替换 `src/serial_arm.py` 整层。本文记录硬件参数、
> 适配计划、以及拿到 SDK 之前需要向商家问清楚的问题。

---

## 1. 硬件参数（从厂商规格表抄录）

### 整机

| 项 | 值 |
|---|---|
| 产品型号 | Panthera-HT |
| 站立尺寸 | 860 mm |
| 折叠尺寸 | 460 mm |
| 重量 | 4.35 kg |
| 工作电压 | 24 V |
| 最大负载 | 3.5 kg |
| 末端最大运动速度 | 0.8 m/s |
| 自由度 | 6 |
| 重复定位精度 | 0.1 mm |
| 通信方式 | **FDCAN** (CAN-FD) |
| 最大关节扭矩 (峰值) | 36 Nm |
| 操作系统支持 | Ubuntu 22.04 |

### 关节运动范围 (deg)

| 关节 | 范围 | 备注 |
|---|---|---|
| J1 (基座旋转) | -180° ~ 180° | 360° 无死区 |
| J2 (大臂俯仰) | 0° ~ 200° | **不能向下，注意安装方向** |
| J3 (小臂俯仰) | 0° ~ 230° | |
| J4 (腕部 1) | -90° ~ 90° | |
| J5 (腕部 2) | -90° ~ 90° | |
| J6 (末端旋转) | -180° ~ 180° | 360° 无死区 |

### 关节电机型号（厂商表）

按 base→tip 顺序，驱动 J1~J6：

```
HTDW-6056-36-NE     <- J1 (最强，承担整臂扭矩)
HTDW-5047-36-NE-JC  <- J2
HTDW-5047-36-NE     <- J3
HTDW-4438-30-NE     <- J4
HTDW-3536-32-NE     <- J5/J6 (腕部，更小更轻)
```

HTDW 系列大概率是无框电机 + 谐波/摆线减速器 + 集成驱动，每节挂在 CAN 总线
独立 ID 上。从规格"开源运动控制算法"判断可能基于 odrive / mit-cheetah-motor
体系，但需要确认。

### 出厂套件清单

```
机械臂 *1
通用盒子底板 *1（七路 CAN 板带外壳）       <- 总线集线 / 电源分配
USB 转 FDCAN 调试板 *1                     <- PC/Pi 接入口
G 型夹 *2                                  <- 安装夹具
220V 转 24V 电源适配器 *1
DC 母头转 XT60 母头 *1                     <- 适配电源接口
XT30 (2+2) *2                              <- 内部电源
末端电阻 *1                                <- CAN 总线终端电阻
杯头 M6*10 *4                              <- 机械臂底座/光学平板固定螺丝
USB 转 Type-C *1
主臂操作手柄 + D405 相机支架 *1            <- teleop leader + 相机机架
```

### 关键观察

- "**主臂操作手柄**"是 leader 臂，套件含遥操作功能 → 暗示这是 ALOHA 风格
  双臂遥操作平台的衍生品。本项目用不到 leader 臂，仅用 follower。
- "**D405 相机支架**"暗示厂商建议 Intel RealSense D405 安装在末端做手眼。
  本项目用户决定用普通 USB 摄像头（外置定装），不挂在臂上。
- "**末端电阻**" → CAN 总线末端必须装 120Ω 终端电阻防反射。第一次连不通先
  检查这一项。
- 24V 电源链路与 Pi 5V 完全独立，**不要从 Pi 取电**驱动机械臂。

---

## 2. SDK 调研结果（2026-04-30 拉取）

仓库：<https://github.com/HighTorque-Robotics/Panthera-HT_SDK>，MIT 协议。
主入口：`panthera_python/`，依赖 `panthera_cpp/` 编译产物。

### 2.1 已经能从公开资料确认的事

| 问题 | 答案 |
|---|---|
| SDK GitHub 链接 | <https://github.com/HighTorque-Robotics/Panthera-HT_SDK> |
| ARM64 支持 | ⚠️ **预编译 wheel 仅 x86_64**（`hightorque_robot-1.2.0-cp310-cp310-linux_x86_64.whl`）；Pi/RK3588 必须**源码编译** |
| 控制接口 | 关节角 + 笛卡尔（笛卡尔通过自带 IK 桥接） |
| 内置 IK | ✅ `inverse_kinematics(target_position, target_rotation, init_q)` |
| 内置 FK | ✅ `forward_kinematics(joint_angles)` 返回 dict（position/rotation/transform） |
| 通信底层 | 实际上**走 USB-CDC 串口**（`/dev/ttyACM*`），不是裸 socketcan，意味着**Pi 不需要 SocketCAN 内核模块** |
| 夹爪 API | `gripper_open()`、`gripper_close()`、`gripper_control()`、`gripper_control_MIT()` |
| 急停 | `set_stop()` 软停；硬件层无明确文档，**强烈建议外加红色急停按钮断 24V** |
| 控制模式 | 位置 / 速度 / 力矩 / 阻抗 / 重力补偿 / 主从遥操 |
| 轨迹规划 | 内置 `quintic_interpolation`、`septic_interpolation`（5 次/7 次多项式插值，C²/C³ 连续） |
| Python 版本 | 3.9 / 3.10 / 3.11 / 3.12 |
| 依赖 | `pin` (pinocchio)、`scipy>=1.9`、`pyyaml>=6.0`、`pybind11`（编译时） |
| 系统依赖 | `liblcm-dev`、`libyaml-cpp-dev`、`libserialport-dev`、`cmake`、`python3-dev` |
| 单位 | **米 + 弧度**（注意我们项目其它部分用 mm，wrapper 里要转） |
| 配置 | YAML 文件（`Leader.yaml` / `Follower.yaml` 含关节限位、力矩限位） |

### 2.2 SDK 关键 API（实测调研，以 SDK README 为准）

```python
from Panthera_lib import Panthera
import numpy as np

# 实例化
robot = Panthera()                       # 默认读 Leader.yaml
robot = Panthera("path/to/Follower.yaml")

# 状态读取（rad / m / Nm）
robot.get_current_pos()                  # -> ndarray [6,]  rad
robot.get_current_vel()                  # -> ndarray [6,]  rad/s
robot.get_current_torque()               # -> ndarray [6,]  Nm

# 关节空间控制
robot.moveJ(pos=[...], duration=5.0,
            iswait=True, tolerance=0.01, timeout=15.0)
robot.Joint_Pos_Vel(pos, vel, max_tqu=[10,10,10,5,5,5])

# IK / FK
fk = robot.forward_kinematics(joint_angles=current_q)
# fk = {'position': [x,y,z], 'rotation': R3x3, 'transform': T4x4, 'joint_angles': q}
q = robot.inverse_kinematics(target_position=[x,y,z],   # m
                             target_rotation=R3x3,        # 可省略
                             init_q=robot.get_current_pos(),
                             max_iter=1000, eps=1e-4)
# 返回 [6,] joint angles 或 None（无解）

# 夹爪
robot.gripper_open(vel=0.5, max_tqu=0.5)
robot.gripper_close(pos=0.0, vel=0.5, max_tqu=0.5)

# 急停 / 复位
robot.set_stop()
robot.set_reset()
robot.set_timeout(timeout_ms)
```

### 2.3 还没完全确认、要拿到设备亲手验证的几项

- 笛卡尔 `moveL` 直接接口的具体函数签名（README 提到 `6_moveL_pos_control.py`
  示例存在，但没列函数 signature，可能是 examples 内自己组合 IK + moveJ 实现的）
- 出厂坐标系基座原点的确切方向（X 是朝前还是朝侧？）
- 关节零位标定流程（开机自动？需要软件指令？）
- ARM64 源码编译的实测可行性

---

## 3. 软件适配计划（SDK 到手后做）

### 3.1 替换 serial_arm 模块

把现有 G-code 路径保留为 `src/arms/gcode.py`（参考 fallback），新增
`src/arms/panthera_ht.py`：

```python
# 期望接口（保持和 GCodeArm 一致，主流水线不用改）
class PantheraHTArm:
    def __init__(self, can_iface: str = "can0", ...): ...
    def home(self) -> bool: ...
    def move(self, x: float, y: float, z: float, ...) -> bool: ...
    def gripper_close(self) -> bool: ...
    def gripper_open(self) -> bool: ...
    def close(self) -> None: ...
```

config.yaml 加新分支：

```yaml
arm:
  backend: panthera_ht        # 新增；保留 gcode 作为兼容选项
  can_interface: can0         # 或 USB-FDCAN 设备名
  ...
```

### 3.2 工作空间重新规划

旧的 G-code 桌面臂工作半径约 ±170mm，三个桶位都在这里。Panthera-HT 站立
860mm，臂展约 523mm（折叠），工作半径要重测。

```yaml
arm:
  home_pos:    [0, 350, 400]      # 站立后中性位
  bins:
    pathological: [400, -200, 200]  # 单位 mm，相对基座；按你工作台实测填
    infectious:   [400, 200, 200]
    sharps:       [-300, 0, 200]
```

### 3.3 socketcan 配置

Pi 上启用 USB-FDCAN：

```bash
# 看 USB-FDCAN 调试板被识别成什么
dmesg | grep -i can
# 一般是 can0
sudo ip link set can0 up type can bitrate 1000000 dbitrate 5000000 fd on
ip -details link show can0
```

具体波特率以 SDK 文档为准，CAN-FD 标准波特率有 1M / 5M / 8M 几种。

### 3.4 急停 / 软停

6-DOF 臂带 36Nm 扭矩，**必须**有急停。最简：

- 硬件层：电源 24V 接红色急停按钮（断电）
- 软件层：`signal.signal(SIGINT, lambda *a: arm.stop())` 监听 Ctrl+C，先调
  SDK 的 `stop()` 释放伺服再退出
- main.py 的 vision_worker 死了 → arm_pipeline 已有检测会退出（之前修过这个
  bug）

---

## 4. 相机方案：Intel RealSense D405

最终选定 **Intel RealSense D405**（套件原配支架对应这款）。原始的深度路径
基本可以保留，只是相机后端从 Orbbec OpenNI2 换成 pyrealsense2。

### 4.1 D405 关键参数

| 项 | 值 | 影响 |
|---|---|---|
| 工作距离 | **7–50 cm** | 比 D435i 短得多；外置定装距离工作台 50cm 左右 |
| 接口 | USB 3.0 Type-C | **必须 USB 3.0**，USB 2.0 会失败 |
| 深度技术 | 双目 IR 主动结构光 | 室内光下精度好 |
| 默认 depth_scale | ≈ 0.0001 m/单位 | wrapper 已自动从设备读取并换 mm |
| 常用分辨率 | 1280×720 / 848×480 / 640×480 @30fps | 配置文件默认 848×480 平衡精度与帧率 |
| 内参 | 设备出厂校准 | 启动时自动 log，**首次跑后填回 config.yaml** |

### 4.2 安装 / 部署

`scripts/install_pi.sh` 默认会装 RealSense（除非 `REALSENSE_SDK=0` 跳过）：

1. 加 Intel apt 源 → `librealsense2-utils` + `librealsense2-dev` + udev 规则
2. `pip install pyrealsense2`（ARM64 也有 wheel）
3. `python -c "import pyrealsense2; ..."` 验证

如果 apt 源失败（比如 Bookworm ARM64 当前没仓库），脚本会 fallback 到只装
pip wheel——pyrealsense2 wheel 自带运行时 .so，多数情况能直接用。

### 4.3 装在哪：眼在末端 vs 固定俯视

D405 工作距离 7–50cm，**不能像 Astra Pro / D435i 那样固定在工作台上方
30+cm 俯视全场**。两个可行方案：

**方案 A：装在末端（厂商套件支架的设计）**
- 优点：天然手眼一体，标定就是机械臂自己往下看
- 缺点：每次抓取前必须先把臂移到"观察位"，每个目标要"先看再抓"，节拍变慢
- 实现：现有标定流程基本不用改；要扩展 `move()` 调用，让臂先到固定观察位、
  拍一帧、然后 IK 到目标

**方案 B：固定吊在工作台上方 ~50cm（仍勉强够 D405 远端工作距离）**
- 优点：跟原来 Astra Pro 部署方式一致，节拍快
- 缺点：D405 的远端 50cm 精度比近距明显下降；视野也偏窄（848×480 视场角约 87°，50cm 高时只能覆盖 ~95×55cm 工作区）
- 实现：完全沿用现有标定流程，只是把 `camera.backend` 改成 realsense

**推荐**：先做方案 B 把现有流程跑通，性能不够再切到方案 A 加观察位逻辑。

### 4.4 启动后第一件事——把内参填回配置

D405 启动时 `RealsenseCamera.__init__` 会打印这条 log：

```
RealSense color intrinsics (copy these into config.yaml):
    fx=430.1234 fy=430.5678 cx=423.9876 cy=240.4321  (848x480)
```

把这四个数填到 `config.yaml`：

```yaml
camera:
  intrinsics:
    fx: 430.1234
    fy: 430.5678
    cx: 423.9876
    cy: 240.4321
```

**不填回去**：手眼标定算出来的 `image_to_arm` 矩阵会带着内参误差，抓取
偏移会随距离增大。

### 4.5 配置示例（`config.yaml` 切到 RealSense）

```yaml
camera:
  backend: realsense
  width: 848
  height: 480
  fps: 30
  flip_color: false             # D405 一般不需要翻转
  intrinsics:                    # 首次启动后从日志填回
    fx: 430.0
    fy: 430.0
    cx: 424.0
    cy: 240.0
  depth_min_mm: 80               # D405 工作距离下限
  depth_max_mm: 600              # 工作距离上限（俯视方案下要根据相机高度调）
  align_to: color
  log_intrinsics: true
```

---

## 5. 当前项目状态 vs 你的硬件路线

```
                       你这台                  原通用方案              代码状态
                  ──────────────────────  ──────────────────────  ─────────────────
通信协议           FDCAN (走 /dev/ttyACM*)   G-code Serial            ✓ 已抽象 src/arms/
自由度             6 DOF                    3 DOF (X/Y/Z)            ✓ wrapper 包了 IK
末端               自带 1-DOF 夹爪           M3/M5 继电器 + 气泵       ✓ SDK 直接调
相机               Intel RealSense D405     Orbbec Astra Pro         ✓ 已抽象 src/cameras/
工作半径           ~523mm (臂展)             ±170mm (桌面臂)          ⚠ config 桶位需重测
SDK                Panthera-HT_SDK (MIT)    pyserial G-code          ⚠ 仅 x86_64 wheel，ARM64 源码编译
电源               24V 独立                 5V Pi 自带                ✓ 无影响
```

---

## 6. 建议你立刻做的 3 件事

1. **D405 拿到后插上 Pi**，跑 `python tools/depth_inspect.py`，把日志里
   打印的 `fx/fy/cx/cy` 填到 `config.yaml`（不填回，手眼标定会偏）
2. **拍一张控制盒（七路 CAN 板）的照片 + USB-FDCAN 调试板的照片**，确认
   连线方式以及它在 Pi 上识别为 `/dev/ttyACM*` 几号
3. **量好工作台**：D405 装在哪（末端 vs 固定俯视，§4.3）、三个分类桶
   摆在机械臂坐标系下哪个位置，量好后填 `config.yaml -> arm.bins.*`
