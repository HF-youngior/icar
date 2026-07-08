# 模块接口说明

后端提供 HTTP API 和 WebSocket 两类接口。WebSocket 用于实时控制和状态推送，HTTP API 用于调试和非实时操作。

## WebSocket

地址：

```text
ws://127.0.0.1:8000/ws
```

### Web 到后端

```json
{
  "type": "manual_control",
  "payload": {
    "direction": "forward",
    "speed": 0.16
  }
}
```

```json
{
  "type": "nav_goal",
  "payload": {
    "point_id": "kitchen"
  }
}
```

```json
{
  "type": "patrol_start",
  "payload": {
    "route_id": "night_watch"
  }
}
```

```json
{
  "type": "emergency_stop",
  "payload": {
    "reason": "web"
  }
}
```

### 后端到 Web

```json
{
  "type": "navigation_status",
  "payload": {
    "task_id": "nav-xxxx",
    "state": "running",
    "target": {"id": "kitchen", "name": "厨房"},
    "progress": 0.42,
    "message": "正在前往厨房"
  }
}
```

```json
{
  "type": "sensor_update",
  "payload": {
    "name": "pm25",
    "label": "PM2.5",
    "value": 35,
    "unit": "ug/m3",
    "level": "normal"
  }
}
```

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/snapshot` | 获取完整当前状态 |
| GET | `/api/points` | 获取家庭点位 |
| GET | `/api/routes` | 获取巡逻路线 |
| POST | `/api/control/manual` | 手动控制 |
| POST | `/api/control/emergency-stop` | 急停 |
| POST | `/api/navigation/goal` | 单点导航 |
| POST | `/api/navigation/patrol` | 巡逻路线 |
| POST | `/api/navigation/stop` | 停止导航 |
| POST | `/api/vision/detect` | 触发一次视觉检测 |
| POST | `/api/alarms/{alarm_id}/confirm` | 确认告警 |

