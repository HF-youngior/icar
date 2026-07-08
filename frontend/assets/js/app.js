const state = {
  ws: null,
  connected: false,
  snapshot: {
    robot: {},
    navigation: {},
    points: [],
    routes: [],
    sensors: [],
    vision: [],
    alarms: [],
    reports: [],
  },
};

const $ = (id) => document.getElementById(id);

const els = {
  serverInput: $("serverInput"),
  connectBtn: $("connectBtn"),
  disconnectBtn: $("disconnectBtn"),
  railDot: $("railDot"),
  railStatus: $("railStatus"),
  connectionState: $("connectionState"),
  robotMode: $("robotMode"),
  robotTarget: $("robotTarget"),
  batteryText: $("batteryText"),
  speedRange: $("speedRange"),
  speedValue: $("speedValue"),
  estopBtn: $("estopBtn"),
  stopTaskBtn: $("stopTaskBtn"),
  detectBtn: $("detectBtn"),
  pointList: $("pointList"),
  routeList: $("routeList"),
  navMessage: $("navMessage"),
  navProgress: $("navProgress"),
  navProgressText: $("navProgressText"),
  sensorGrid: $("sensorGrid"),
  alarmList: $("alarmList"),
  alarmSummary: $("alarmSummary"),
  visionList: $("visionList"),
  visionSummary: $("visionSummary"),
  visionImage: $("visionImage"),
  reportList: $("reportList"),
  map: $("homeMap"),
};

function connect() {
  if (state.ws) state.ws.close();
  const ws = new WebSocket(els.serverInput.value.trim());
  state.ws = ws;
  setConnection("connecting");

  ws.onopen = () => {
    state.connected = true;
    setConnection("online");
    send("ping", {});
  };

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    handleMessage(message.type, message.payload);
  };

  ws.onclose = () => {
    state.connected = false;
    setConnection("offline");
  };

  ws.onerror = () => setConnection("error");
}

function disconnect() {
  if (state.ws) state.ws.close();
  state.ws = null;
  state.connected = false;
  setConnection("offline");
}

function setConnection(status) {
  const labels = {
    online: "已连接",
    offline: "离线",
    connecting: "连接中",
    error: "连接失败",
  };
  els.connectionState.textContent = labels[status] || status;
  els.railStatus.textContent = labels[status] || status;
  els.railDot.classList.toggle("online", status === "online");
}

function send(type, payload = {}) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
  state.ws.send(JSON.stringify({ type, payload }));
  return true;
}

function handleMessage(type, payload) {
  if (type === "snapshot") {
    state.snapshot = payload;
  } else if (type === "robot_status") {
    state.snapshot.robot = payload;
  } else if (type === "navigation_status") {
    state.snapshot.navigation = payload;
  } else if (type === "sensor_update") {
    upsertByName(state.snapshot.sensors, payload);
  } else if (type === "vision_event") {
    state.snapshot.vision.unshift(payload);
    state.snapshot.vision = state.snapshot.vision.slice(0, 12);
  } else if (type === "alarm_event") {
    state.snapshot.alarms.unshift(payload);
    state.snapshot.alarms = state.snapshot.alarms.slice(0, 24);
  } else if (type === "alarm_update") {
    replaceById(state.snapshot.alarms, payload, "alarm_id");
  } else if (type === "report_created") {
    state.snapshot.reports.unshift(payload);
    state.snapshot.reports = state.snapshot.reports.slice(0, 16);
  }
  render();
}

function upsertByName(list, item) {
  const index = list.findIndex((entry) => entry.name === item.name);
  if (index >= 0) list[index] = item;
  else list.push(item);
}

function replaceById(list, item, key) {
  const index = list.findIndex((entry) => entry[key] === item[key]);
  if (index >= 0) list[index] = item;
}

function render() {
  const { robot, navigation, points, routes, sensors, vision, alarms, reports } = state.snapshot;
  els.robotMode.textContent = robot.mode || "--";
  els.robotTarget.textContent = robot.target || "无";
  els.batteryText.textContent = robot.battery ? `${robot.battery}%` : "--%";
  els.navMessage.textContent = navigation.message || "等待任务";
  const progress = Math.round((navigation.progress || 0) * 100);
  els.navProgress.style.width = `${progress}%`;
  els.navProgressText.textContent = `${progress}%`;
  renderPoints(points || []);
  renderRoutes(routes || []);
  renderSensors(sensors || []);
  renderVision(vision || []);
  renderAlarms(alarms || []);
  renderReports(reports || []);
  drawMap(points || [], robot.pose || {}, navigation.target);
}

function renderPoints(points) {
  els.pointList.innerHTML = "";
  points.filter((point) => point.enabled !== false).forEach((point) => {
    const button = document.createElement("button");
    button.innerHTML = `<strong>${point.name}</strong><span>${point.description || ""}</span>`;
    button.onclick = () => send("nav_goal", { point_id: point.id });
    els.pointList.appendChild(button);
  });
}

