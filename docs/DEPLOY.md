# 完整部署流程

从你拿到树莓派 + 相机 + 机械臂 那一刻起，到分拣系统真正在跑，按这个顺序走，
**每一步过了再做下一步**。任何一步过不去都看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

---

## Phase 0 — 备料

按 [BOM.md](BOM.md) 把硬件凑齐。**最小可工作集**：

- Raspberry Pi 5（4GB 也行；推 8GB）+ 27W PD 电源 + 64GB SD 卡 + 主动散热
- Orbbec Astra Pro Plus（深度相机，OpenNI2 兼容）
- G-code 协议机械臂（GRBL / Marlin 固件）
- 真空泵 + 5V 继电器 + 吸盘 + 12V 电源
- 5cm × 5cm ArUco 标定卡（`docs/test_aruco5-5-50.jpg` 直接打印）
- 三个分类垃圾桶（黄色感染性、红色病理性、利器盒）
- USB 数据线两根、USB-TTL 一根（备用）

---

## Phase 1 — 树莓派系统

### 1.1 烧 SD 卡

用 Raspberry Pi Imager：

- 系统：Raspberry Pi OS (64-bit) Bookworm
- 设置 SSH、Wi-Fi、用户名/密码（Imager 设置齿轮里）
- 烧好后插到 Pi 上，第一次开机走完 wizard

### 1.2 SSH 进 Pi

