# 手眼标定（Hand-Eye Calibration）

## 它在解决什么问题？

相机看到的是**像素 + 深度**。机械臂能听懂的是**毫米坐标**。
两边各有一套坐标系，必须算一个 4×4 仿射矩阵 `image_to_arm`，
让我们能这样转换：

```
arm_xyz = image_to_arm @ [x_cam, y_cam, z_cam, 1].T
```

我们的标定方法是**经典 50 点最小二乘**：
让机械臂带着一张 ArUco 卡走过 50 个已知坐标，每到一处相机拍下卡片
中心在相机坐标系下的位置。然后求最佳拟合的 4×4 矩阵。

---

## 你需要的东西

| 项 | 规格 |
|---|---|
| ArUco 标定卡 | **5cm × 5cm**，DICT_7X7_100 字典，ID=0（在 `docs/test_aruco5-5-50.jpg` 有现成的） |
| 双面胶 / 透明胶 | 把卡贴在末端 |
| 卷尺 | 量"末端到 ArUco 中心"的偏移 |
| 工作台 | 标定点全部在相机视野内 |

---

## 第一步：贴标定卡

1. 把 ArUco 卡平整地贴在机械臂末端的吸盘下方（标定卡平面**朝下**对着相机）。
2. 量出**ArUco 中心相对于机械臂末端 TCP 的偏移**（mm）。例如，你的卡贴在
   吸盘前面 35mm 的位置，那偏移就是 `[0, 35, 0]`。
3. 把这个偏移写到 `config.yaml`：
   ```yaml
   calibration:
     end_effector_to_aruco_offset_mm: [0, 35, 0]
   ```

⚠️ 这个偏移**必须量准**，量错 5mm，最终抓取就会偏 5mm。

---

## 第二步：摆相机

- 相机俯视工作台，距离 30–40cm
- 视野要**覆盖所有 50 个标定点**（默认范围约 ±120mm × 150–250mm）
- 一旦标定完成，**相机就不能再动**！稍微挪一下就要重标。
- 工作台最好深色无反光（白纸会让深度图过曝）

---

## 第三步：跑标定

```bash
source venv/bin/activate
python -m src.calibration --force
```

`--force` 表示就算 `save_parms/image_to_arm.npy` 已经存在也重做。

程序流程：

1. 提示"30 秒后开始"，给你最后一次检查的时间
2. 串口打开机械臂，G28 回零
3. 循环 50 个点：移动 → 等机械稳定 → 拍照 → 检测 ArUco → 记录中心
4. 用 `np.linalg.pinv` 求最佳仿射变换
5. 保存 `image_to_arm.npy` 和 `arm_to_image.npy`
6. 打印 Sanity Check：每个点的期望坐标 vs 用矩阵反算的坐标

---

## 第四步：判断标定好不好

看 Sanity Check 的输出：

```
pt00  expected=[ 0. 205.  10.]  result=[ 0.5 204.7  9.8]  err=0.61mm
pt01  expected=[ 0. 195.  20.]  result=[ 0.3 195.2 19.5]  err=0.62mm
...
Mean error: 1.85 mm   Max error: 4.91 mm
```

| 平均误差 | 评级 | 怎么办 |
|---|---|---|
| < 2 mm | 完美 | 直接跑 `python -m src.main` |
| 2 - 5 mm | 可用 | 大部分情况够用，注射器这种小目标可能抓不太稳 |
| 5 - 10 mm | 凑合 | 检查 ArUco 偏移、确认标定点全部在视野内 |
| > 10 mm | 重标 | ArUco 没贴正、标定卡反光、深度图无效点太多 |

---

## 常见踩坑

### 「no marker detected」一直刷屏

- ArUco 字典对不上：默认是 `DICT_7X7_100`，标定卡得是这个字典生成的
- 卡贴歪了，机械臂转动后相机看不见正面
- 工作台太亮，导致卡片对比度不够 → 关一盏顶灯
- 跑 `python tools/aruco_demo.py` 单独验证字典和卡是否匹配

### 「only N valid samples; need >= 6」

50 个标定点里没几个被识别到。原因通常是：
- 一些标定点超出相机视野 → 编辑 `src/calibration_points.py` 缩小范围
- 一些点机械臂够不到 → 同上

### Sanity Check 的误差大但运动看起来正确

- 末端到 ArUco 偏移量错了。**重新量**，重新写 `config.yaml`，重新跑
- 标定过程中相机被碰过

### 跑完抓取偏 1–2cm

- Z 方向（深度）是最大误差源。检查 `camera.intrinsics.fx/fy/cx/cy`
  是否符合你的相机出厂值
- 物体太矮（<2cm 厚）时深度图测量误差占比大，可以在 config 里
  把 `arm.pick_offset_z` 调更负一点试试

---

## 自定义标定轨迹

如果你的工作台尺寸跟默认不一样，编辑 `src/calibration_points.py`：

```python
DEFAULT_CALI_POINTS = [
    [x_mm, y_mm, z_mm, 0],   # 第 4 个值在当前实现里没用
    ...
]
```

要点：
- 至少 30 个点
- 在工作台上**均匀分布**（不要全堆在一角）
- Z 方向也要有变化（10mm 到 50mm 范围）
- 全部在机械臂可达范围内
- 全部在相机视野内
