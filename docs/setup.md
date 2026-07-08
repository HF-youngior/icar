# 部署与真车连接说明

## 1. 推荐运行位置

第一阶段建议在 Windows 或 VMware Ubuntu 中以模拟模式运行，验证 Web、导航状态、传感器、告警和视觉事件。

第二阶段接真车时有两种选择：

1. 后端运行在小车 Jetson 或小车 Docker 容器里，直接使用 ROS2。
2. 后端运行在 VMware Ubuntu 20.04 Foxy 中，与小车处于同一热点/局域网，通过 ROS2 或 TCP 连接小车。

## 2. ROS2 Foxy 环境

Ubuntu 20.04 对应 ROS2 Foxy。启动前需要：

```bash
source /opt/ros/foxy/setup.bash
```

如果使用小车 Docker 容器，需要先进入课程手册要求的容器，再启动小车底盘、雷达、建图或导航相关 launch 文件。

## 3. ROS2 CLI 模式

```bash
export ICAR_CAR_ADAPTER=ros2_cli
./scripts/start_backend.sh
```

手动遥控会发布 `/cmd_vel`：

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.16, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

导航会默认发布 Nav2/RViz 常见的 `/goal_pose`。如果小车手册中的目标点话题名称不同，需要修改：

```json
{
  "car": {
    "nav_goal_topic": "/goal_pose"
  }
}
```

## 4. TCP 模式

```bash
export ICAR_CAR_ADAPTER=tcp
export ICAR_CAR_HOST=172.20.10.3
export ICAR_CAR_PORT=8888
./scripts/start_backend.sh
```

TCP 命令模板在 `config/app.example.json` 中。拿到真实协议后优先改配置，不要大改 Web。

## 5. NoMachine 的作用

NoMachine 只是远程进入小车 Ubuntu 桌面，不是 Web 系统必须依赖的通信方式。Web 系统真正需要的是：

1. 电脑、VMware Ubuntu 和小车处在同一网络。
2. 后端能访问小车 ROS2/TCP 服务。
3. 浏览器能访问后端地址，例如 `http://小车IP:8000` 或 `http://虚拟机IP:8000`。
