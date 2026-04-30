# 医疗废弃物分拣机械臂项目 —— BOM清单 + 树莓派部署方案

> 基于 robot-arm2/ 现有代码（YOLOv8 + Orbbec 深度相机 + G-code 串口机械臂）
> 终端：Raspberry Pi
> 输出日期：2026-04-30

---

## ⚠️ 实际部署偏离原始假设（务必先读这一段）

本文档下面写的是**通用部署方案**，仍保留作为别人 fork 后的参考。但本项目维护者
实际使用的硬件路线已收敛到下面这套，与原始假设差别较大：

| 项 | 通用方案推荐 | 实际选用 | 影响 |
|---|---|---|---|
| 机械臂 | GRBL/Marlin 桌面臂（G-code over USB-Serial） | **Panthera-HT 6-DOF**（FDCAN, 厂商 SDK） | 整个 arm 模块需替换 |
| 相机 | Orbbec Astra Pro Plus (RGB-D) | **普通 USB 摄像头**（仅彩色，无深度） | 标定从 3D 仿射降级为 2D 单应 |
| 末端 | 真空泵 + 继电器 + 吸盘 | **Panthera 自带 1-DOF 夹爪** | 不需要 M3/M5 继电器电路 |
| 工作半径 | ±170mm 桌面 | ~523mm 臂展，工作半径需重测 | 桶位坐标重新规划 |
| 终端 | Pi 5 8GB | Pi 5 8GB（**待确认 SDK 是否支持 ARM64**） | 若 SDK 仅 x86 → 需换 mini PC |

详见 [PANTHERA_HT.md](PANTHERA_HT.md) 完整适配档案与开放问题清单。

下面的"通用方案"对其他想从零搭一套的人仍然有效。

---

## 一、项目架构总览

```
┌─────────────────────────────────────────────────────────┐
│                 Raspberry Pi 5 (终端大脑)                │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐   │
│  │ OpenNI2     │   │ YOLOv8-NCNN │   │ pyserial     │   │
│  │ 深度相机驱动 │──▶│ 目标检测     │──▶│ 发G-code     │   │
│  └─────────────┘   └─────────────┘   └──────────────┘   │
│         ▲                                    │          │
└─────────┼────────────────────────────────────┼──────────┘
          │ USB                                │ USB-TTL
          │                                    │
   ┌──────┴──────┐                       ┌─────┴──────┐
   │ Astra Pro   │                       │ 机械臂控制板│
   │ 深度相机     │                       │ (GRBL/Marlin)│
   └─────────────┘                       └─────┬──────┘
                                               │
                                       ┌───────┴───────┐
                                       │  3-4轴机械臂   │
                                       │  + 夹爪/吸盘   │
                                       └───────────────┘
                                               │
                                       ┌───────┴───────┐
                                       │ 3 个分类垃圾桶 │
                                       │ 病理/感染/损伤  │
                                       └───────────────┘
```

---

## 二、完整 BOM 硬件清单

### 1. 计算终端

| 名称 | 型号推荐 | 备注 | 参考价（人民币） |
|---|---|---|---|
| 主板 | **Raspberry Pi 5 8GB** | YOLOv8 推理强烈推荐 8GB；4GB 也能跑但容易OOM | 700–800 |
| 散热 | Pi 5 主动散热风扇 | 满载会热降频 | 50 |
| 电源 | 官方 27W USB-C PD 电源 | Pi 5 必须用 PD 电源 | 80 |
| TF 卡 | 64GB A2 U3 (SanDisk Extreme) | 模型文件 + Ubuntu/Raspbian 系统 | 80 |
| AI 加速器 (强烈建议) | **Hailo-8L M.2 模块 + Pi 5 AI Hat** 或 **Coral USB Accelerator** | 不加速，CPU 跑 YOLOv8n 大概 2–4 FPS；加 Hailo 可达 30+ FPS | Hailo Hat 约 600；Coral USB 约 500 |

### 2. 视觉传感器（你还没买）

你代码里的内参 `fx=fy=524.38, cx=324.77, cy=212.35`，分辨率 640×400，吻合 **Orbbec Astra Pro / Astra+** 系列。建议：

| 型号 | 优点 | 缺点 |
|---|---|---|
| **Astra Pro Plus** (推荐) | 内参与你代码完全匹配，OpenNI2 ARM64 SDK 官方支持 | 体积稍大 |
| Astra Mini S | 体积小、近距精度好 | 相机内参不同，要重新标定 |
| Gemini 2 / Gemini 335 | 新款双目结构光，精度更高 | 用 Orbbec SDK 而非 OpenNI2，需改代码 |

**建议直接买 Astra Pro Plus**，代码基本不用改相机部分。参考价 1500–1800。

