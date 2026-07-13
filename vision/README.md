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

## 不抢摄像头的真车接法

如果小车已经提供原生视频流 `http://小车IP:6500/video_feed`，推荐不要再让 YOLO 直接打开 `/dev/video0`。

本项目提供了一个轻量桥接脚本：

```text
robot/yolo_stream_service.py
```

它的设计是：

- 从现成的 `6500/video_feed` 读取一帧
- 调用小车本地已有的 YOLOv5 推理代码
- 通过 HTTP 返回检测结果 JSON
- 不直接占用摄像头设备

典型启动方式示例：

```bash
python3 robot/yolo_stream_service.py \
  --host 0.0.0.0 \
  --port 8765 \
  --stream-url http://127.0.0.1:6500/video_feed \
  --yolo-root /home/jetson/yolov5-7.0 \
  --weights /home/jetson/Yolov5ptFile/yolov5s.pt \
  --data /home/jetson/yolov5-7.0/data/coco128.yaml
```

后端可通过这些环境变量切到远端 YOLO 服务：

```bash
export ICAR_VISION_MODE=remote
export ICAR_VISION_HOST=192.168.137.173
export ICAR_VISION_PORT=8765
export ICAR_VISION_STREAM_URL=http://192.168.137.173:6500/video_feed
```
