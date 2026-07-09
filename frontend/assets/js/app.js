const page = document.body.dataset.page || "dashboard";
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

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function connect() {
  const input = $("serverInput");
  if (!input) return;
  if (state.ws) state.ws.close();
  const ws = new WebSocket(input.value.trim());
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
  const labels = { online: "已连接", offline: "离线", connecting: "连接中", error: "连接失败" };
  setText("connectionState", labels[status] || status);
  setText("railStatus", labels[status] || status);
  const dot = $("railDot");
  if (dot) dot.classList.toggle("online", status === "online");
}

function send(type, payload = {}) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    return false;
  }
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
    state.snapshot.vision = state.snapshot.vision.slice(0, 20);
  } else if (type === "alarm_event") {
    state.snapshot.alarms.unshift(payload);
    state.snapshot.alarms = state.snapshot.alarms.slice(0, 40);
  } else if (type === "alarm_update") {
    replaceById(state.snapshot.alarms, payload, "alarm_id");
  } else if (type === "report_created") {
    state.snapshot.reports.unshift(payload);
    state.snapshot.reports = state.snapshot.reports.slice(0, 30);
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
  renderCommon();
  if (page === "dashboard") renderDashboard();
  if (page === "control") renderControl();
  if (page === "navigation") renderNavigation();
  if (page === "vision") renderVisionPage();
  if (page === "alarms") renderAlarmsPage();
  if (page === "reports") renderReportsPage();
}

function renderCommon() {
  const { robot, navigation } = state.snapshot;
  setText("adapterText", `adapter ${robot.adapter || "--"}`);
  setText("robotMode", robot.mode || "--");
  setText("robotTarget", `目标：${robot.target || "无"}`);
  setText("robotError", robot.last_error || "无");
  setText("batteryText", robot.battery ? `${robot.battery}%` : "--%");
  setText("navMessage", navigation.message || "等待任务");
  const progress = Math.round((navigation.progress || 0) * 100);
  setText("navProgressText", `${progress}%`);
  const progressBar = $("navProgress");
  if (progressBar) progressBar.style.width = `${progress}%`;
}

function renderDashboard() {
  renderSensors();
  const timeline = $("dashboardTimeline");
  if (!timeline) return;
  const events = [
    ...state.snapshot.alarms.slice(0, 5).map((item) => ({
      title: item.message,
      meta: `${item.timestamp} · 告警 · ${item.level}`,
      level: item.level,
    })),
    ...state.snapshot.vision.slice(0, 3).map((item) => ({
      title: `视觉检测：${item.label_zh || item.label}`,
      meta: `${item.timestamp} · 置信度 ${Math.round((item.confidence || 0) * 100)}%`,
      level: item.risk === "warning" ? "warning" : "normal",
    })),
    ...state.snapshot.reports.slice(0, 3).map((item) => ({
      title: item.title,
      meta: `${item.timestamp} · ${item.summary}`,
      level: "normal",
    })),
  ].slice(0, 8);
  timeline.innerHTML = events.length
    ? events.map(renderTimelineItem).join("")
    : `<div class="timeline-item"><strong>暂无事件</strong><span>连接后会显示实时事件</span></div>`;
}

function renderControl() {
  renderCommon();
}

function renderNavigation() {
  renderPoints();
  renderRoutes();
  drawMap();
}

function renderVisionPage() {
  const list = $("visionList");
  const events = state.snapshot.vision || [];
  if (events.length) {
    const latest = events[0];
    setText("visionSummary", `${latest.label_zh || latest.label} · ${Math.round((latest.confidence || 0) * 100)}%`);
    const image = $("visionImage");
    if (image && latest.image_url) image.src = latest.image_url;
  }
  if (list) {
    list.innerHTML = events.length
      ? events.slice(0, 12).map((event) => renderTimelineItem({
        title: event.label_zh || event.label,
        meta: `${event.timestamp || ""} · 置信度 ${Math.round((event.confidence || 0) * 100)}% · ${event.source || ""}`,
        level: event.risk === "warning" ? "warning" : "normal",
      })).join("")
      : `<div class="timeline-item"><strong>暂无检测</strong><span>点击检测一次或等待模拟检测事件</span></div>`;
  }
}

function renderAlarmsPage() {
  const list = $("alarmList");
  const alarms = state.snapshot.alarms || [];
  const open = alarms.filter((alarm) => alarm.status !== "confirmed");
  setText("alarmSummary", open.length ? `${open.length} 条待处理告警` : "暂无待处理告警");
  if (!list) return;
  list.innerHTML = alarms.length
    ? alarms.slice(0, 30).map((alarm) => `
      <div class="alarm-item level-${alarm.level || "normal"}">
        <div>
          <strong>${escapeHtml(alarm.message)}</strong>
          <span>${alarm.timestamp || ""} · ${alarm.source || ""} · ${alarm.status || ""}</span>
        </div>
        <button class="neon-btn ghost" data-alarm="${alarm.alarm_id}" ${alarm.status === "confirmed" ? "disabled" : ""}>确认</button>
      </div>
    `).join("")
    : `<div class="alarm-item"><div><strong>暂无告警</strong><span>传感器、视觉和急停事件会显示在这里</span></div></div>`;
  list.querySelectorAll("[data-alarm]").forEach((btn) => {
    btn.addEventListener("click", () => send("alarm_confirm", { alarm_id: btn.dataset.alarm, operator: "web" }));
  });
}

function renderReportsPage() {
  const list = $("reportList");
  const reports = state.snapshot.reports || [];
  if (!list) return;
  list.innerHTML = reports.length
    ? reports.slice(0, 30).map((report) => `
      <div class="report-item">
        <strong>${escapeHtml(report.title)}</strong>
        <span>${report.timestamp || ""} · ${escapeHtml(report.summary || "")}</span>
      </div>
    `).join("")
    : `<div class="report-item"><strong>暂无报告</strong><span>导航到达或巡逻完成后会生成报告</span></div>`;
}

