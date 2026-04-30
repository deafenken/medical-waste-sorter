# Hailo-8 / Hailo-8L NPU 部署指南

> Pi 5 + Hailo-8 26 TOPS：YOLOv8n 在 640×640 输入下能稳定 30+ FPS。
> 本文是把 `best.pt` 跑在 Hailo NPU 上的完整流程。

---

## 实测对比（参考量级）

| 后端 | 输入 | 单帧耗时 | FPS | 备注 |
|---|---|---|---|---|
| Pi 5 PyTorch (CPU) | 640 | 250-500 ms | 2-4 | 别跑生产 |
| Pi 5 NCNN (CPU) | 640 | 80-120 ms | 8-12 | 默认 fallback |
| Pi 5 NCNN INT8 (CPU) | 640 | 50-70 ms | 15-20 | 量化后 |
| **Pi 5 + Hailo-8L (13 TOPS)** | 640 | 30 ms | 30+ | 中端 NPU |
| **Pi 5 + Hailo-8 (26 TOPS)** | 640 | 15-20 ms | **40-60** | 你这套 |

---

## 整体迁移路径

```
PC (有 GPU 或快 CPU 即可)            Pi 5 + Hailo-8
+--------------------------+         +---------------------+
| best.pt                  |         |                     |
|     |                    |         |                     |
|     v ultralytics export |         |                     |
| best.onnx                |         |                     |
|     |                    |         |                     |
|     v Hailo Dataflow     |         |                     |
|       Compiler (DFC)     |         |                     |
| best.har -> best.hef     |         |                     |
+--------------------------+         |                     |
              |                      |                     |
              | scp best.hef         |                     |
              v                      v                     |
                            +----+----+                    |
                            | best.hef |  HailoRT runtime  |
                            +----------+        |          |
                                                v          |
                                       hailo_platform API  |
                                                |          |
                                                v          |
                                       30+ FPS @ NPU       |
                                                +----------+
```

⚠️ **Hailo Dataflow Compiler (DFC) 仅支持 x86_64 Linux**。Pi 上无法转换模型，
必须在 PC（Ubuntu 22.04 x86_64 推荐）上转完，再 scp 到 Pi。

---

## Step 1：在 PC 上把 .pt → .onnx

```bash
# 在你的 PC 上（不是 Pi 上）
pip install ultralytics
python tools/export_ncnn.py models/best.pt --format onnx
# 产出 models/best.onnx
```

---

## Step 2：在 PC 上注册 Hailo 开发者账号 + 下 DFC

1. 注册 https://hailo.ai/developer-zone/
2. 下载：
   - **Hailo Dataflow Compiler (DFC)** —— Ubuntu .deb 或 wheel（仅 x86_64）
   - **Hailo Model Zoo** —— Github 公开源
3. 装 DFC（按官方指南，需要 Python 3.10）

---

## Step 3：在 PC 上把 .onnx → .hef（量化 + 编译）

DFC 需要校准数据。**用你 Pi 上 `tools/capture_calib_set.py` 拍的真实部署
场景图**——这是关键，校准集质量决定 INT8 精度。

```bash
# 把 Pi 上 calib_set/ 整个 scp 到 PC
scp -r winbeau@selabpi5.local:~/medical-waste-sorter/calib_set ./

# 在 PC 上用 Hailo Model Zoo 的脚本一键转换
git clone https://github.com/hailo-ai/hailo_model_zoo.git
cd hailo_model_zoo
pip install -e .

# 转换：用现成的 yolov8n.yaml 配置改一下
hailomz compile yolov8n \
    --ckpt /path/to/best.onnx \
    --hw-arch hailo8 \
    --calib-path /path/to/calib_set \
    --classes 5

# 产出 best.hef
```

`--hw-arch hailo8`（你的型号是 26 TOPS）；如果是 Hailo-8L 改成 `hailo8l`。
`--classes 5` 是你的类别数。

详细参数和疑难，看：
- 官方文档：https://hailo.ai/developer-zone/documentation/
- Model Zoo: https://github.com/hailo-ai/hailo_model_zoo/blob/master/docs/COMPILE.rst

---

## Step 4：在 Pi 上装 HailoRT 运行时

HailoRT 是闭源的，**不能 pip 装**，必须从 Hailo Developer Zone 下：

1. Pi 上 `mkdir -p ~/hailo`
2. 在 PC 上下：
   - `hailort_4.x.x_arm64.deb` —— ARM64 系统包
   - `hailort-pcie-driver_4.x.x_all.deb` —— PCIe 驱动（如果你 Hailo 走 PCIe / M.2）
   - `hailo_platform-4.x.x-cp311-cp311-linux_aarch64.whl` —— Python 绑定
