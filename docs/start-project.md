# 项目启动说明

这份文档记录一次已经跑通的真车启动流程。项目分成两部分启动：

1. 小车 Jetson 上启动控制桥接、摄像头流和 YOLO 检测接口。
2. 电脑本地启动 Web 后端和前端页面。

下面命令里的路径都用占位写法。组员只需要进入自己电脑上的项目根目录即可，不需要使用某个人的本机文件夹名。

## 1. 启动前确认

默认约定如下：

| 项目 | 默认值 | 说明 |
| --- | --- | --- |
| 小车 IP | `192.168.137.173` | 以小车终端显示的 `MY_IP` 或当前热点分配地址为准 |
| 小车用户名 | `jetson` | SSH 登录用户名 |
| 控制桥接端口 | `6001` | Web 后端通过 TCP 控制小车 |
| 摄像头端口 | `8080` | 小车上的 MJPEG 视频流 |
| YOLO 接口端口 | `8765` | 小车上的远程识别 HTTP 接口 |
| Web 后端端口 | `8000` | 电脑本地 FastAPI 服务 |

如果小车 IP 变化，把所有命令中的 `192.168.137.173` 换成当前 IP。

电脑和小车需要在同一个热点或局域网下。启动前可以先检查：

```bash
ping 192.168.137.173
```

## 2. 登录小车

在电脑终端执行：

```bash
ssh jetson@192.168.137.173
```

登录成功后，后续第 3 到第 5 节都在小车终端中执行。

## 3. 启动 6001 控制桥接

先启动 Rosmaster TCP 桥接：

```bash
nohup python3 /home/jetson/Rosmaster-App/rosmaster/icar_rosmaster_tcp_bridge.py \
  --host 0.0.0.0 \
  --port 6001 \
  --speed 50 \
  --pulse-timeout-sec 0.45 \
  </dev/null >/tmp/icar_rosmaster_tcp_bridge.log 2>&1 &
```

检查端口是否已经监听：

```bash
ss -lntp | grep 6001
```

看到类似下面输出就表示启动成功：

```text
LISTEN 0 5 0.0.0.0:6001 0.0.0.0:* users:(("python3",pid=xxxx,fd=8))
```

如果需要重启桥接：

```bash
pkill -f '[i]car_rosmaster_tcp_bridge.py' 2>/dev/null || true
```

然后重新执行本节的 `nohup python3 ...` 命令。

## 4. 启动 8080 摄像头流

先停止旧的摄像头服务，避免端口或摄像头设备被占用：

```bash
pkill -f '[i]car_camera_mjpeg_server.py' 2>/dev/null || true
```

启动 MJPEG 摄像头服务：

```bash
nohup python3 /home/jetson/icar_camera_mjpeg_server.py \
  --host 0.0.0.0 \
  --port 8080 \
  --device auto \
  --width 640 \
  --height 480 \
  --fps 12 \
  </dev/null >/tmp/icar_camera_mjpeg_server.log 2>&1 &
```

在小车上检查端口：

```bash
ss -lntp | grep 8080
```

在电脑上也可以检查：

```bash
nc -vz 192.168.137.173 8080
```

浏览器可打开下面地址看视频流：

```text
http://192.168.137.173:8080/?action=stream
```

如果页面只有占位图或打不开，查看日志：

```bash
tail -n 80 /tmp/icar_camera_mjpeg_server.log
```

## 5. 启动 8765 YOLO 接口

先停止旧的 YOLO 服务：

```bash
pkill -f '[y]olo_stream_service.py' 2>/dev/null || true
```

启动 YOLO 识别接口。当前实测使用 8080 摄像头流作为输入：

```bash
nohup python3 /home/jetson/yolo_stream_service.py \
  --host 0.0.0.0 \
  --port 8765 \
  --stream-url 'http://127.0.0.1:8080/?action=stream' \
  --yolo-root /home/jetson/yolov5-7.0 \
  --weights /home/jetson/yolov5-7.0/TRAFFIC/best.pt \
  --data /home/jetson/yolov5-7.0/TRAFFIC/voc_traffic.yaml \
  </dev/null >/tmp/icar_yolo_stream.log 2>&1 &
```

如果小车上的 `yolo_stream_service.py` 已经配置好默认模型，也可以用简化命令：

```bash
nohup python3 /home/jetson/yolo_stream_service.py \
  --host 0.0.0.0 \
  --port 8765 \
  --stream-url 'http://127.0.0.1:8080/?action=stream' \
  </dev/null >/tmp/icar_yolo_stream.log 2>&1 &
```

检查端口：

```bash
ss -lntp | grep 8765
```

检查健康接口：

```bash
curl http://127.0.0.1:8765/health
```

如果启动失败或识别接口没有响应，查看日志：

```bash
tail -n 120 /tmp/icar_yolo_stream.log
```

## 6. 启动电脑本地 Web 后端

回到电脑终端，进入项目根目录：

```bash
cd /path/to/icar
source .venv/bin/activate
```

如果还没有安装依赖，先执行一次：

```bash
pip install -r backend/requirements.txt
```

设置真车和视觉服务环境变量：

```bash
export ICAR_CAR_ADAPTER=tcp
export ICAR_CAR_HOST=192.168.137.173
export ICAR_CAR_PORT=6001
export ICAR_HOST=0.0.0.0

export ICAR_VISION_MODE=remote
export ICAR_VISION_HOST=192.168.137.173
export ICAR_VISION_PORT=8765
export ICAR_VISION_STREAM_URL='http://192.168.137.173:8080/?action=stream'
export ICAR_VISION_TICK_SEC=1.5
```

启动后端：

```bash
bash ./scripts/start_backend.sh
```

终端出现下面信息表示后端启动成功：

```text
iCar backend starting...
Bind host: 0.0.0.0
Bind port: 8000
Uvicorn running on http://0.0.0.0:8000
```

浏览器打开：

```text
http://127.0.0.1:8000/control
http://127.0.0.1:8000/vision
```

如果手机和电脑在同一个局域网，也可以打开电脑局域网 IP 对应的地址：

```text
http://电脑局域网IP:8000/control
```

## 7. 常用检查和停止命令

在电脑检查小车端口：

```bash
nc -vz 192.168.137.173 6001
nc -vz 192.168.137.173 8080
nc -vz 192.168.137.173 8765
```

在小车查看服务日志：

```bash
tail -n 80 /tmp/icar_rosmaster_tcp_bridge.log
tail -n 80 /tmp/icar_camera_mjpeg_server.log
tail -n 120 /tmp/icar_yolo_stream.log
```

在小车停止三个服务：

```bash
pkill -f '[i]car_rosmaster_tcp_bridge.py' 2>/dev/null || true
pkill -f '[i]car_camera_mjpeg_server.py' 2>/dev/null || true
pkill -f '[y]olo_stream_service.py' 2>/dev/null || true
```

在电脑停止 Web 后端：

```text
按 Ctrl+C
```

## 8. 启动顺序速查

完整顺序如下：

1. 电脑 SSH 登录小车：`ssh jetson@小车IP`
2. 小车启动 `6001` 控制桥接。
3. 小车启动 `8080` 摄像头流。
4. 小车启动 `8765` YOLO 接口。
5. 电脑进入项目根目录，激活 `.venv`。
6. 电脑设置 `ICAR_CAR_*` 和 `ICAR_VISION_*` 环境变量。
7. 电脑执行 `bash ./scripts/start_backend.sh`。
8. 浏览器打开 `/control` 或 `/vision` 页面。
