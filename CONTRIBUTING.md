# 贡献指南

欢迎一切 issue 和 PR。本项目目标是让医疗废弃物分拣机械臂在树莓派 / RK3588 上可复现地跑起来。

## 提 Issue

按 `.github/ISSUE_TEMPLATE/` 里的模板提，**完整填写硬件信息和日志**能极大节省排查时间。

## 提 PR

### 代码风格

- 类型注解（`from __future__ import annotations`）
- `logging` 而不是 `print`
- 一切硬编码进 `config.yaml`，新加字段在 `config.example.yaml` 写注释和默认值
- 模块对外接口写 docstring（中文 / 英文皆可）

### 加新硬件支持

#### 新相机后端

继承 `src/camera.py` 的 `Camera` 基类，实现：
```python
class MyCamera(Camera):
    def read(self) -> tuple[ndarray, ndarray | None, ndarray | None]: ...
    def close(self) -> None: ...
```
然后在 `build_camera()` 里加分支。

#### 新机械臂协议

继承 `src/serial_arm.py` 的接口（保持 `home()`、`move()`、`gripper_*()`、`send()` 这几个方法）。
单独建一个文件如 `src/dobot_arm.py`，然后在 `config.yaml` 加 `arm.protocol: dobot` 分支。

#### 新检测后端

继承 `src/detector.py` 的 `Detector` 基类，实现 `predict()`。已有 `RknnDetector`
作为 NPU 后端的骨架可以参考。

### 测试

CI 跑 `py_compile` 和轻量 import 检查（不依赖真硬件）。**涉及硬件的改动请在
PR 描述里贴你实测的截图 / 视频 / 日志**。

### 提交粒度

一个 PR 解决一件事。重构和新功能分开提，便于 review 和 revert。

## 数据 / 模型贡献

如果你训了一个更好的医疗废弃物检测模型并愿意开源，欢迎提 PR：
- 把权重放到 `models/`，文件名注明类别数和数据集（如 `best_v2_8cls.pt`）
- 在 `docs/MODELS.md` 加一段说明：训练数据来源、类别表、性能指标
- 更新 `config.example.yaml` 的 `category_to_bin` 映射

**注意**：医疗影像数据如果有版权或患者隐私问题，先妥善处理后再贡献。
