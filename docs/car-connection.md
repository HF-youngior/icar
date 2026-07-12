# 小车连接说明

## 1. 现在推荐的连接方式

现在不再把 NoMachine 作为主流程。已经实测可用的推荐方式是：

1. 电脑和小车连接同一个热点或同一个局域网。
2. 先检查控制端口：优先用 `6000`，如果 `6000 closed` 但 `6001 open`，就用我们的备用 Rosmaster 桥接 `6001`。
3. 本地启动 Web 后端，网页通过当前可用的 TCP 控制端口连接小车。
4. 手机、电脑、小车在同一个热点时，手机也可以打开电脑打印出的局域网网址进行控制。

这样做的好处是：

- 不需要一直开 NoMachine 桌面。
- 不依赖固定 Docker 容器 ID，例如之前的 `549b`。
- Web 遥控优先复用可用控制链路：`6000` 能用就连 `6000`，否则使用已经启动的 `6001` 自建桥接。
- 组员只需要 PowerShell、浏览器和同一局域网，就能重复操作。

## 2. 为什么以前的 `549b` 不可靠

Docker 容器 ID 不是固定值。只要小车重新创建过容器、恢复过镜像，或者换过环境，容器 ID 就会变化。

所以现在脚本已经改成：

- 默认自动扫描小车上的 ROS/Foxy/Yahboom 相关容器。
- 优先选择正在运行的容器。
- 如果没有运行中的，再选第一个匹配到的容器。
- 也支持你手动传入 `-Container` 指定容器。

## 3. 先决条件

默认假设：

- 小车 IP：当前热点下以小车屏幕/终端显示为准，例如本次实测为 `192.168.137.173`
- 小车用户名：`jetson`
- 小车密码：`yahboom`
- Web 手动遥控优先连接 `6000`，如果 `6000 closed` 且 `6001 open`，就连接 `6001`
- Docker/ROS2 容器方案仍保留，用于后续 SLAM、建图、导航链路联调

如果 IP 改了，只要把命令里的 `192.168.137.173` 换成当前 IP 即可。

### 3.1 当前端口约定

| 端口 | 用途 | 是否默认使用 |
| --- | --- | --- |
| `22` | SSH 登录小车，用于脚本启动小车端服务 | 必须可通 |
| `6000` | 小车原生 Rosmaster/App 控制端口，Web 遥控默认连接这里 | 默认控制端口 |
| `6001` | 我们自建 Rosmaster 备用桥接端口 | 仅当 `6000 closed` 时备用 |
| `6500` | 小车原生 App 实时画面，路径 `/video_feed` | 默认视觉画面 |
| `8080` | 我们自建 MJPEG 备用摄像头，路径 `/?action=stream` | 仅当 `6500` 不稳定时备用 |
| `8000` | 电脑本地 Web 后端端口，手机也访问电脑这个端口 | Web 页面端口 |

## 4. 推荐操作流程

### 4.1 先检查小车连接状态

热点重新连上后，在项目根目录执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

手动遥控至少需要看到 `6000 open` 或 `6001 open` 其中一个：

```text
22    open   SSH login
6000  open   Built-in Rosmaster app control
```

如果当前结果是：

```text
6000  closed
6001  open
```

也可以直接用 `6001` 启动后端。`6001` 是我们自建 Rosmaster 桥接，已经能接 Web 遥控指令。

### 4.2 根据检查结果启动本地 Web 后端

如果 `6000 open`，执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6000
```

如果 `6000 closed` 但 `6001 open`，执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6001
```

