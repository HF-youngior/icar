# 小车连接说明

## 1. 现在推荐的连接方式

现在不再把 NoMachine 作为主流程。已经实测可用的推荐方式是：

1. 电脑和小车连接同一个热点或同一个局域网。
2. 确认小车原生 Rosmaster 控制服务 `6000` 端口可用。
3. 本地启动 Web 后端，网页通过 TCP 连接小车 `6000` 端口。
4. 手机、电脑、小车在同一个热点时，手机也可以打开电脑打印出的局域网网址进行控制。

这样做的好处是：

- 不需要一直开 NoMachine 桌面。
- 不依赖固定 Docker 容器 ID，例如之前的 `549b`。
- Web 遥控优先复用小车自带 `app` 控制链路，和在 NoMachine 里运行小车自带 app 的思路一致。
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
- Web 手动遥控优先连接小车原生 Rosmaster/app 控制端口 `6000`
- Docker/ROS2 容器方案仍保留，用于后续 SLAM、建图、导航链路联调

如果 IP 改了，只要把命令里的 `192.168.137.173` 换成当前 IP 即可。

## 4. 推荐操作流程

### 4.1 先检查小车连接状态

热点重新连上后，在项目根目录执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\check_car_connection.ps1 -CarHost "192.168.137.173"
```

正常情况下，手动遥控至少需要看到：

```text
22    open   SSH login
6000  open   Built-in Rosmaster app control
```

其中 `6000` 是当前 Web 遥控优先使用的端口。`6001` 是我们自建 Rosmaster 桥接的备用端口，关闭也不影响当前主流程。

### 4.2 启动本地 Web 后端

确认 `6000` 端口打开后，执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend_car_ssh.ps1 -CarHost "192.168.137.173" -CarPort 6000
```

然后电脑浏览器打开：

```text
http://127.0.0.1:8000/control
```

脚本还会打印手机可访问的局域网地址，例如：

```text
http://192.168.137.1:8000/control
```

把这条网址发到手机微信里，手机和电脑、小车在同一个热点时，手机点开就可以控制小车。

### 4.3 查看当前有哪些 Docker 容器

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

只要看到 `6000 open`，就可以直接启动 Web 后端。`6001` 是备用桥接端口，关闭不影响当前手动遥控主流程。

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

如果只是要让 Web 控制小车前进、后退、左转、右转和停止，优先使用小车原生 `6000` 端口。下面的自建 `6001` Rosmaster 桥接作为备用方案保留。

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

它会在小车上启动一个 `TCP 6001` 服务，收到 Web 发来的控制帧后，直接调用 `Rosmaster_Lib` 控制底盘。当前已验证成功的手机/Web 遥控主流程使用的是小车原生 `6000` 端口，不需要额外启动这个备用桥接。

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
| 停止/急停 | `set_car_run(7, 0)` |

说明：Docker/ROS2 桥接方式仍然保留，后续做 SLAM 建图和导航时可能还会用到；但 Web 手动遥控优先使用 Rosmaster SSH 桥接。
