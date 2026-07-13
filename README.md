# 智能家居管家机器人 Web 控制系统

本目录是“智能家居管家机器人系统”的代码工程。项目采用前后端分离但轻量部署的结构：

- 后端：Python + FastAPI + WebSocket，负责平台基础、状态汇总、模拟/真实小车适配、导航任务、传感器、告警和报告。
- 前端：原生 HTML/CSS/JavaScript，无需 Node 构建，便于在 Windows、Ubuntu 20.04 ROS2 Foxy、Ubuntu 22.04 ROS2 Humble 或 Jetson 上快速打开演示。
- 默认模式：`simulated`，不需要连接小车也能演示 Web 控制台。
- 真车模式：预留 `ros2_cli` 和 `tcp` 适配器，后续根据小车实际 ROS2 话题或 TCP 协议切换。

## 1. 为什么不优先用 Spring Boot

本项目后续要接 ROS2、Jetson、Yolo、传感器和小车控制。ROS2 的 Python 生态和命令行工具更贴近小车开发环境，用 FastAPI 做桥接层会比 Spring Boot 更直接。Spring Boot 适合企业后台，但本实训的重点是机器人通信、导航、AI 推理和 Web 上位机，Python 后端能减少胶水代码。

## 2. 目录结构

```text
icar-smart-home/
  backend/                 后端服务
    app/
      adapters/            小车适配器：模拟、TCP、ROS2 CLI
      main.py              FastAPI 入口
      navigation.py        导航任务状态机
      sensors.py           传感器模拟与阈值告警
      vision.py            视觉事件模拟入口
      state.py             全局状态与 WebSocket 广播
  config/
    app.example.json       主配置模板
    points.json            家庭点位配置
    routes.json            巡逻路线配置
  frontend/                Web 控制台
  scripts/                 启动与检查脚本
  docs/                    接口、部署、测试文档
  data/                    运行时报告、日志、截图
```

## 3. 本地模拟运行

### Windows PowerShell

```powershell
cd F:\北交大2周项目\icar-smart-home
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
.\scripts\start_backend.ps1
```

浏览器打开：

```text
http://127.0.0.1:8000
```

说明：启动脚本运行后会停在终端里，这是正常现象，表示 Web 服务正在运行。不要把它当作卡住；需要停止时按 `Ctrl+C`，或另开一个 PowerShell 执行：

```powershell
.\scripts\stop_backend.ps1
```

Windows 脚本默认监听 `127.0.0.1:8000`，适合本机浏览器开发。如果要让同一热点/局域网内的其他设备访问，可先执行：

```powershell
$env:ICAR_HOST='0.0.0.0'
.\scripts\start_backend.ps1
```

脚本默认不开 `--reload`，减少多进程和端口占用问题。需要开发热重载时可设置：

```powershell
$env:ICAR_RELOAD='1'
.\scripts\start_backend.ps1
```

### Ubuntu / Jetson

```bash
cd /path/to/icar-smart-home
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
./scripts/start_backend.sh
```

启动后可以运行一次冒烟测试：

```bash
python scripts/smoke_test.py
```

也可以运行不依赖真实小车和数据库的自动化单元测试：

```bash
python -m unittest discover -s tests -v
```

## 4. 接真车的两种方式

### 方式 A：ROS2 CLI 适配器

适合在 Ubuntu 20.04 + ROS2 Foxy 的虚拟机、小车 Jetson 或小车 Docker 容器中运行。

```bash
source /opt/ros/foxy/setup.bash
export ICAR_CAR_ADAPTER=ros2_cli
./scripts/start_backend.sh
```

该模式会用 `ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist ...` 发布速度命令。导航目标默认发布到 Nav2/RViz 常见的 `/goal_pose` 话题，实际是否可用取决于小车导航栈是否已启动。

### 方式 B：TCP 适配器

如果小车已有 TCP 控制服务，可在 `config/app.example.json` 中配置 IP、端口和命令模板：

```bash
export ICAR_CAR_ADAPTER=tcp
export ICAR_CAR_HOST=172.20.10.3
export ICAR_CAR_PORT=6000
./scripts/start_backend.sh
```

TCP 协议参考鸿蒙 APP 课程材料：端口 `6000`，按钮控制为 `cmd 15`，帧格式形如 `$011504011B#`。本项目已经实现基础方向控制。

## 5. 可选数据库

默认不启用数据库，所有演示功能都可以在本地模拟状态下运行。需要把告警、报告、视觉事件和传感器采样写入腾讯云 MySQL 时，先设置环境变量再启动后端：

```powershell
$env:ICAR_DB_HOST='bj-cynosdbmysql-grp-4ra8jiia.sql.tencentcdb.com'
$env:ICAR_DB_PORT='27180'
$env:ICAR_DB_USER='root'
$env:ICAR_DB_PASSWORD='你的数据库密码'
$env:ICAR_DB_NAME='icar'
.\scripts\start_backend.ps1
```

连通性检查：

```powershell
python -X utf8 scripts\db_check.py
```

数据库密码不要写入 Git；项目只提交配置模板和说明。

## 6. 页面入口

| 页面 | 地址 |
| --- | --- |
| 总览 | `http://127.0.0.1:8000/dashboard` |
| 遥控 | `http://127.0.0.1:8000/control` |
| 导航 | `http://127.0.0.1:8000/navigation` |
| 视觉 | `http://127.0.0.1:8000/vision` |
| 告警 | `http://127.0.0.1:8000/alarms` |
| 报告 | `http://127.0.0.1:8000/reports` |

## 7. 当前已实现功能

- Web 控制台首页、连接状态、手动遥控、急停、速度档位。
- 房间点位列表、单点导航、巡逻路线、导航状态和模拟地图。
- 传感器面板：温度、湿度、光照、可燃气体、PM2.5。
- 告警列表、告警确认、通信断开/传感器超阈值告警。
- 视觉事件模拟：人员、宠物、门窗等检测结果。
- 报告记录：导航到达、巡逻完成、告警事件。
- 接口文档、测试清单和启动脚本。
- 可选腾讯云 MySQL 持久化：告警、报告、视觉事件、传感器采样。

## 8. 推荐分工

- 同学 A：`backend/app/main.py`、`navigation.py`、`adapters/`
- 同学 B：`frontend/`
- 同学 C：`backend/app/vision.py`、后续真实 Yolo 脚本
- 同学 D：`backend/app/sensors.py`、告警规则、报告数据
- 同学 E：`docs/`、`scripts/`、README、测试和答辩材料

## 9. GitHub

目标仓库：

```text
git@github.com:HF-youngior/icar.git
```

建议确认本地 SSH key 已能访问 GitHub 后再推送。

## 10. 相关文档

| 文档 | 说明 |
| --- | --- |
| `docs/car-connection.md` | 小车连接、NoMachine、SSH、热点、有线和 VMware 测试说明 |
| `docs/database.md` | 腾讯云 MySQL 环境变量、建表和连通性检查 |
| `docs/cloud-ci.md` | 腾讯云数据库、腾讯云语音识别、大模型和 GitHub Actions CI/CD 说明 |
| `docs/interface.md` | WebSocket 和 HTTP 接口 |
| `docs/test-plan.md` | 功能测试和真车联调测试清单 |
| `vision/README.md` | YOLOv5 训练、推理和 Jetson 部署说明 |