### 3. 机械臂（你已有，但不确定怎么连）

> 你代码里用的是 **G-code 协议**（`G1 X Y Z`、`G28`、`M3` 关夹爪 / `M5` 开夹爪），坐标范围±170mm，这意味着控制板**很可能是基于 GRBL 或 Marlin 固件**，常见于：
> - 越疆 EleBot / EleArm 入门款
> - LewanSoul xArm 系列里走 G-code 的型号
> - 国产 3D 打印改装的 SCARA 机械臂
> - 一些桌面级激光雕刻臂的扩展

#### 如何识别你已有的机械臂

按这个清单挨个对照，就能知道下面怎么接：

1. **看控制板上的芯片**：
   - 如果是 **Arduino Uno / MEGA + GRBL Shield** → GRBL 固件，串口 115200 8N1，G-code 标准
   - 如果是 **Marlin 主板**（如 Ramps 1.4、SKR mini）→ Marlin 固件，串口 115200 或 250000，支持 G-code
   - 如果是 **Dobot 自家板** → 用 Dobot SDK，**不是 G-code**（你这套代码不能直接用）
   - 如果是 **STM32 自定义板** → 看厂商文档

2. **看 USB 接口**：
   - CH340 芯片 → Linux 下 `/dev/ttyUSB0`
   - FTDI FT232 → `/dev/ttyUSB0`
   - ATmega16U2（原版 Arduino Uno）→ `/dev/ttyACM0`
   - STM32 原生 USB → `/dev/ttyACM0`

3. **波特率**通常是 **115200**（你代码里也是这个），少数 Marlin 是 250000。

#### 第一次接通测试方法

把机械臂 USB 插到电脑（先别用 Pi，用 Windows 笔记本更直观），然后：

```python
import serial, time
ser = serial.Serial("COM?", 115200, timeout=2)  # COM号查设备管理器
time.sleep(2)
ser.write(b"G28\r")          # 回零
print(ser.readlines())
ser.write(b"G1 X0 Y150 Z50 F1000\r")  # 移动到中心点
print(ser.readlines())
```

如果机械臂动了 → 你的协议就是对的，代码可以直接用。
如果不动、报错或没反应 → 协议不是 G-code，要联系厂家拿 SDK。

#### 如果发现不是 G-code 怎么办

最常见的替代是：
- **Dobot Magician/M1**：用 `pydobot` 或 `Dobot DLL`，需要把 `port_test.py` 整个换掉
- **MyCobot 280 / 320**：用 `pymycobot` 库
- **xArm（UFactory）**：用 `xArm-Python-SDK`

这种情况告诉我具体型号，我帮你改代码。

### 4. 夹爪 / 末端执行器

你代码里 `M3` / `M5` 是 GRBL 主轴控制指令（通常用来切换继电器开关）。这意味着你的夹爪可能是：

| 类型 | 控制方式 | 适合场景 |
|---|---|---|
| **气动吸盘** + 电磁阀 (推荐) | M3 开/M5 关 继电器控气泵 | 抓塑料瓶、纱布、口罩这些轻质物 |
| **舵机平行夹爪** | 通常要 PWM；如果是 M3/M5 说明是开关型 | 抓注射器更稳 |
| **电磁铁** | M3/M5 开关 | 只能抓铁器，**不适合医疗废弃物** |

**建议**：用气动吸盘 + 一个小型真空泵（直流 12V，淘宝约 80–150 元）+ 5V 继电器模块（10 元），用机械臂控制板上的 spindle 输出口（M3/M5 引脚）触发继电器。

### 5. 其他配件

| 名称 | 数量 | 备注 |
|---|---|---|
| USB 数据线 | 2 | 连相机、连机械臂 |
| USB-TTL 转换头（CH340） | 1（备用） | 万一控制板没自带 USB |
| 5V 继电器模块 | 1 | M3/M5 控制气泵 |
| 12V 直流电源 | 1 | 给气泵供电（**不要从 Pi 取电**） |
| 真空吸盘 + 软管 | 1套 | 末端 |
| ArUco 5×5 标定板 | 1张 | 激光打印或铜版纸打印贴硬纸板，**尺寸严格 5cm**（代码里 `marker_size=5`）|
| 三色分类垃圾桶 | 3个 | 黄色（感染性）、红色（病理性）、利器盒（损伤性） |
| 工作台 | 1张 | 50×80cm 平面，深色无反光 |
| 相机支架 | 1个 | 推荐俯视 30–40cm 高度 |

---

## 三、树莓派系统部署步骤

### Step 1：烧录系统

- 推荐 **Raspberry Pi OS (64-bit) Bookworm** 或 **Ubuntu 24.04 ARM64**
- 用 Raspberry Pi Imager 烧录到 TF 卡
- 烧录时启用 SSH，设置好 Wi-Fi