3. scp 到 Pi 的 `~/hailo/` 目录
4. 让 install_pi.sh 自动装：

```bash
HAILO_SDK=1 ./scripts/install_pi.sh
```

脚本会从 `~/hailo/` 检测到这些文件并 dpkg + uv pip install。

或者手动装：

```bash
cd ~/hailo
sudo dpkg -i hailort_*.deb
sudo dpkg -i hailort-pcie-driver_*.deb
sudo modprobe hailo_pci   # 加载 PCIe 驱动
uv pip install hailo_platform-*.whl

# 验证
hailortcli scan
# 应该能看到你的 Hailo-8 设备
```

---

## Step 5：把 best.hef 拷到 Pi，配 yaml

```bash
# PC 上
scp best.hef winbeau@selabpi5.local:~/medical-waste-sorter/models/

# Pi 上改 config.yaml
```

```yaml
detector:
  backend: hailo
  model_path: models/best.hef
  imgsz: 640         # 必须和 .hef 编译时的 input shape 一致
```

---

## Step 6：实现 HailoDetector.predict()

这一步是**实际写代码**——`src/detector.py` 里 `HailoDetector.predict()`
目前是 `NotImplementedError` 占位。

参考 Hailo Model Zoo 的 `yolov8.py` 后处理：
https://github.com/hailo-ai/hailo_model_zoo/tree/master/hailo_model_zoo/core/postprocessing

完整实现要做四件事：

1. **预处理**：BGR→RGB，letterbox 到 (imgsz, imgsz)，归一化到 [0, 1] FP32
2. **NPU 推理**：
   ```python
   with InferVStreams(network_group, input_vstreams_params, output_vstreams_params) as infer_pipeline:
       output = infer_pipeline.infer({input_vstream_info.name: preprocessed})
   ```
3. **解码 YOLOv8 输出**：3 个 grid 头（小/中/大），每个 grid 出
   `[bbox(4) + class_score(C)]`，跑 NMS
4. **letterbox 反推**：把 grid 坐标转回原图像素坐标

如果你的 .hef 在 Hailo Model Zoo 编译时**已经塞了 NMS 后处理**（开
`--include-postprocess`），第 3、4 步可以省，输出直接是 `[xmin, ymin, xmax, ymax, score, cls_id]` 的张量。

---

## Step 7：跑流水线

```bash
uv run python -m src.main
```

vision_worker 会从 NPU 拿检测结果，理论上能跑 30+ FPS。第一次跑时
关注：

- Hailo 状态：`hailortcli scan` 看设备活跃
- 推理耗时：日志里 FPS 应该明显高于 NCNN 模式
- 检测精度：和 NCNN 相比损失应该 < 3 mAP（INT8 量化常见区间）

---

## 常见问题

### `hailortcli scan` 找不到设备
- M.2 接口没插好，或者 PCIe 驱动没加载：`sudo modprobe hailo_pci`
- Pi 5 PCIe 默认是 Gen 2，但 Hailo 8 要求 Gen 3：编辑 `/boot/firmware/config.txt`，加 `dtparam=pciex1_gen=3`，重启
- 散热不足：Hailo 8 满载会热到 70°C+，**需要主动散热**

### `hailo_platform` import 失败
- HailoRT 系统包没装：`sudo dpkg -i hailort_*.deb`
- Python 版本不匹配：wheel 文件名 `cp311` 必须对应你的 Python 3.11
- venv 路径问题：在 .venv 里 `uv pip install hailo_platform-*.whl`

### .hef 编译时报"unsupported op"
- YOLOv8 export 时确保用 `imgsz=640` 且没有 dynamic axes
- 用 Hailo Model Zoo 的 `yolov8n.yaml` 配置改最少东西：classes 数 + checkpoint 路径
- DFC 版本太老不支持 v8，升级到 3.27+

### 推理速度上不去
- 输入分辨率没必要 640，试试 320（imgsz: 320 重新编译 hef）
- 多核：`InferVStreams` 默认单线程，可以用 `AsyncInfer` API
- 数据传输瓶颈：图像预处理在 CPU，NPU 闲着等；预热 + pipeline 化

---

## 参考链接

- 官方 Developer Zone：https://hailo.ai/developer-zone/
- Hailo Model Zoo：https://github.com/hailo-ai/hailo_model_zoo
- HailoRT 文档：https://hailo.ai/developer-zone/documentation/hailort-v4-19-0/
- Pi 5 + Hailo-8 装机指南（社区）：https://www.raspberrypi.com/documentation/accessories/ai-kit.html
