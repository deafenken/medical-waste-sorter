# 识别模型优化指南

按"先做容易做的、再做需要工具链的、最后做需要重训的"顺序整理。
**所有第一档的优化已经在代码里实现了**，下面只是文档说明怎么调参；
第二档需要你自己跑脚本；第三档需要训练数据。

---

## 第一档：纯代码优化（已实现，在 config.yaml 里调）

### 1.1 双阈值 / 置信度迟滞

```yaml
detector:
  conf_draw:    0.40   # 高于此就画框（看到模型在想什么）
  conf_trigger: 0.70   # 高于此才会进入抓取候选
```

**调参方法**：先看主流水线运行时的可视化窗口。把 `conf_draw` 调到 0.3
让所有"模型有点犹豫"的检测都显出来，观察哪些是真物体哪些是误检；然后
把 `conf_trigger` 设在能稳定卡掉所有误检的那条线（一般 0.65-0.75）。

⚠️ 注意 trigger 不是越高越好——调到 0.85 漏检率会飙升，反而拖慢分拣。

### 1.2 多帧投票（IoU Tracker + consecutive_hits）

```yaml
detector:
  use_tracker: true
  vote_window: 3        # 同一物体连续被检测到 N 帧才触发
  tracker_iou: 0.3      # 帧间 IoU 大于此判定为同一物体
  tracker_max_lost: 5   # 连续 N 帧没匹配到就淘汰这个 track
```

**这一项性价比最高**。即使你的模型偶尔把白桌布角识成口罩，只要它不连续
3 帧出现在同一位置，就不会触发抓取。代价是延迟增加 `vote_window/FPS` 秒
（10 FPS 时 0.3 秒），对静态物体基本无感。

调参经验：

| 场景 | vote_window |
|---|---|
| 物体静止、追求稳 | 5 |
| 物体被推上传送带 | 2 (再多就跟不上了) |
| 默认 | 3 |

### 1.3 输入分辨率

```yaml
detector:
  imgsz: 640    # 默认；改 320 速度快约 4 倍，小目标精度降
```

只在 Pi CPU 推理太慢时调。如果你换了加速棒（Hailo / Coral）或上了
RK3588 NPU，**保持 640** 不要为了速度牺牲精度。

### 1.4 NMS 参数

```yaml
detector:
  iou_threshold: 0.7    # 默认 0.7；目标紧靠时调到 0.5 减少重复检测
  max_det: 100          # 默认；工作台一般几个物体，调到 30 省后处理时间
```

### 1.5 模型预热

代码里 `detector.warmup()` 在视觉进程启动后被自动调用一次，跑一帧
640×640 全零图。第一帧的 1-2 秒冷启动开销被吃掉，从第二帧起就是稳态
FPS。**这一项不需要你做任何事**，自动生效。

---

## 第二档：导出 / 量化（需要工具链，不需要重训）

### 2.1 NCNN FP16 导出

`scripts/install_pi.sh` 已经自动做了这个。手动跑：

```bash
python tools/export_ncnn.py models/best.pt
```

产出：`models/best_ncnn_model/`。配 yaml：

```yaml
detector:
  backend: ncnn
  model_path: models/best_ncnn_model
```

### 2.2 NCNN INT8 量化（推荐做）

INT8 比 FP16 再快约 2 倍，精度一般损失 1-3%。**RK3588 NPU 路径也强烈
建议用 INT8**，不然 NPU 无法发挥。

#### 步骤 1：捕获校准集

INT8 量化器需要看 50-200 张**真实场景图**来确定每层激活值的范围。**不是
训练集，不是验证集**——必须是部署现场的图。所以这一步要在你布好相机和
工作台之后做。

```bash
python tools/capture_calib_set.py --count 100 --interval 0.5
```

捕获时务必：
- 摆上真实的医疗废弃物样本
- 切换不同光照（开关顶灯、关一盏）
- 物体位置/角度随机变换
- 留几张空台面的帧
- 让相机拍到有反光、阴影的边角情况

输出在 `calib_set/calib_*.jpg` + `calib_set/dataset.txt`。

#### 步骤 2：跑量化

```bash
python tools/quantize_ncnn.py models/best.pt --int8 --calib calib_set
```

产出 `models/best_ncnn_int8_model/`。配 yaml：

```yaml
detector:
  backend: ncnn
  model_path: models/best_ncnn_int8_model
```