### Step 2：基础环境

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git cmake build-essential \
    libopencv-dev python3-opencv libusb-1.0-0-dev \
    udev v4l-utils

# 创建项目虚拟环境
python3 -m venv ~/venv-arm
source ~/venv-arm/bin/activate
pip install --upgrade pip

# Python 依赖（先装这些）
pip install numpy opencv-python pyserial primesense
```

### Step 3：编译 Orbbec OpenNI2 ARM64 驱动

这是树莓派部署最容易卡住的一步：

```bash
# 1. 从奥比中光官网下载 OpenNI Linux ARM64 SDK
#    https://www.orbbec.com/developers/openni-sdk/
#    或 GitHub: https://github.com/orbbec/OpenNI2

cd ~
git clone https://github.com/orbbec/OpenNI2.git
cd OpenNI2

# 2. 编译
make PLATFORM=Arm64 -j4

# 3. 编译产物在 Bin/Arm64-Release/
#    把 OpenNI2/ 子目录里的 .so 文件路径记下来

# 4. udev 规则（让非 root 用户能访问相机）
sudo cp Packaging/Linux/primesense-usb.rules /etc/udev/rules.d/557-primesense-usb.rules
sudo udevadm control --reload-rules

# 5. 把相机插上，测试
cd Bin/Arm64-Release
./SimpleViewer
```

成功的话能看到深度图。**记下编译产物路径**，等下要在代码里替换 `redist_path`。

### Step 4：安装 YOLOv8（用 NCNN 加速版）

```bash
pip install ultralytics
# 转换模型
cd ~/robot-arm2
python -c "from ultralytics import YOLO; YOLO('best.pt').export(format='ncnn')"
# 会生成 best_ncnn_model/ 目录
```

代码里加载方式改成：
```python
model = YOLO('best_ncnn_model')   # 不再加载 .pt
```

CPU 推理速度：Pi 5 + NCNN 大概能跑 **8–12 FPS**，加 Hailo 能到 30+ FPS。

### Step 5：串口权限

```bash
# 把当前用户加到 dialout 组（访问串口必须）
sudo usermod -aG dialout $USER
# 注销重登
```

插上机械臂的 USB 后：
```bash
ls /dev/ttyUSB* /dev/ttyACM*
# 一般会出现 /dev/ttyUSB0 或 /dev/ttyACM0
```

---

## 四、代码修改清单

下面这些地方必须改，否则在 Pi 上跑不起来：

| 文件 | 行号 | 原内容 | 改成 |
|---|---|---|---|
| `orbbec_init.py` | 调用方 | 不变 | OK |
| `Getdepthvalue.py` | 28 | `redist_path = "F:\\study-python\\..."` | `redist_path = "/home/pi/OpenNI2/Bin/Arm64-Release/OpenNI2"`（你 Step 3 编出来的实际路径） |
| `yolov8_test.py` | 30 | 同上 Windows 路径 | 同上 |
| `yolov8_test.py` | 29 | `model = YOLO('best.pt')` | `model = YOLO('best_ncnn_model')` |
| `yolov8_test.py` | 236 | `serial.Serial("COM5", ...)` | `serial.Serial("/dev/ttyUSB0", baudrate=115200, timeout=2)` |
| `calibration_test.py` | 31 | Windows redist_path | Linux 路径 |
| `calibration_test.py` | 343 | `Ser("COM5")` | `Ser("/dev/ttyUSB0")` |
| 图像窗口 | 多处 `cv2.imshow` | 不变（如有显示器） | 如果 Pi 跑 headless（无显示器），把 `cv2.imshow`、`cv2.waitKey` 换成保存图片或注释掉 |

另外建议加几个**鲁棒性补丁**：

1. **YOLO 推理失败保护**：当 `result_list` 为空、`max_score_bbox[0]==0` 时，第 116–117 行会去查 `img[0,0]`（深度图原点）算 xyz，等于把 (0,0) 误当目标。要加 `if max_score_bbox[0] > 0` 判断。
2. **深度无效保护**：Astra 在物体太近 (<30cm) 或太远 (>2m) 时返回 0，转出来的 z=0 会让臂撞向桌面。在 `convert_depth_to_xyz` 后加 `if z < 100 or z > 800: continue`。
3. **状态显示 bug**：`yolov8_test.py` 第 134 行 `if robot_status == 0` 应该是 `robot_status.value == 0`，否则永远走红色分支。
4. **退出键**：`Getdepthvalue.py` 第 105 行 `if int(key) == "q"` 是 bug，`"q"` 不能 int 化，应该是 `if key == ord("q")`。

---

## 五、手眼标定流程（calibration_test.py）

这是项目跑通的关键步骤，第一次必须做：

### 准备

1. 打印一张 **5cm × 5cm 的 ArUco 7×7 字典 ID=0 标定板**（代码用的是 `DICT_7X7_100`），贴在硬纸板上。
2. 把标定板**粘在机械臂末端**（吸盘正下方），让 ArUco 中心和吸盘中心重合（如果有 35mm 偏移，对应代码第 245 行 `arm_cord.T[index][1] + 35`，已经写死了 35mm Y 方向偏移，**你的实际偏移要量准并修改**）。
3. 相机固定在工作台上方，俯视，视野要覆盖 `default_cali_points` 里所有点（代码里大约 ±120mm × 150–250mm 的范围）。

### 执行

```bash
# 删除旧标定文件，强制重新标定
rm save_parms/image_to_arm.npy save_parms/arm_to_image.npy