如果 `6000` 和 `6001` 都是 closed，先启动备用桥接：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_rosmaster_bridge_ssh.ps1 -CarHost "192.168.137.173"
```

然后重新检查，看到 `6001 open` 后，用 `6001` 启动后端。

### 4.3 视觉画面端口

当前 Web 视觉页默认使用小车原生 App 的 `6500` 实时画面：

```text
http://小车IP:6500/video_feed
```

如果 `6500` 不稳定或暂时没有画面，页面会自动尝试自建 `8080` 备用摄像头流：

```text
http://小车IP:8080/?action=stream
```

如果手机或浏览器不能直连小车，会继续尝试后端代理地址：

```text
/api/camera/stream?host=小车IP&port=6500&path=%2Fvideo_feed
```

如果 `8080 closed` 且 `6500` 画面不稳定，可以在电脑 PowerShell 里执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_camera_ssh.ps1 -CarHost "192.168.137.173"
```

这个脚本会通过 SSH 把项目里的轻量 MJPEG 服务复制到小车并启动：

```text
robot/camera_mjpeg_server.py -> /home/jetson/icar_camera_mjpeg_server.py
```

启动后再检查一次：

```powershell
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

备用服务启动成功后应看到 `8080 open`。备用直连地址是：

```text
http://小车IP:8080/?action=stream
```

如果 `8080` open 但只有 1x1 占位图，通常是原生 `app.py` 已占用 `/dev/video0`，这时优先使用 `6500/video_feed`。如果 `8080` 仍然 closed，需要看脚本提示的 `/tmp/icar_camera_mjpeg_server.log`。

如果想试小车自带的 Flask/camera 服务，也可以再执行：

```powershell
.\scripts\start_car_builtin_app_ssh.ps1 -CarHost "192.168.137.173"
```

后端启动成功后，电脑浏览器打开：

```text
http://127.0.0.1:8000/control
```

脚本还会打印手机可访问的局域网地址，例如：

```text
http://192.168.137.1:8000/control
```

把这条网址发到手机微信里，手机和电脑、小车在同一个热点时，手机点开就可以控制小车。

### 4.4 查看当前有哪些 Docker 容器

热点重新连上后，在项目根目录执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_bridge_ssh.ps1 -ListContainers
```

这一步不会启动桥接，只会列出候选容器。

如果想手动查看，也可以直接执行：

```powershell
ssh jetson@172.20.10.3 "docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'"
```

### 4.4 启动 Docker 映射模式桥接

如果你要做建图、键盘控制、ROS2 `/cmd_vel` 这一类流程，再执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_bridge_ssh.ps1 -Mode mapping
```

脚本会自动完成这些动作：

- 把 `robot/icar_tcp_bridge.py` 复制到小车
- 自动找到合适的 Docker 容器
- 启动容器
- 停掉旧的串口桥接
- 在容器里执行 `m1`
- 在容器里启动 TCP 到 ROS2 `/cmd_vel` 的桥接服务

### 4.5 启动 Docker 导航模式桥接

如果你要走导航链路，执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_bridge_ssh.ps1 -Mode navigation
```

它和上面类似，只是会在容器里执行 `n1`。

### 4.6 手动指定容器

如果自动识别到了多个容器，或者你明确知道该用哪一个，可以手动指定：

```powershell
.\scripts\start_car_bridge_ssh.ps1 -Container 12ab34cd56ef -Mode mapping
```

## 5. 调试命令

### 5.1 一键检查端口

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

如果 `6000 open`，说明 Web 后端可以连到小车原生控制服务。
如果只有 `ping` 通但 `6000 closed`，Web 会显示 `offline`，需要先在小车端启动原生 app/control 服务，或检查热点是否刚重连导致服务掉线。

### 5.2 查看 Docker 桥接日志

```powershell
ssh jetson@192.168.137.173 "docker exec <容器ID> bash -lc 'tail -n 40 /tmp/icar_tcp_bridge.log /tmp/icar_launch.log 2>/dev/null'"
```

### 5.3 检查当前 ROS 话题

```powershell
ssh jetson@192.168.137.173 "docker exec <容器ID> bash -lc 'ros2 topic list'"
```

如果后面要进一步排查 `/cmd_vel`，这个命令很有用。

## 6. 如果暂时不连真车

