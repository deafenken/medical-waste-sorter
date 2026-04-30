# 故障排查

按"问题归属"分组。先定位是相机问题、机械臂问题、模型问题还是标定问题，
再去对应章节查。

---

## 相机 / OpenNI2

### `ImportError: No module named openni`
```
pip install primesense
```
但仅 Python 包是不够的，还要装 OpenNI2 **原生** 库（`.so`）。
`scripts/install_pi.sh` 会自动编译 ARM64 版。

### `OniInit() failed`
- `openni_redist_path` 不正确。这个路径要指向**包含驱动 `.so` 的目录**，
  例如 `/home/pi/OpenNI2/Bin/Arm64-Release/OpenNI2`（注意是 `OpenNI2` 子目录）。
- udev 规则没装，普通用户没权限访问 USB → 跑过 `install_pi.sh` 后**重新插拔相机**

### 相机识别不出来 (`Device.open_any()` 失败)
```bash
lsusb | grep -i orbbec
# 看不到？换 USB 口（要 USB 3.0 蓝口）；换 USB 线
```

### 深度图全黑或全白
- 物体太近（<30cm）或太远（>2m）→ 调整工作台高度
- 反光物体 → 换深色无反光台面
- 红外发射器被挡

### 彩色图镜像了
- 改 `config.yaml`：`camera.flip_color: false`

### ⚠️ 彩色图与深度图不对齐（坐标系坑）
**症状**：识别框画在塑料瓶上，但机械臂去抓的是瓶子旁边几厘米外的空地。

**原因**：很多 Astra 系列相机的 USB 彩色镜头与深度镜头**水平方向是镜像的**。
本项目默认 `flip_color: true` 假设你的相机就是这种情况——翻转后彩色和深度才对齐。
但**有些 Astra 出厂校准已经处理了这个镜像**，再翻一次反而错位。

**自检方法**：跑 `python tools/depth_inspect.py`，把一个有明显形状的物体
（比如手）放进画面里**只占左半边**。
- 如果双击物体上的点能打印合理的深度值（30~80cm 范围）→ 配置正确
- 如果双击物体打印的深度是 0 或者反映的是另一侧的距离 → 设
  `camera.flip_color: false` 再试一次

不验证就跑标定，结果会一直偏。

---

## 机械臂 / 串口

### `serial.serialutil.SerialException: could not open port`
```bash
ls -l /dev/ttyUSB0    # 设备存在吗？
groups               # 当前用户在 dialout 里吗？
sudo usermod -aG dialout $USER && newgrp dialout
```

### 看不到 `/dev/ttyUSB*` 也看不到 `/dev/ttyACM*`
```bash
dmesg | tail        # 插入 USB 时看是不是被识别
lsusb               # 看 vendor:product
```
没有任何条目 → 控制板可能坏了，或线只是充电线没数据。

### 发送 G28 但机械臂不动
- 协议不对：不是所有控制板都吃 G-code。跑 `python tools/port_probe.py`，
  如果回包里没有 `Grbl` / `Marlin` / `ok`，说明协议不匹配
- Marlin 默认要求"先 home 才能 move"，先发 `G28`
- 步进电机使能没打开（GRBL 的话先发 `$X` 解锁报警状态）

### G-code 发出后控制板回 `error:9`（GRBL）
意思是 home 之前不能 move。先 `G28`，再 `G1 ...`。

### 不停 `ACK timeout waiting for response`
- 串口波特率不对，常见 115200 / 250000，看你控制板说明书
- 控制板根本不回 `ok`（Dobot 私有协议）→ 在 `config.yaml` 设
  `arm.wait_for_ok: false`，但要自己加 `time.sleep` 防止指令踩踏

### 夹爪 `M3` / `M5` 不工作或方向反了
- 不同固件/不同接线，可能要换：
  - GRBL 主轴：`M3`（开）/ `M5`（关）
  - GRBL 冷却液：`M7`/`M9`
  - Marlin 风扇：`M106 S255`/`M107`
  - Marlin 激光：`M3 S255`/`M5`
- 改 `config.yaml`：
  ```yaml
  arm:
    gripper_close_cmd: "M3 S255"
    gripper_open_cmd:  "M5"
  ```

---

## 模型 / 检测

### `ultralytics.utils.errors.HUBModelError`
模型路径不对。NCNN 模式下 `model_path` 要指向**目录**而不是文件：
```yaml
detector:
  backend: ncnn
  model_path: models/best_ncnn_model    # 是目录！
```

### NCNN 推理结果与 PyTorch 不一致
不应该差太多。如果差 10% 以上：
- 重新 export：`python tools/export_ncnn.py models/best.pt`
- 检查 ultralytics 版本，>=8.1 才稳定

### 检测不出口罩 / 注射器
- 训练数据里这一类样本太少 → 重训，加数据
- `conf_threshold` 太高 → 调到 0.4 试试
- 距离/角度变了 → 训练时镜头距离要和实测一致

### 推理太慢（< 5 FPS）
- 是不是用了 PyTorch 后端？换 NCNN
- 树莓派散热不行触发降频 → 加风扇
- 上 Hailo / RK3588

---

## 标定 / 抓取

详见 [CALIBRATION.md](CALIBRATION.md) 末尾的 FAQ。简短版：

| 现象 | 原因 |
|---|---|
| 抓在物体旁边 1cm | 末端到 ArUco 偏移量不准 |
| 抓在物体上方 1cm | `arm.pick_offset_z` 太保守 |
| 偏差随位置变化 | 标定点没覆盖整个工作台 |
| 时好时坏 | 深度图有噪声，加深度滤波或多帧平均 |

---

## 跑通流水线后

### 流程卡住，机械臂不动
- 看 `[main]` 日志，是不是停在 `ACK timeout`？
- 是不是没物体所以没目标？把物体放到镜头中央
- 是不是 `robot_status` 永远是 `STATUS_BUSY`？检查 arm 子流程是不是
  在等什么没回的 `ok`

### 进程退出但相机或串口没释放
- 用 `Ctrl+C`，主进程会清理；如果 `kill -9` 了就要拔掉 USB 重插
- 把 `config.yaml` 里 `runtime.show_window: false` 改成 `true`
  跑，按 `q` 优雅退出

### 想看更详细的日志
```yaml
runtime:
  log_level: DEBUG
```

---

## 还是搞不定？

打开一个 issue，附上：
- 平台（树莓派型号 / OS 版本）
- 完整报错信息
- `config.yaml`（去掉敏感信息）
- `lsusb` 输出
- 视觉/串口/标定 哪个 tools 子命令失败的