python calibration_test.py
```

机械臂会自动走 50 个点，每到一个点相机就拍 ArUco。结束后会生成 `image_to_arm.npy`（4×4 仿射变换矩阵）。

### 验证

代码末尾的 Sanity Test 会打印 Expected vs Result，**误差应在 5mm 以内**。如果误差很大：
- ArUco 没贴正
- 偏移量 35mm 不对
- 相机被挪动过
- 标定点超出相机视野

### 一旦标完别动相机！

只要相机或机械臂被挪动过，就要重新标定。

---

## 六、上电跑通顺序（Bring-up Checklist）

第一次接通系统建议按这个顺序逐项验证：

1. **Pi 系统启动** → SSH 能进，`htop` 能看到 4 核
2. **相机单独验证**：插 USB → `lsusb` 能看到 Orbbec 设备 → 跑 OpenNI2 的 `SimpleViewer`，能看到深度图
3. **机械臂单独验证**：插 USB → `ls /dev/ttyUSB*` 看到设备 → 用上面 Step 3 的 Python 三行代码测 G28，臂能动
4. **夹爪/吸盘验证**：单独发 `M3` 看气泵转，发 `M5` 停
5. **YOLOv8 离线推理**：用 `detect_video.py`（注意路径改 Linux）跑一段视频，能看到 5 类废弃物的检测框
6. **手眼标定**：跑 `calibration_test.py`，生成 npy 文件，Sanity Test 误差 <5mm
7. **联调**：跑 `yolov8_test.py`，放一个塑料瓶，看臂能不能抓到桶里
8. **加分类逻辑**：换不同物体，验证三个桶分得对

---

## 七、容易踩的坑（来自代码审查）

| 风险 | 位置 | 处理建议 |
|---|---|---|
| 深度=0 时把臂撞向桌面 | `convert_depth_to_xyz` | 加阈值判断 |
| `M3`/`M5` 在不同固件里语义不同（GRBL 是主轴正/反/停，Marlin 是风扇/激光） | `send_message` 调用处 | **真接气泵前先空转测试** |
| 串口超时 timeout=2s，但 G-code 长行程要 5–10s | `port_test.py` | 把 `time.sleep(1)` 改成等 `ok` 回包 |
| 使用 `multiprocessing.Queue` 传 numpy float，序列化开销大 | `yolov8_test.py` | 当前帧率不高没关系；如果加速卡上能到 30FPS 就要换 `shared_memory` |
| 没有急停 | 整个项目 | **强烈建议**给机械臂控制板加一个物理急停开关，或者代码里监听键盘 ESC 立刻断电源 |
| 模型只识别 5 类，遇到其他垃圾会乱抓 | YOLO 训练数据 | 加一个"未知"置信阈值过滤；最低 conf 设到 0.6+ |

---

## 八、阶段性目标 / 推荐推进顺序

如果你想分阶段推进，建议：

**阶段一（1 周）：** 树莓派系统 + 相机单独跑通（OpenNI2 看深度图、YOLO 加载模型识别一张图）
**阶段二（1 周）：** 机械臂单独跑通（识别协议、串口连通、能 G-code 走点、夹爪/吸盘动作）
**阶段三（3-5 天）：** 手眼标定（贴 ArUco、跑 calibration_test、误差达标）
**阶段四（1 周）：** 联调 + 鲁棒性优化（修上面那些坑、加急停、做 demo 视频）
**阶段五（可选）：** 上 Hailo-8 加速、做 Web 监控界面、加日志和异常重启

---

## 九、需要我接下来做的事

把这份方案过一遍后，告诉我：

1. 你的机械臂控制板上**写的什么芯片/品牌**？（最好拍张照）
2. 你打算**自己买相机还是先用普通 USB 摄像头先调代码**？
3. 要不要我**先把代码改成 Linux 可跑的版本**（路径、串口、模型导出、bug 修复都打包），等硬件到了直接跑？