如果热点没开，或者小车暂时不在手边，组员可以先跑模拟模式：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend.ps1
```

这时 Web 会用模拟数据跑起来，适合前端、报告、告警、页面联调。

## 7. 为什么不再推荐直接串口桥接

之前我们试过 `icar_tcp_serial_bridge.py`，可以收到 Web 发来的控制帧，但小车没有实际运动。  
这说明“TCP 数据到小车宿主机”是通的，但没有走手册 3.7 里的正式 ROS2 控制链路。

所以现在统一改成：

- Web -> TCP 6000
- TCP 桥接 -> Docker 容器中的 ROS2 `/cmd_vel`
- 小车底盘 -> 按手册已有控制链路执行

这个方案更接近老师手册里的实际运行方式。

## 8. VMware 现在的作用

VMware 依然有用，只是作用变成：

- Ubuntu 20.04 + ROS2 Foxy：熟悉 ROS2 指令，做导航逻辑开发
- Ubuntu 22.04 + ROS2 Humble：完成后续仿真实验
- Windows 本机：运行 Web、后端、文档、数据库和 Git

也就是说，真车联调不是每个人都必须一直占着小车做。

## 9. 常见问题

### Q1：脚本提示没有匹配到容器

先执行：

```powershell
.\scripts\start_car_bridge_ssh.ps1 -ListContainers
```

如果还是没有结果，说明：

- 热点还没连好
- 小车没开机
- Docker 容器名称或镜像名和当前过滤规则不一致

这时直接手工看：

```powershell
ssh jetson@172.20.10.3 "docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'"
```

### Q2：Web 页面能打开，但小车不动

优先检查三件事：

1. `6000` 端口是否真的通了
2. 桥接是否在 Docker 容器里启动成功
3. 容器里的底盘控制链路是否已经按手册启动

### Q3：NoMachine 还用不用

还能用，但只建议在这些时候用：

- 看 RViz
- 看桌面程序
- 非要图形界面操作时

正常启停桥接和控制链路，优先用 SSH。

## 10. 小车断电后的恢复步骤

如果小车没电，`SSH`、`NoMachine`、`TCP 6000/6001` 都会直接超时，这时候先不要继续传文件或反复点网页控制。

建议按下面顺序恢复：

1. 先给小车充电，确认能正常开机。
2. 让电脑和小车重新连接到同一个热点。
3. 先测试网络是否恢复：

```powershell
ping 192.168.137.173
powershell -Command "Test-NetConnection 192.168.137.173 -Port 22"
```

4. 如果 `22` 端口通了，优先检查原生 `6000` 控制端口：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

只要看到 `6000 open` 或 `6001 open`，就可以按检查脚本推荐的端口启动 Web 后端。

5. 然后在另一个 PowerShell 启动本地后端：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6000
```

6. 浏览器打开：

```text
http://127.0.0.1:8000/control
```

7. 如果页面能打开但车不动，先重新检查端口：

```powershell
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

重点看三件事：

- `22` 是否 open，表示 SSH 可达
- `6000` 是否 open，表示小车原生控制服务可达
- 后端窗口是否显示连接到了 `192.168.137.173:6000`

## 11. 手机打开网页控制小车

可以实现，推荐用于演示。

条件：

1. 电脑、手机、小车连接同一个热点
2. 电脑运行 `icar-smart-home` 后端
3. 小车桥接已经正常启动

推荐流程：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend.ps1
```

现在 Windows 启动脚本会默认监听 `0.0.0.0`，并自动打印可访问的网址，例如：

```text
http://192.168.137.1:8000/control
```

把这条网址发到微信里，手机点开即可。

说明：

- 手机页面会自动使用当前网页地址对应的 WebSocket，不再写死 `127.0.0.1`
- 所以只要手机能打开 `http://电脑IP:8000/control`，页面里的连接默认就是对的
- 如果 Windows 防火墙弹窗，记得允许“专用网络”访问

如果手机能打开网页但控制无反应，优先检查：

