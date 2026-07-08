# YOLOv5 视觉模块

课程资料中的视觉目标检测流程使用 YOLOv5：

- 训练：在 x86 主机 + Nvidia GPU 上准备 YOLOv5-7.0、标注数据集和 `*.yaml` 配置，运行 `train.py`。
- 应用：在 Jetson Orin Nano Ubuntu 20.04 上部署 PyTorch、OpenCV、YOLOv5 和训练得到的 `best.pt`，读取 Astra 深度相机/RGB 图像做推理。
- 联动：识别结果可结合深度图距离，最后发布 `/cmd_vel` 控制底盘。

本目录提供的是训练/推理脚本骨架，不把大模型文件提交到 Git。推荐把模型放在：

```text
vision/weights/best.pt
vision/weights/yolov5s.pt
```

`weights/` 已被 `.gitignore` 忽略。

## 训练

先准备 YOLOv5-7.0 源码目录和数据集，然后运行：

```bash
python vision/train_yolov5.py \
  --yolov5-dir /home/yyh/yolov5-7.0 \
  --data vision/yolov5_home.yaml \
  --weights yolov5s.pt \
  --epochs 80 \
  --batch-size 16 \
  --img 640
```

如果只是课程演示，建议优先用预训练 `yolov5s.pt` 检测 `person`，再扩展宠物、门窗、危险物品等家庭类别。

## 推理

```bash
python vision/infer_yolov5.py \
  --yolov5-dir /home/jetson/yolov5-7.0 \
  --weights vision/weights/best.pt \
  --source 0
```

`--source 0` 表示摄像头；也可以换成图片、视频、RTSP 地址。

