# 小车连接说明

## 1. 现在推荐的连接方式

现在不再把 NoMachine 作为主流程。推荐方式是：

1. 电脑和小车连接同一个热点或同一个局域网。
2. 在 Windows PowerShell 里用 `SSH + Docker + 自动桥接脚本` 启动小车控制链路。
3. 本地启动 Web 后端，网页通过 TCP 连接小车。

这样做的好处是：

- 不需要一直开 NoMachine 桌面。
- 不依赖固定容器 ID，例如之前的 `549b`。
- 组员只需要 PowerShell 和 SSH，就能重复操作。

## 2. 为什么以前的 `549b` 不可靠

Docker 容器 ID 不是固定值。只要小车重新创建过容器、恢复过镜像，或者换过环境，容器 ID 就会变化。

所以现在脚本已经改成：

- 默认自动扫描小车上的 ROS/Foxy/Yahboom 相关容器。
- 优先选择正在运行的容器。
- 如果没有运行中的，再选第一个匹配到的容器。
- 也支持你手动传入 `-Container` 指定容器。

## 3. 先决条件

默认假设：

- 小车 IP：`172.20.10.3`
- 小车用户名：`jetson`
- 小车密码：`yahboom`
- 小车 ROS2 环境在 Docker 容器里，不在宿主机里
- 容器里可以使用手册中的别名，例如 `m1`、`n1`

如果 IP 改了，只要把命令里的 `172.20.10.3` 换成当前 IP 即可。

## 4. 推荐操作流程

### 4.1 查看当前有哪些容器

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

### 4.2 启动映射模式桥接

如果你要做建图、键盘控制这一类流程，执行：

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

### 4.3 启动导航模式桥接

如果你要走导航链路，执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_car_bridge_ssh.ps1 -Mode navigation
```

它和上面类似，只是会在容器里执行 `n1`。

### 4.4 手动指定容器

如果自动识别到了多个容器，或者你明确知道该用哪一个，可以手动指定：

```powershell
.\scripts\start_car_bridge_ssh.ps1 -Container 12ab34cd56ef -Mode mapping
```

### 4.5 启动本地 Web 后端

等小车桥接启动后，在另一个 PowerShell 窗口执行：

```powershell
cd F:\北交大2周项目\icar-smart-home
$env:ICAR_CAR_ADAPTER="tcp"
$env:ICAR_CAR_HOST="172.20.10.3"
$env:ICAR_CAR_PORT="6000"
.\scripts\start_backend.ps1
```

然后浏览器打开：

```text
http://127.0.0.1:8000/control
```

## 5. 调试命令

### 5.1 查看桥接日志

```powershell
ssh jetson@172.20.10.3 "docker exec <容器ID> bash -lc 'tail -n 40 /tmp/icar_tcp_bridge.log /tmp/icar_launch.log 2>/dev/null'"
```

### 5.2 检查 6000 端口是否打开

```powershell
powershell -Command "Test-NetConnection 172.20.10.3 -Port 6000"
```

如果 `TcpTestSucceeded : True`，说明 Web 后端可以连到小车控制桥。

### 5.3 检查当前 ROS 话题

```powershell
ssh jetson@172.20.10.3 "docker exec <容器ID> bash -lc 'ros2 topic list'"
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