1. 小车是否已经连上同一个热点
2. 电脑后端的 `ICAR_CAR_HOST` 是否是当前小车 IP
3. 车端 `6000` 原生控制端口是否 open

## 12. 推荐：不用 Docker 的 Rosmaster SSH 桥接

如果只是要让 Web 控制小车前进、后退、左转、右转和停止，按检查脚本推荐选择 `6000` 或 `6001`。当前 `6000 closed` 但 `6001 open` 时，直接使用 `6001`。

这套方式复用小车自带的控制程序目录：

```text
/home/jetson/Rosmaster-App/rosmaster
```

小车自带命令实际含义：

```bash
ros  # cd /home/jetson/Rosmaster-App/rosmaster
app  # cd /home/jetson/Rosmaster-App/rosmaster; python3 app_sim_run.py
```

`app_sim_run.py` 里按钮实际调用的是 `rosmaster_test.py` 和 `Rosmaster_Lib`，所以我们新增了一个轻量桥接脚本：

```text
robot/rosmaster_tcp_bridge.py
```

它会在小车上启动一个 `TCP 6001` 服务，收到 Web 发来的控制帧后，直接调用 `Rosmaster_Lib` 控制底盘。如果小车原生 `6000` 没开，但 `6001` 已经 open，就直接让后端连接 `6001`。

### 12.1 备用：启动车端 Rosmaster 桥接

当前小车 IP 是 `192.168.137.173` 时，在 Windows PowerShell 执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_rosmaster_bridge_ssh.ps1 -CarHost "192.168.137.173"
```

脚本会自动完成：

- 通过 SSH 连接小车
- 把 `robot/rosmaster_tcp_bridge.py` 复制到小车
- 停掉旧的 Web 控制桥接进程
- 启动新的 Rosmaster TCP 桥接
- 检查 `192.168.137.173:6001` 是否打开

如果小车 IP 变了，只需要改 `-CarHost`：

```powershell
.\scripts\start_car_rosmaster_bridge_ssh.ps1 -CarHost "新的小车IP"
```

### 12.2 启动本地 Web 后端

另开一个 PowerShell：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6000
```

然后打开：

```text
http://127.0.0.1:8000/control
```

手机端访问时，使用 `start_backend_car_ssh.ps1` 打印出来的局域网网址，例如：

```text
http://192.168.137.1:8000/control
```

### 12.3 查看车端桥接日志

如果网页能打开但小车不动，先看日志：

```powershell
ssh jetson@192.168.137.173 "tail -n 80 /tmp/icar_rosmaster_tcp_bridge.log"
```

正常情况下，点击 Web 前进按钮后会看到类似：

```text
command from ('192.168.137.1', 端口): forward
```

### 12.4 控制方向映射

| Web 按钮 | Rosmaster 指令 |
| --- | --- |
| 前进 | `set_car_run(1, speed)` |
| 后退 | `set_car_run(2, speed)` |
| 左转 | `set_car_run(6, speed)` |
| 右转 | `set_car_run(5, speed)` |
| 停止/急停 | `set_car_run(0, 0)` |

说明：Docker/ROS2 桥接方式仍然保留，后续做 SLAM 建图和导航时可能还会用到；但 Web 手动遥控优先使用 Rosmaster SSH 桥接。

## 13. 从学长学姐 App 迁移进来的 3 个功能

本次已经把参考 App 中最适合直接迁移的 3 个点接入本项目：

1. 速度控制：Web 遥控页的速度滑块不再只是前端显示。后端会先发送速度帧，再发送前进/后退/转向帧。
2. 摄像头流：视觉页现在默认使用小车原生 App 直连 `http://小车IP:6500/video_feed`，打开最快；自建 `http://小车IP:8080/?action=stream` 和后端代理 `/api/camera/stream?...` 作为备用。
3. 外设与模式：遥控页新增灯光、短蜂鸣、循迹按钮。灯光会优先通过 SSH 在小车上直接调用 `Rosmaster_Lib.set_colorful_lamps`，并同时发送 `0x30/0x31` 和学长学姐 App 中的 `0x20` 兼容帧；短蜂鸣直接走小车蜂鸣器协议，适合现场确认指令已经发到小车。