function renderRoutes(routes) {
  els.routeList.innerHTML = "";
  routes.forEach((route) => {
    const button = document.createElement("button");
    button.innerHTML = `<strong>${route.name}</strong><span>${route.description || ""}</span>`;
    button.onclick = () => send("patrol_start", { route_id: route.id });
    els.routeList.appendChild(button);
  });
}

function renderSensors(sensors) {
  els.sensorGrid.innerHTML = "";
  sensors.forEach((sensor) => {
    const item = document.createElement("div");
    item.className = `sensor-item level-${sensor.level || "normal"}`;
    item.innerHTML = `
      <strong>${sensor.label || sensor.name}</strong>
      <span>${sensor.updated_at || ""}</span>
      <div class="sensor-value">${sensor.value}<small> ${sensor.unit || ""}</small></div>
    `;
    els.sensorGrid.appendChild(item);
  });
}

function renderVision(events) {
  els.visionList.innerHTML = "";
  if (events.length) {
    const latest = events[0];
    els.visionSummary.textContent = `${latest.label_zh || latest.label} · ${Math.round((latest.confidence || 0) * 100)}%`;
    if (latest.image_url) els.visionImage.src = latest.image_url;
  }
  events.slice(0, 5).forEach((event) => {
    const item = document.createElement("div");
    item.className = `event-item level-${event.risk === "warning" ? "warning" : "normal"}`;
    item.innerHTML = `<strong>${event.label_zh || event.label}</strong><span>${event.timestamp || ""} · 置信度 ${Math.round((event.confidence || 0) * 100)}%</span>`;
    els.visionList.appendChild(item);
  });
}

function renderAlarms(alarms) {
  els.alarmList.innerHTML = "";
  const open = alarms.filter((alarm) => alarm.status !== "confirmed");
  els.alarmSummary.textContent = open.length ? `${open.length} 条待处理` : "暂无告警";
  alarms.slice(0, 8).forEach((alarm) => {
    const item = document.createElement("div");
    item.className = `alarm-item level-${alarm.level || "normal"}`;
    const disabled = alarm.status === "confirmed" ? "disabled" : "";
    item.innerHTML = `
      <strong>${alarm.message}</strong>
      <span>${alarm.timestamp} · ${alarm.source} · ${alarm.status}</span>
      <div class="alarm-actions"><button ${disabled}>确认</button></div>
    `;
    item.querySelector("button").onclick = () => send("alarm_confirm", { alarm_id: alarm.alarm_id, operator: "web" });
    els.alarmList.appendChild(item);
  });
}

function renderReports(reports) {
  els.reportList.innerHTML = "";
  reports.slice(0, 8).forEach((report) => {
    const item = document.createElement("div");
    item.className = "report-item";
    item.innerHTML = `<strong>${report.title}</strong><span>${report.timestamp} · ${report.summary}</span>`;
    els.reportList.appendChild(item);
  });
}

function drawMap(points, pose, target) {
  const canvas = els.map;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#f6f8f4";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#cdd8d2";
  ctx.lineWidth = 2;
  ctx.strokeRect(44, 44, width - 88, height - 88);
  ctx.beginPath();
  ctx.moveTo(44, 205);
  ctx.lineTo(width - 44, 205);
  ctx.moveTo(320, 44);
  ctx.lineTo(320, height - 44);
  ctx.stroke();

  points.forEach((point) => {
    const p = mapPose(point.pose);
    const active = target && target.id === point.id;
    ctx.fillStyle = active ? "#c5523a" : "#2f6f5e";
    ctx.beginPath();
    ctx.arc(p.x, p.y, active ? 10 : 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#18211f";
    ctx.font = "15px Microsoft YaHei, Arial";
    ctx.fillText(point.name, p.x + 12, p.y + 5);
  });

  const robot = mapPose(pose);
  ctx.fillStyle = "#2f6fb0";
  ctx.beginPath();
  ctx.arc(robot.x, robot.y, 12, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 3;
  ctx.stroke();
}

function mapPose(pose = {}) {
  const x = Number(pose.x || 0);
  const y = Number(pose.y || 0);
  return {
    x: 64 + x * 112,
    y: 370 - y * 78,
  };
}

function bindEvents() {
  els.connectBtn.onclick = connect;
  els.disconnectBtn.onclick = disconnect;
  els.speedRange.oninput = () => {
    els.speedValue.textContent = `${Number(els.speedRange.value).toFixed(2)} m/s`;
  };
  document.querySelectorAll(".dpad button").forEach((button) => {
    button.onclick = () => send("manual_control", {
      direction: button.dataset.dir,
      speed: Number(els.speedRange.value),
    });
  });
  els.estopBtn.onclick = () => send("emergency_stop", { reason: "web" });
  els.stopTaskBtn.onclick = () => send("task_stop", {});
  els.detectBtn.onclick = () => send("vision_detect", {});
}

async function loadSnapshot() {
  try {
    const response = await fetch("/api/snapshot");
    state.snapshot = await response.json();
    render();
  } catch (error) {
    console.warn("snapshot failed", error);
  }
}

bindEvents();
loadSnapshot().then(connect);