function renderSensors() {
  const grid = $("sensorGrid");
  if (!grid) return;
  const sensors = state.snapshot.sensors || [];
  grid.innerHTML = sensors.map((sensor) => `
    <div class="sensor-item level-${sensor.level || "normal"}">
      <strong>${escapeHtml(sensor.label || sensor.name)}</strong>
      <span>${sensor.updated_at || ""}</span>
      <div class="sensor-value">${sensor.value}<small> ${sensor.unit || ""}</small></div>
    </div>
  `).join("");
}

function renderPoints() {
  const list = $("pointList");
  if (!list) return;
  list.innerHTML = (state.snapshot.points || [])
    .filter((point) => point.enabled !== false)
    .map((point) => `
      <button data-point="${point.id}">
        <strong>${escapeHtml(point.name)}</strong>
        <span>${escapeHtml(point.description || "")}</span>
      </button>
    `).join("");
  list.querySelectorAll("[data-point]").forEach((btn) => {
    btn.addEventListener("click", () => send("nav_goal", { point_id: btn.dataset.point }));
  });
}

function renderRoutes() {
  const list = $("routeList");
  if (!list) return;
  list.innerHTML = (state.snapshot.routes || []).map((route) => `
    <button data-route="${route.id}">
      <strong>${escapeHtml(route.name)}</strong>
      <span>${escapeHtml(route.description || "")}</span>
    </button>
  `).join("");
  list.querySelectorAll("[data-route]").forEach((btn) => {
    btn.addEventListener("click", () => send("patrol_start", { route_id: btn.dataset.route }));
  });
}

function renderTimelineItem(item) {
  return `
    <div class="timeline-item level-${item.level || "normal"}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.meta || "")}</span>
    </div>
  `;
}

function drawMap() {
  const canvas = $("homeMap");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const points = state.snapshot.points || [];
  const robot = state.snapshot.robot || {};
  const target = state.snapshot.navigation?.target;

  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#061326");
  gradient.addColorStop(1, "#090820");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(38,244,255,0.18)";
  ctx.lineWidth = 1;
  for (let x = 40; x < width; x += 48) {
    ctx.beginPath();
    ctx.moveTo(x, 36);
    ctx.lineTo(x, height - 36);
    ctx.stroke();
  }
  for (let y = 36; y < height; y += 48) {
    ctx.beginPath();
    ctx.moveTo(40, y);
    ctx.lineTo(width - 40, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "rgba(38,244,255,0.5)";
  ctx.lineWidth = 3;
  ctx.strokeRect(60, 58, width - 120, height - 116);
  ctx.strokeStyle = "rgba(159,107,255,0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(60, height * 0.48);
  ctx.lineTo(width - 60, height * 0.48);
  ctx.moveTo(width * 0.47, 58);
  ctx.lineTo(width * 0.47, height - 58);
  ctx.stroke();

  points.forEach((point) => {
    const p = mapPose(point.pose, width, height);
    const active = target && target.id === point.id;
    ctx.beginPath();
    ctx.arc(p.x, p.y, active ? 13 : 9, 0, Math.PI * 2);
    ctx.fillStyle = active ? "#ff4fd8" : "#26f4ff";
    ctx.shadowBlur = active ? 28 : 18;
    ctx.shadowColor = active ? "#ff4fd8" : "#26f4ff";
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#e9f7ff";
    ctx.font = "16px Microsoft YaHei, Arial";
    ctx.fillText(point.name, p.x + 16, p.y + 6);
  });

  const r = mapPose(robot.pose || {}, width, height);
  ctx.beginPath();
  ctx.arc(r.x, r.y, 15, 0, Math.PI * 2);
  ctx.fillStyle = "#7dff9b";
  ctx.shadowBlur = 30;
  ctx.shadowColor = "#7dff9b";
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#061326";
  ctx.font = "bold 12px Arial";
  ctx.fillText("BOT", r.x - 11, r.y + 4);
}

function mapPose(pose = {}, width, height) {
  const x = Number(pose.x || 0);
  const y = Number(pose.y || 0);
  return {
    x: 80 + x * ((width - 160) / 5.2),
    y: height - 80 - y * ((height - 160) / 4.4),
  };
}

function bindEvents() {
  $("connectBtn")?.addEventListener("click", connect);
  $("disconnectBtn")?.addEventListener("click", disconnect);
  $("estopBtn")?.addEventListener("click", () => send("emergency_stop", { reason: "web" }));
  $("reconnectCarBtn")?.addEventListener("click", reconnectCar);
  $("stopTaskBtn")?.addEventListener("click", () => send("task_stop", {}));
  $("detectBtn")?.addEventListener("click", () => send("vision_detect", {}));
  $("speedRange")?.addEventListener("input", () => {
    setText("speedValue", `${Number($("speedRange").value).toFixed(2)} m/s`);
  });
  document.querySelectorAll(".neon-dpad button").forEach((button) => {
    button.addEventListener("click", () => send("manual_control", {
      direction: button.dataset.dir,
      speed: Number($("speedRange")?.value || 0.16),
    }));
  });
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

async function reconnectCar() {
  const button = $("reconnectCarBtn");
  if (button) button.textContent = "重连中...";
  try {
    await fetch("/api/car/reconnect", { method: "POST" });
  } catch (error) {
    console.warn("car reconnect failed", error);
  } finally {
    if (button) button.textContent = "重连小车";
    await loadSnapshot();
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;");
}

bindEvents();
loadSnapshot().then(connect);