### 13.1 真车使用流程

先检查端口，按脚本推荐使用 `6000` 或 `6001`：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

如果脚本推荐 `6001`，就执行：

```powershell
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6001
```

如果 `6500` 画面不稳定，先启动备用摄像头服务：

```powershell
.\scripts\start_car_camera_ssh.ps1 -CarHost "192.168.137.173"
```

然后打开：

```text
http://127.0.0.1:8000/control
http://127.0.0.1:8000/vision
```

手机演示时使用启动脚本打印出来的局域网地址，例如：

```text
http://192.168.137.1:8000/control
http://192.168.137.1:8000/vision
```

### 13.2 备用 6001 桥接

如果不用小车原生 `6000`，也可以启动备用桥接：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_rosmaster_bridge_ssh.ps1 -CarHost "192.168.137.173"
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6001
```

备用桥接现在也能识别速度、灯光、蜂鸣器和循迹帧。原生 `6000` 端口优先级更高；灯光控制现在会同时走 SSH 直调 Rosmaster 和 TCP 兼容帧，循迹开启/关闭分别使用 `0x63/0x64`。

### 13.3 不连真车的快速测试

只验证代码和接口是否正常时，运行：

```powershell
cd F:\北交大2周项目\icar-smart-home
python .\scripts\test_migrated_features.py
```

通过时会看到：

```text
Migrated feature test passed.
Checked: camera candidates, speed TCP frames, light, buzzer, follow-line, SLAM helpers.
```

## 14. 实车 SLAM 建图与自动导航（yyh 分支）

当前 `yyh` 分支已经把课程 6.1/6.2 的实车 SLAM/Navigation2 流程接入 Web。这个功能不是原来导航页里的模拟家庭地图，而是通过 SSH 到小车，在小车 Docker 里的 ROS2 Foxy 环境启动真实建图和导航节点。

### 14.1 端口约定

| 端口 | 用途 | 说明 |
| --- | --- | --- |
| `22` | SSH | Web 后端通过 SSH 启动小车 ROS2/Docker 任务 |
| `6000` | 小车原生 Rosmaster 控制 | Web 遥控、建图遥控默认使用这个端口 |
| `6500` | 小车原生 App 摄像头 | 视觉页面默认直连 `http://小车IP:6500/video_feed` |
| `6001` | 自建 Rosmaster 备用桥 | 只在 `6000` 不可用时作为备选 |
| `8000` | 本地 Web 后端 | 手机访问 `http://电脑IP:8000/control`、`/vision` 或 `/navigation` |

### 14.2 启动 Web 后端