#### 步骤 3：精度回归

INT8 不是无损，**部署前一定要测一下**。建议方法：

```bash
# 1. 用 FP16 模型跑分拣，记录 10 个物体的检测情况
# 2. 切到 INT8，用同样物体跑一遍
# 3. 比对：检测置信度差几个百分点正常；漏检/误检明显增多就回退 FP16
```

如果 INT8 精度损失太大，可能是校准集不够代表性。重新捕获更多场景再试。

### 2.3 RKNN INT8（RK3588 路径）

完整流程见 [RK3588.md](RK3588.md)。校准集复用第 2.2 步的 `calib_set/`。

---

## 第三档：重训（需要原始数据集）

> 你说数据没了，所以这一档暂时**用不了**。仅作记录，将来如果你重新攒
> 数据集做了，按下面思路升级。

### 3.1 升级 backbone：YOLOv8n → YOLOv8s

精度提升约 5-8 个 mAP，Pi 5 NCNN 仍能跑 5-8 FPS。

```bash
# 在你的训练机上
yolo detect train data=medical_waste.yaml model=yolov8s.pt imgsz=640 epochs=100
```

### 3.2 换 YOLOv11n

Ultralytics 2024 年发的新架构，同等大小精度提升明显。

```bash
yolo detect train data=medical_waste.yaml model=yolo11n.pt imgsz=640 epochs=100
```

代码不用改——`UltralyticsDetector` 直接接 v11 的 .pt。

### 3.3 难例挖掘

让现有系统跑一段时间，把所有"漏检 / 误检 / 抓不稳"的画面用
`tools/capture_calib_set.py`（改个 --out 路径）保存下来，标注后并入
训练集重训。

### 3.4 数据增强补强

医疗场景常见的：
- 半透明/反光物体（注射器塑料外壳）→ 添加亮度抖动 + 反射高光合成
- 部分遮挡（口罩堆叠）→ 加 `mosaic` 和 `cutout`
- 弱光 → 添加暗化增强

`yolov8.yaml` 里改：
```yaml
hsv_v: 0.4    # 亮度抖动幅度
mosaic: 1.0   # mosaic 概率
mixup: 0.15
copy_paste: 0.1
```

---

## 第四档：进阶 / 实验性

### 4.1 测试时增强 (TTA)

水平翻转 + 多尺度 + 平均输出。慢约 4 倍，但对边缘 case 鲁棒性好。
```python
results = model.predict(source=frame, augment=True)
```
Pi 上不建议，RK3588 加 NPU 仍能 ~10 FPS。

### 4.2 集成 (Ensemble)

同时跑 YOLOv8n + YOLOv8s，框 IoU 重叠的取平均置信度。
代码层面要双 detector，**显存/内存翻倍**。

### 4.3 模型蒸馏

用大模型 (m/l) 当 teacher，蒸馏到 n。可以让 n 模型精度逼近 s。
需要训练框架支持，工程量较大。

---

## 调参速查表

| 现象 | 调哪个参数 |
|---|---|
| 偶尔误抓桌布、空气 | 提高 `conf_trigger` 或 `vote_window` |
| 慢 / 动作犹豫 | 降低 `vote_window`；改 `imgsz: 320` |
| 多个物体同时出现时混乱 | 提高 `tracker_iou`；查 `max_det` 是否够 |
| 第一帧卡顿 | 检查 warmup 日志，应该有 "detector warmed up" |
| 同一物体被反复抓两次 | track 没消亡，检查 `tracker_max_lost` |
| INT8 后精度掉 5%+ | 校准集不够代表性，重新捕获 |
| Pi 上 FPS < 5 | 上 INT8；或换 Hailo / RK3588 |

---

## 实测数据参考（我没在你硬件上验过，仅作量级参考）

| 配置 | imgsz | Pi 5 FPS | 精度（相对 FP32） |
|---|---|---|---|
| PyTorch FP32 | 640 | 2-4 | 100% |
| NCNN FP16 | 640 | 8-12 | 99-100% |
| NCNN INT8 | 640 | 15-20 | 97-99% |
| NCNN FP16 | 320 | 20-30 | 95-97% |
| NCNN INT8 | 320 | 30+ | 93-96% |
| RK3588 NPU INT8 | 640 | 30-40 | 97-99% |
| Hailo-8L | 640 | 30+ | 99-100% |

具体取决于模型结构、量化校准质量、Pi 散热状况。