```bash
ssh pi@<pi-ip>
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### 1.3 把仓库克隆下来 + 一键安装

```bash
git clone https://github.com/deafenken/medical-waste-sorter.git medical-waste-sorter
cd medical-waste-sorter
chmod +x scripts/install_pi.sh
./scripts/install_pi.sh
```

这一步会跑 5–15 分钟（OpenNI2 编译最久）。完成后**注销重登一次**让
`dialout` 组生效。

### 1.4 验证安装

```bash
source venv/bin/activate
python -c "import cv2, numpy, serial, ultralytics; print('python deps ok')"
python -c "from openni import openni2; print('openni2 binding ok')"
ls $HOME/OpenNI2/Bin/Arm64-Release/OpenNI2/*.so | head -3
```

三条都没报错就 OK。

---

## Phase 2 — 机械臂联调

### 2.1 不连相机，先单独把机械臂搞定

USB 接到 Pi，跑：

```bash
ls /dev/ttyUSB* /dev/ttyACM*    # 应该出现一个
python tools/port_probe.py --port /dev/ttyUSB0
```

**预期看到**：

- 启动 banner（`Grbl 1.1f` / `Marlin xxx` 之类的字样）→ 说明协议对了
- 发 `G28` 后机械臂回零
- 发 `G1 X0 Y150 Z80` 后机械臂移动到对应位置
- 控制板回 `ok`（每条指令后）

**没看到 banner 或没回 ok**：协议不是 G-code，看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
"机械臂 / 串口"段。

### 2.2 改 config.yaml

```yaml
arm:
  port: /dev/ttyUSB0     # 改成你实测的串口
  baudrate: 115200       # GRBL 默认；Marlin 有时是 250000
  home_pos: [0, 185, 160]   # 改成你机械臂工作空间正中央上空
  bins:
    pathological: [170, 0, 160]    # 黄桶位置 (mm)
    infectious:   [170, 120, 160]  # 红桶位置
    sharps:       [-170, 30, 160]  # 利器盒位置
```

桶的位置先在白纸上画机械臂工作半径，然后量好桶的位置填进去。

### 2.3 手动 jog 验证

```bash
python tools/test_arm.py
arm> home
arm> move 0 180 80
arm> grip close       # 这里应该听到继电器/气泵动作
arm> grip open
arm> move 170 0 160   # 移动到病理桶位置确认能到
arm> quit
```

⚠️ **第一次接气泵之前先空载测继电器**：
- 不接气泵管子，听继电器"咔哒"响 = 接线对了
- 接错的话 `M3` 可能让继电器永远开（烧坏继电器或泵）

---

## Phase 3 — 相机联调

### 3.1 插上相机

```bash
lsusb | grep -i orbbec    # 应该出现一行
dmesg | tail              # 看插入时是否被识别
```

### 3.2 验深度图

```bash
python tools/depth_inspect.py
```

应该弹出两个窗口：彩色图和深度图。**双击彩色图上某个点**：

- 命令行打印 `(x,y) depth=NNN mm  cam=(...)` → ✓
- 打印 `depth=0 invalid` → 这一点没深度，换一处试
- 全部都是 0 → 相机距离太近或太远，工作距离 30–80cm 最稳

### 3.3 验对齐（重要！）

把手伸到画面**只占左半边**：
- 双击手上的点，深度合理（30~80cm）→ ✓
- 双击的位置打印的深度反映的是**右边空地**的距离 → 设
  `config.yaml`: `camera.flip_color: false` 重试

不验这一步，后面手眼标定一定偏。

### 3.4 验 ArUco

打印 5cm × 5cm 标定卡，跑：

```bash
python tools/aruco_demo.py
```

把标定卡放到镜头下，应该看到边框和 ID 被画出来。看不到？多半字典对不上，
检查 `config.yaml` 里 `calibration.aruco_dict: DICT_7X7_100` 跟你打的卡是不是一致。

---

## Phase 4 — 手眼标定

详见 [CALIBRATION.md](CALIBRATION.md)。简版：

### 4.1 贴卡

把 ArUco 卡贴在机械臂末端吸盘正下方。**量准** ArUco 中心相对 TCP 的偏移
（例如 +35mm Y 方向），写到 config：

```yaml
calibration:
  end_effector_to_aruco_offset_mm: [0, 35, 0]
```

### 4.2 摆相机

相机俯视工作台 30–40cm。**确认所有 50 个标定点都在视野内**——可以先用
`tools/test_arm.py` 把臂走到 `move -120 240 0` 和 `move 125 230 10`
两个极端点，看相机能不能都看到。

### 4.3 跑标定

```bash
python -m src.calibration --force
```

**前 30 秒不要动**，这是给你最后调整 ArUco 的时间。然后会自动走 50 点。

结束后看 Sanity Check 输出：
- Mean error < 5mm → ✓ 进 Phase 5
- 5–10mm → 凑合用，但小目标（注射器）抓不稳
- > 10mm → 重做，多半是 ArUco 偏移量错了或卡贴歪了

---

## Phase 5 — 流水线联调

### 5.1 第一次跑

```bash
python -m src.main
```

放一个塑料瓶到工作台中央，**手放在急停（拔 USB 或断电）旁边**，看：

1. 机械臂回零
2. 检测框画在塑料瓶上，类别"plastic bottle"，置信度 > 0.6
3. 命令行打印 `target arm xyz = (...)`
4. 机械臂上方接近 → 下压 → M5 抓取
5. 移动到病理桶上方
6. M3 释放
7. 回零等下一个

### 5.2 测三类

每类各放一个验证：
- 塑料瓶/玻璃瓶 → 病理桶 (170, 0, 160)
- 口罩/纱布 → 感染桶 (170, 120, 160)
- 注射器 → 利器盒 (-170, 30, 160)

桶位置不对直接改 `config.yaml`，**不需要重启代码**（其实需要，但只重启
不需要重新标定）。

### 5.3 调精度

抓偏 1–2cm 是常见的。先调这两个：

| 现象 | 调哪 |
|---|---|
| 偏左/右/前/后 | 重做手眼标定 |
| 偏高（吸不到） | `arm.pick_offset_z` 调更负，比如 -30 |
| 偏低（撞桌面） | `arm.pick_offset_z` 调更高，比如 -15 |
| 时好时坏 | 加深度滤波（已有 5×5 ROI 中位数），或加跨帧投票 |

---

## Phase 6 — 跑长期 demo

### 6.1 加开机自启（可选）

```bash
sudo tee /etc/systemd/system/medical-waste-sorter.service <<'EOF'
[Unit]
Description=Medical Waste Sorter
After=network.target
[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/medical-waste-sorter
ExecStart=/home/pi/medical-waste-sorter/venv/bin/python -m src.main
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable medical-waste-sorter
sudo systemctl start medical-waste-sorter
sudo journalctl -u medical-waste-sorter -f      # 看实时日志
```

注意自启时 `runtime.show_window: false`（没显示器）。

### 6.2 远程查看（可选）

VNC 或 X11 转发：
```bash
ssh -X pi@<pi-ip>      # X11 forwarding
DISPLAY=:0 python -m src.main    # 在 Pi 自己的桌面跑
```

---

## Phase 7 — 迁移到 RK3588（可选）

完整看 [RK3588.md](RK3588.md)。简版三步：

1. PC 上把 `best.pt` 转 `best.rknn`
2. `scp best.rknn` 到板子
3. 改 `config.yaml`：`detector.backend: rknn`、`detector.model_path: models/best.rknn`
4. 实现 `src/detector.py` 的 `RknnDetector.predict()`（参考 RKNN model zoo）

---

## 故障排查回路

任何一步过不去都按这个顺序排查：

1. 看终端报错的最后一行
2. 翻 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 对应章节
3. 把日志级别提到 DEBUG（`config.yaml` `runtime.log_level: DEBUG`）
4. 单独跑对应的 `tools/` 脚本定位是哪一层挂的
5. 还搞不定 → 提 issue（按 `.github/ISSUE_TEMPLATE/bug_report.yml` 格式）