小车当前 IP 例如 `192.168.137.173` 时，在 Windows PowerShell 执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6000
```

电脑浏览器打开：

```text
http://127.0.0.1:8000/navigation
```

正常页面顶部应该显示：

```text
SLAM Navigation v3
激光 SLAM 建图与自动导航
```

手机同热点访问时，用启动脚本打印出的电脑热点地址，例如：

```text
http://192.168.137.1:8000/navigation
```

如果端口 `8000` 被占用，按启动脚本提示执行：

```powershell
Stop-Process -Id <脚本提示的PID>
```

然后重新启动后端，并在浏览器按 `Ctrl+F5` 强制刷新 `/navigation`。

### 14.3 Web 页面里的操作顺序

建图流程：

1. 打开 `/navigation`。
2. 点击“检查连接”，确认 `22`、`6000` 和 ROS2 容器状态。
3. 点击“开始建图”，后台会启动 `gmapping`。
4. 使用页面右侧“建图遥控器”慢速移动小车，让激光雷达扫描环境。每次按键是短脉冲，松手或切出页面会自动停车。
5. 在“新地图名”输入框里填地图名，例如 `yahboomcar_web`。
6. 点击“保存地图”，生成 `.yaml/.pgm` 地图文件。

导航流程：

1. 在地图下拉框里选择 `yahboomcar.yaml`、`yahboomcar2.yaml` 或刚保存的地图。
2. 选择导航算法，默认推荐 `DWA`，也可以切换到 `TEB`。
3. 点击“启动导航”，后台会启动雷达 bringup 和 Navigation2。
4. 第一次导航前，点击“点选当前位置/起点”，在地图上点小车真实所在位置，绿色点就是当前位置。
5. 根据小车真实朝向填 `θ`，然后点击“确认当前位置”。这一步会连续发布 `/initialpose`，并等待 AMCL 或 TF 回传地图坐标。
6. 点击“新增目标点”，再点击“点选目标点”，在地图上点要去的位置。目标 A/B/C 会使用不同颜色显示，也可以在 `θ` 输入框里设置到达该点时的朝向。
7. 在目标点列表里选择要去的目标，例如“目标 A”，点击“去目标点”。Web 会先把绿色当前位置作为 `initial_pose` 再发布一次，确认 AMCL/TF 已经知道小车当前位置后，才会发布 `/goal_pose`。如果定位失败，目标点不会发送，小车也不会盲动。
8. 小车到达目标点后，不要直接把上一次到达位置当成下一次起点。先点击“同步小车当前位姿”，或者切到“点选当前位置/起点”在地图上重新点绿色位置，再按实际情况微调 `X/Y/θ`。
9. 点击“确认当前位置”，确认 AMCL/TF 已经接受新的起点后，再选择目标 B 或目标 C 并点击“去目标点”。
10. 需要停止时点击“停止 SLAM/导航”，紧急情况点“急停”。

### 14.4 起点、终点和 AMCL 的关系

绿色点表示“Web 认为的小车当前位姿/起点”。目标 A/B/C 会用不同颜色显示，白色外圈表示当前选中的目标点。

SLAM 建图主要靠激光雷达和里程计生成 2D 栅格地图，不是靠摄像头和旧地图画面做重叠比对。导航时 Navigation2 会加载保存好的地图，AMCL 会结合雷达扫描和地图来估计小车当前在地图中的位置。

如果日志里出现下面这些内容：

```text
Please set the initial pose
Invalid frame ID "map"
Timed out waiting for transform from base_footprint to map
```

通常不是程序坏了，而是导航已经启动，但 AMCL 还没有收到初始位姿。处理方式是：在地图上点小车当前真实位置，填好朝向 `θ`，再点“确认当前位置”。第一次加载一张保存好的地图时，系统不能凭空知道“小车在这张旧地图里的绝对位置”；只有建图过程仍在运行、AMCL 已经定位成功，或者你给过一次初始位姿以后，Web 才能直接同步当前位姿。

### 14.5 多目标点连续导航

现在导航页支持多个目标点：

1. 点击“新增目标点”，会生成目标 A/B/C 等候选点。
2. 选中某个目标后，在地图上点击位置，目标点会用不同颜色显示。
3. `θ` 输入框表示该目标点的到达朝向；修改 `θ` 后会同步到当前选中的目标点。
4. 点击“去目标点”后，Web 会发送当前选中的目标点。
5. 到达目标点附近后，Web 只会轮询当前位置并给出距离提示，不会自动把当前位置写成下一次导航起点。
6. 去下一个目标前，先用“同步小车当前位姿”或地图点选重新设置绿色起点，必要时手动微调 `X/Y/θ`。
7. 点击“确认当前位置”后，再发送下一个目标点。

也就是说，每次从目标 A 去目标 B、从目标 B 去目标 C 前，都建议重新确认一次绿色当前位置。这样虽然多一步，但能避免 AMCL 估计偏差被连续放大。

### 14.6 后台实际执行的 ROS2 命令

Web 后端会通过 SSH 创建或复用一个常驻 Docker 容器：

```text
icar_web_nav
```

容器镜像：

```text
yahboomtechnology/ros-foxy:5.0.1
```

建图对应课程 6.1：

```bash
ros2 launch yahboomcar_nav map_gmapping_launch.py
ros2 launch yahboomcar_nav save_map_launch.py map_path:=/root/yahboomcar_ros2_ws/yahboomcar_ws/src/yahboomcar_nav/maps/<地图名>
```

导航对应课程 6.2：

```bash
ros2 launch yahboomcar_nav laser_bringup_launch.py
ros2 launch yahboomcar_nav navigation_dwa_launch.py map:=/root/yahboomcar_ros2_ws/yahboomcar_ws/src/yahboomcar_nav/maps/<地图名>.yaml
```

也支持：

```bash
ros2 launch yahboomcar_nav navigation_teb_launch.py map:=...
```

Web 会读写这些 ROS2 topic：

```text
/initialpose  geometry_msgs/msg/PoseWithCovarianceStamped
/goal_pose    geometry_msgs/msg/PoseStamped
/amcl_pose    geometry_msgs/msg/PoseWithCovarianceStamped
```

### 14.7 地图文件位置

小车地图目录：

```text
/home/jetson/code/yahboomcar_ws/src/yahboomcar_nav/maps
```

当前常见地图：

```text
yahboomcar.yaml
yahboomcar2.yaml
```

Web 后端会把 `.pgm/.yaml` 读取回来，转换成浏览器可显示的 PNG，缓存到：

```text
data/slam_maps/
```

### 14.8 调试命令

查看 Web 端认为的 SLAM 状态：

```powershell
curl http://127.0.0.1:8000/api/slam/status
```

查看车端日志：

```powershell
curl http://127.0.0.1:8000/api/slam/logs
```

查看 AMCL 当前位姿：

```powershell
curl http://127.0.0.1:8000/api/slam/pose/current
```

### 14.9 `bt_navigator` 崩溃或目标点发送后不动

如果日志里出现下面任意一种内容：

```text
Action server failed while executing action callback: "send_goal failed"
process has died [bt_navigator ... exit code -11]
Action servers: 0
```

说明 Web 已经把目标点发给 Navigation2，但车端 Nav2 的 `bt_navigator` 没有稳定执行目标，或者 `/navigate_to_pose` action server 已经消失。这个时候问题不是“目标点坐标没有发出去”，而是车端 ROS2 导航进程状态已经不干净。

现在 Web 的“启动导航”步骤已经做了额外保护：

1. 先停止旧的 SLAM/Nav2/laser bringup 相关进程。
2. 自动重启我们自己的 `icar_web_nav` Docker 容器，清理僵尸进程和重复 ROS2 节点。
3. 再启动 `laser_bringup_launch.py` 和 `navigation_dwa_launch.py`。
4. 等 `/navigate_to_pose` 变成 `Action servers: 1`，并确认 `bt_navigator` active 后，才认为导航系统就绪。

导航页“运行状态”里会显示：

```text
Nav2 action: /navigate_to_pose ready
bt_navigator: active
```

只有看到这两个状态正常后，再执行：

1. 点选当前位置/起点。
2. 点击“确认当前位置”。
3. 点选目标点。
4. 点击“去目标点”。

如果页面提示 `bt_navigator crashed` 或 `Nav2 action not ready`，不要继续反复点击“去目标点”，先重新点击“启动导航”，等状态恢复后再发送目标点。

手动查看 Docker 容器：

```powershell
ssh jetson@192.168.137.173 "docker ps -a --filter name=icar_web_nav"
```

如果导航页报错，优先检查：

1. `22` 是否 open。
2. 小车是否连接了雷达和底盘线。
3. `icar_web_nav` 是否 running。
4. `/api/slam/logs` 里是否有 `yahboomcar_nav`、`rplidar`、`map_server`、`nav2` 相关错误。
