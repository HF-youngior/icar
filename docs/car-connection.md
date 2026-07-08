# 小车连接、VMware 测试与真车联调说明

## 1. NoMachine、SSH、Web 系统分别是什么

| 工具 | 作用 | 是否是本项目必须 |
| --- | --- | --- |
| NoMachine | 远程进入小车 Ubuntu 桌面，适合看 RViz、终端和图形界面 | 调试时常用，但 Web 系统不依赖它 |
| SSH | 远程进入小车命令行，适合启动容器、启动 ROS2、查看日志 | 推荐掌握，稳定性通常比远程桌面好 |
| Web 控制台 | 我们自己做的上位机，用浏览器遥控、导航、看状态和告警 | 项目主交付 |
| VMware Ubuntu | 在电脑上模拟/开发 ROS2、后端、Web，不占用真车 | 多人协作时很有用 |

## 2. 当前项目的三种运行模式

### 模式 A：模拟模式

默认模式，不连接真车。适合所有组员在自己电脑或 VMware 中开发页面、接口、报告和演示流程。

```powershell
cd F:\北交大2周项目\icar-smart-home
.\scripts\start_backend.ps1
```

浏览器打开：

```text
http://127.0.0.1:8000
```

### 模式 B：TCP 真车模式

参考鸿蒙 APP 资料，小车 TCP 端口为 `6000`，控制帧格式类似：

```text
$011504011B#
```

含义：`cmd 15` 按钮控制，方向 `01` 表示前进。  
本项目后端已经实现了该协议的基础方向控制。

启动方式：

```powershell
$env:ICAR_CAR_ADAPTER="tcp"
$env:ICAR_CAR_HOST="172.20.10.3"
$env:ICAR_CAR_PORT="6000"
.\scripts\start_backend.ps1
```

其中 `172.20.10.3` 要换成你们当时小车实际 IP。

### 模式 C：ROS2 真车模式

适合在小车 Jetson、Docker 容器或 Ubuntu 20.04 + ROS2 Foxy 环境中运行。

```bash
source /opt/ros/foxy/setup.bash
export ICAR_CAR_ADAPTER=ros2_cli
./scripts/start_backend.sh
```

后端会发布：

```bash
/cmd_vel
/goal_pose
```

前提是小车底盘、雷达、导航栈已经按手册启动。

## 3. SSH 怎么连小车

如果小车 IP 是 `172.20.10.3`：

```bash
ssh jetson@172.20.10.3
```

密码通常是：

```text
yahboom
```

老师群里发的示例：

```bash
ssh jetson@192.168.43.60
```

这里的 `192.168.43.60` 只是那一次网络里的 IP。你们换热点、换手机、换有线网络后，IP 会变，必须用当前小车显示或路由器里看到的 IP。

如果 Windows 想使用 `sshpass`，老师发的命令是为了免手输密码：

```powershell
winget install --id=xhcoding.sshpass-win32 -e
```

也可以不用 `sshpass`，直接执行 `ssh jetson@小车IP`，然后手动输入密码。

## 4. 热点为什么容易卡

手机热点通常有几个问题：

1. 小车、电脑、VMware 都抢同一个无线链路，延迟会飘。
2. NoMachine 是图形远程桌面，带宽占用比 SSH 大。
3. ROS2 DDS 对网络发现和组播比较敏感，NAT/热点隔离可能导致发现不稳定。
4. 一台小车通常只能给一组人真机联调，其他人同时连会互相影响。

建议：

1. 真车调试时尽量少开 NoMachine，多用 SSH。
2. Web 页面和后端可以先在模拟模式跑，只有控制和导航最后再接真车。
3. 真车演示前录制一段视频，避免现场网络断开。

## 5. VMware 有什么用

VMware 不是为了替代小车，而是为了让大家不用抢真车也能开发：

| VMware 环境 | 用途 |
| --- | --- |
| Ubuntu 20.04 + ROS2 Foxy | 最接近小车 ROS2 Foxy 环境，适合测试 ROS2 命令、后端 `ros2_cli` 适配 |
| Ubuntu 22.04 + ROS2 Humble | 适合老师要求的仿真实验，和后续算法/仿真练习 |
| Windows 主机 | 适合跑 Web 前端、FastAPI 后端模拟模式、写文档和推送 GitHub |

如果多人分工：

- Web 同学：直接 Windows 或 VMware 模拟模式即可。
- 传感器/告警同学：直接模拟数据即可。
- Yolo 同学：可在有 GPU 的电脑训练，或先用预训练模型和图片测试。
- 导航同学：用 VMware Foxy 熟悉 ROS2 命令，真车空闲时再验证 `/cmd_vel`、`/goal_pose`。

## 6. 我们 Web 能不能替代鸿蒙 APP

可以。鸿蒙 APP 的核心也是：

1. 连接小车 IP 和 TCP 端口。
2. 把按钮/摇杆转换成小车控制协议。
3. 显示视频或状态。

我们做 Web 的好处是：

1. 不需要鸿蒙测试机。
2. 电脑、iPhone 浏览器都可以访问。
3. 更容易和 ROS2、Yolo、报告、GitHub 结合。

当前 Web 已经实现模拟控制和 TCP/ROS2 接口预留，后续只要确认真车当前启动的是哪种服务，就能逐步替换模拟适配器。

