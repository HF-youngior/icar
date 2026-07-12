const page = document.body.dataset.page || "dashboard";

const state = {
  ws: null,
  connected: false,
  manualStopInFlight: false,
  lastManualStopAt: 0,
  manualStopTimer: null,
  manualDirection: null,
  camera: {
    candidates: [],
    index: 0,
    attempts: 0,
    active: false,
    currentUrl: "",
  },
  slam: {
    maps: [],
    selectedMap: "",
    mapMeta: null,
    mapImage: null,
    click: null,
  },
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

function buildDefaultWsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host || "127.0.0.1:8000";
  return `${scheme}://${host}/ws`;
}

function initConnectionInput() {
  const input = $("serverInput");
  if (!input) return;
  const current = (input.value || "").trim();
  if (!current || current === "ws://127.0.0.1:8000/ws") {
    input.value = buildDefaultWsUrl();
  }
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

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    const text = await response.text().catch(() => "");
    try {
      const data = text ? JSON.parse(text) : {};
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail?.error) {
        message = data.detail.error;
      } else if (data.error) {
        message = data.error;
      }
    } catch {
      if (text) message = text;
    }
    throw new Error(message);
  }
  return response.json().catch(() => ({}));
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`请求失败：${response.status}`);
  return response.json();
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
  drawSlamMap();
}

function renderVisionPage() {
  const list = $("visionList");
  const events = state.snapshot.vision || [];
  if (events.length) {
    const latest = events[0];
    setText("visionSummary", `${latest.label_zh || latest.label} · ${Math.round((latest.confidence || 0) * 100)}%`);
    const image = $("visionImage");
    if (image && latest.image_url && !state.camera.active) image.src = latest.image_url;
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

function renderTimelineItem(item) {
  return `
    <div class="timeline-item level-${item.level || "normal"}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.meta || "")}</span>
    </div>
  `;
}

async function loadSnapshot() {
  try {
    state.snapshot = await getJson("/api/snapshot");
    render();
  } catch (error) {
    console.warn("snapshot failed", error);
  }
}

async function reconnectCar() {
  const button = $("reconnectCarBtn");
  if (button) {
    button.disabled = true;
    button.textContent = "重连中...";
  }
  setText("robotError", "正在通过 SSH 恢复小车服务...");
  setText("cameraStatus", "正在恢复小车摄像头服务...");
  try {
    const result = await postJson("/api/car/reconnect", {});
    const ports = result.runtime?.after || {};
    const cameraReady = ports.camera_6500 || ports.camera_8080;
    setText("robotError", `重连成功：6000=${ports.control_6000 ? "open" : "--"}，6500=${ports.camera_6500 ? "open" : "--"}，8080=${ports.camera_8080 ? "open" : "--"}`);
    setText("cameraStatus", cameraReady ? "小车摄像头服务已恢复" : "小车摄像头端口未打开");
    if (page === "vision") {
      await loadCameraCandidates();
      startCameraAuto();
    }
  } catch (error) {
    console.warn("car reconnect failed", error);
    setText("robotError", `重连失败：${error.message || error}`);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "重连小车";
    }
    await loadSnapshot();
  }
}

function currentSpeed() {
  return Number($("speedRange")?.value || 0.16);
}

function speedPercent(speed = currentSpeed()) {
  return Math.max(0, Math.min(100, Math.round((speed / 0.32) * 100)));
}

function updateSpeedDisplay() {
  const speed = currentSpeed();
  setText("speedValue", `${speed.toFixed(2)} m/s · ${speedPercent(speed)}%`);
}

async function sendAuxControl(action, payload = {}) {
  setText("auxResult", "发送中...");
  try {
    const result = await postJson("/api/control/aux", { action, ...payload });
    setText("auxResult", `已执行 ${action} · ${result.adapter || "tcp"}`);
    await loadSnapshot();
    return true;
  } catch (error) {
    console.warn("aux control failed", error);
    setText("auxResult", `发送失败：${error.message || error}`);
    return false;
  }
}

async function toggleLight() {
  const button = $("lightToggleBtn");
  const enabled = button?.dataset.enabled !== "true";
  const ok = await sendAuxControl("light", {
    enabled,
    r: enabled ? 38 : 0,
    g: enabled ? 244 : 0,
    b: enabled ? 255 : 0,
  });
  if (ok && button) {
    button.dataset.enabled = String(enabled);
    button.classList.toggle("active", enabled);
  }
}

async function toggleFollowLine() {
  const button = $("followLineBtn");
  const enabled = button?.dataset.enabled !== "true";
  if (enabled) await sendStopNow();
  const ok = await sendAuxControl("follow_line", { enabled });
  if (ok && button) {
    button.dataset.enabled = String(enabled);
    button.classList.toggle("active", enabled);
  }
}

async function loadCameraCandidates() {
  const select = $("cameraSelect");
  if (!select) return;
  try {
    const data = await getJson("/api/camera/candidates");
    state.camera.candidates = data.urls || [];
    select.innerHTML = state.camera.candidates.map((candidate, index) => (
      `<option value="${index}">${escapeHtml(candidate.label)}</option>`
    )).join("");
    setText("cameraStatus", state.camera.candidates.length ? "摄像头地址已加载" : "未找到候选地址");
  } catch (error) {
    console.warn("camera candidates failed", error);
    setText("cameraStatus", "摄像头地址加载失败");
  }
}

function startCameraAuto() {
  state.camera.attempts = 0;
  if (!state.camera.candidates.length) {
    loadCameraCandidates().then(() => startCameraAt(0));
    return;
  }
  startCameraAt(0);
}

function startCameraNext() {
  const count = state.camera.candidates.length;
  if (!count) {
    startCameraAuto();
    return;
  }
  state.camera.attempts += 1;
  if (state.camera.attempts >= count) {
    state.camera.active = false;
    setText("cameraStatus", "摄像头未响应");
    const image = $("visionImage");
    if (image) {
      image.onload = null;
      image.onerror = null;
      image.src = "/assets/sample-detection.svg";
    }
    return;
  }
  startCameraAt((state.camera.index + 1) % count);
}

function startCameraAt(index) {
  const image = $("visionImage");
  const candidate = state.camera.candidates[index];
  if (!image || !candidate) return;
  state.camera.index = index;
  state.camera.active = true;
  state.camera.currentUrl = candidate.url;
  const select = $("cameraSelect");
  if (select) select.value = String(index);
  setText("cameraStatus", `连接中：${candidate.label}`);
  image.onload = () => setText("cameraStatus", `已连接：${candidate.label}`);
  image.onerror = () => {
    setText("cameraStatus", `${candidate.label} 无响应，尝试下一个`);
    if (state.camera.active && state.camera.currentUrl === candidate.url) {
      window.setTimeout(startCameraNext, 200);
    }
  };
  image.src = withCacheBust(candidate.url);
  window.setTimeout(() => {
    if (state.camera.active && state.camera.currentUrl === candidate.url) {
      setText("cameraStatus", `正在尝试：${candidate.label}`);
    }
  }, 1500);
}

function withCacheBust(url) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}_=${Date.now()}`;
}

function stopCamera() {
  const image = $("visionImage");
  state.camera.active = false;
  state.camera.currentUrl = "";
  if (image) {
    image.onload = null;
    image.onerror = null;
    image.src = "/assets/sample-detection.svg";
  }
  setText("cameraStatus", "摄像头已停止");
}

async function sendManualHttp(direction) {
  const speed = currentSpeed();
  const payload = { direction, speed };
  if (direction !== "stop") payload.duration_ms = 260;
  try {
    await postJson("/api/control/manual", payload);
  } catch (error) {
    console.warn("manual control failed", error);
  }
}

function clearManualHold() {
  if (state.manualStopTimer) {
    clearTimeout(state.manualStopTimer);
    state.manualStopTimer = null;
  }
}

async function sendStopNow(force = false) {
  const now = Date.now();
  if (!force && (state.manualStopInFlight || now - state.lastManualStopAt < 450)) {
    return;
  }
  state.lastManualStopAt = now;
  state.manualStopInFlight = true;
  clearManualHold();
  state.manualDirection = null;
  try {
    await sendManualHttp("stop");
  } finally {
    state.manualStopInFlight = false;
  }
}

function emergencyStop() {
  clearManualHold();
  state.manualDirection = null;
  postJson("/api/control/emergency-stop", { reason: "web" }).catch((error) => {
    console.warn("emergency stop failed", error);
  });
  sendStopNow(true);
}

function stopNavigationTask() {
  sendStopNow();
  send("task_stop", {});
  postJson("/api/navigation/stop", {}).catch((error) => {
    console.warn("navigation stop failed", error);
  });
}

function sendManualPulse(direction) {
  if (!direction) return;
  if (direction === "stop") {
    sendStopNow();
    return;
  }
  clearManualHold();
  state.manualDirection = direction;
  sendManualHttp(direction);
  state.manualStopTimer = window.setTimeout(() => {
    if (state.manualDirection === direction) {
      sendStopNow();
    }
  }, 260);
}

async function loadSlamMaps() {
  const select = $("slamMapSelect");
  if (!select) return;
  setText("slamMapHint", "正在读取小车地图列表...");
  try {
    const data = await getJson("/api/slam/maps");
    state.slam.maps = data.maps || [];
    select.innerHTML = state.slam.maps.length
      ? state.slam.maps.map((map) => `<option value="${escapeHtml(map.name)}">${escapeHtml(map.name)}</option>`).join("")
      : `<option value="">未找到地图</option>`;
    if (!state.slam.selectedMap && state.slam.maps.length) {
      state.slam.selectedMap = state.slam.maps[0].name;
      select.value = state.slam.selectedMap;
    }
    setText("slamMapHint", state.slam.maps.length ? "地图列表已加载" : "小车 maps 目录没有 YAML 地图");
    if (state.slam.selectedMap) await loadSelectedSlamMap();
  } catch (error) {
    console.warn("slam maps failed", error);
    setText("slamMapHint", `地图读取失败：${error.message || error}`);
  }
}

async function loadSelectedSlamMap() {
  const select = $("slamMapSelect");
  const name = select?.value || state.slam.selectedMap;
  if (!name) return;
  state.slam.selectedMap = name;
  setText("slamMapHint", `正在加载地图 ${name}...`);
  try {
    const mapInfo = state.slam.maps.find((item) => item.name === name) || {};
    const data = mapInfo.meta ? mapInfo : (await getJson(`/api/slam/maps`)).maps.find((item) => item.name === name);
    const image = new Image();
    image.onload = () => {
      state.slam.mapImage = image;
      state.slam.mapMeta = data?.meta || {
        resolution: 0.05,
        origin: [-10, -10, 0],
        width: image.naturalWidth,
        height: image.naturalHeight,
      };
      drawSlamMap();
      renderSlamMapMeta();
      setText("slamMapHint", "地图已加载，点击地图可取点。");
    };
    image.onerror = () => setText("slamMapHint", "地图图片加载失败");
    image.src = withCacheBust(`/api/slam/maps/${encodeURIComponent(name)}/image`);
  } catch (error) {
    console.warn("slam map load failed", error);
    setText("slamMapHint", `地图加载失败：${error.message || error}`);
  }
}

function drawSlamMap() {
  const canvas = $("slamMapCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#06101f";
  ctx.fillRect(0, 0, width, height);

  const image = state.slam.mapImage;
  if (!image) {
    ctx.fillStyle = "#8ea4b8";
    ctx.font = "18px Microsoft YaHei, Arial";
    ctx.fillText("加载小车地图后会显示真实 SLAM 栅格图", 28, 48);
    return;
  }

  const frame = slamMapFrame();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(image, frame.x, frame.y, frame.w, frame.h);
  ctx.strokeStyle = "rgba(38,244,255,0.5)";
  ctx.lineWidth = 2;
  ctx.strokeRect(frame.x, frame.y, frame.w, frame.h);

  if (state.slam.click) {
    const p = worldToCanvas(state.slam.click.x, state.slam.click.y);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
    ctx.fillStyle = "#ff4fd8";
    ctx.shadowBlur = 18;
    ctx.shadowColor = "#ff4fd8";
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#e9f7ff";
    ctx.font = "14px Microsoft YaHei, Arial";
    ctx.fillText(`(${state.slam.click.x.toFixed(2)}, ${state.slam.click.y.toFixed(2)})`, p.x + 12, p.y - 10);
  }
}

function slamMapFrame() {
  const canvas = $("slamMapCanvas");
  const image = state.slam.mapImage;
  const cw = canvas?.width || 900;
  const ch = canvas?.height || 620;
  if (!image) return { x: 20, y: 20, w: cw - 40, h: ch - 40, scale: 1 };
  const scale = Math.min((cw - 40) / image.naturalWidth, (ch - 40) / image.naturalHeight);
  const w = image.naturalWidth * scale;
  const h = image.naturalHeight * scale;
  return { x: (cw - w) / 2, y: (ch - h) / 2, w, h, scale };
}

function canvasToWorld(clientX, clientY) {
  const canvas = $("slamMapCanvas");
  const image = state.slam.mapImage;
  const meta = state.slam.mapMeta;
  if (!canvas || !image || !meta) return null;
  const rect = canvas.getBoundingClientRect();
  const frame = slamMapFrame();
  const cx = ((clientX - rect.left) / rect.width) * canvas.width;
  const cy = ((clientY - rect.top) / rect.height) * canvas.height;
  if (cx < frame.x || cx > frame.x + frame.w || cy < frame.y || cy > frame.y + frame.h) return null;
  const px = (cx - frame.x) / frame.scale;
  const py = image.naturalHeight - ((cy - frame.y) / frame.scale);
  const origin = meta.origin || [-10, -10, 0];
  const resolution = Number(meta.resolution || 0.05);
  return {
    x: origin[0] + px * resolution,
    y: origin[1] + py * resolution,
  };
}

function worldToCanvas(x, y) {
  const image = state.slam.mapImage;
  const meta = state.slam.mapMeta;
  const frame = slamMapFrame();
  const origin = meta?.origin || [-10, -10, 0];
  const resolution = Number(meta?.resolution || 0.05);
  const px = (x - origin[0]) / resolution;
  const py = image.naturalHeight - ((y - origin[1]) / resolution);
  return {
    x: frame.x + px * frame.scale,
    y: frame.y + py * frame.scale,
  };
}

function handleSlamMapClick(event) {
  const world = canvasToWorld(event.clientX, event.clientY);
  if (!world) return;
  state.slam.click = world;
  const xInput = $("slamPoseX");
  const yInput = $("slamPoseY");
  if (xInput) xInput.value = world.x.toFixed(2);
  if (yInput) yInput.value = world.y.toFixed(2);
  setText("slamClickCoord", `${world.x.toFixed(2)}, ${world.y.toFixed(2)}`);
  drawSlamMap();
}

function renderSlamMapMeta() {
  const meta = state.slam.mapMeta;
  if (!meta) {
    setText("slamMapMeta", "--");
    return;
  }
  const origin = meta.origin || [];
  setText("slamMapMeta", `${meta.width || "--"}×${meta.height || "--"} · ${meta.resolution || "--"}m · origin [${origin.join(", ")}]`);
}

async function refreshSlamStatus() {
  const list = $("slamStatusList");
  if (!list) return;
  list.innerHTML = `<div><span>状态</span><strong>读取中...</strong></div>`;
  try {
    const data = await getJson("/api/slam/status");
    const ports = data.ports || {};
    const topics = data.topics || [];
    list.innerHTML = [
      statusRow("小车", `${data.host || "--"} · SSH ${ports.ssh_22 ? "open" : "closed"}`),
      statusRow("ROS 容器", data.container?.running ? "icar_web_nav running" : "未运行"),
      statusRow("模式", data.mode || "idle"),
      statusRow("端口", `6000 ${ports.control_6000 ? "open" : "--"} · 6500 ${ports.camera_6500 ? "open" : "--"}`),
      statusRow("ROS topics", topics.slice(0, 8).join(", ") || "暂无"),
    ].join("");
  } catch (error) {
    list.innerHTML = statusRow("读取失败", error.message || String(error));
  }
}

function statusRow(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

async function refreshSlamLogs() {
  const log = $("slamLogs");
  if (!log) return;
  try {
    const data = await getJson("/api/slam/logs");
    log.textContent = data.logs || "暂无日志";
  } catch (error) {
    log.textContent = `日志读取失败：${error.message || error}`;
  }
}

async function runSlamAction(label, action) {
  setText("navMessage", `${label}...`);
  try {
    const result = await action();
    setText("navMessage", `${label}完成`);
    await refreshSlamStatus();
    await refreshSlamLogs();
    await loadSnapshot();
    return result;
  } catch (error) {
    console.warn(`${label} failed`, error);
    setText("navMessage", `${label}失败：${error.message || error}`);
    throw error;
  }
}

function bindSlamEvents() {
  $("slamMapCanvas")?.addEventListener("click", handleSlamMapClick);
  $("slamMapSelect")?.addEventListener("change", loadSelectedSlamMap);
  $("slamRefreshMapsBtn")?.addEventListener("click", loadSlamMaps);
  $("slamReloadMapBtn")?.addEventListener("click", loadSelectedSlamMap);
  $("slamRefreshStatusBtn")?.addEventListener("click", () => {
    refreshSlamStatus();
    refreshSlamLogs();
  });
  $("slamStartMappingBtn")?.addEventListener("click", () => runSlamAction("启动 SLAM 建图", () => (
    postJson("/api/slam/mapping/start", { algorithm: "gmapping" })
  )));
  $("slamSaveMapBtn")?.addEventListener("click", () => runSlamAction("保存地图", async () => {
    const name = $("slamMapNameInput")?.value || "yahboomcar_web";
    const result = await postJson("/api/slam/map/save", { map_name: name });
    await loadSlamMaps();
    return result;
  }));
  $("slamStartNavBtn")?.addEventListener("click", () => runSlamAction("启动导航系统", () => (
    postJson("/api/slam/navigation/start", {
      algorithm: $("slamNavAlgorithm")?.value || "dwa",
      map: $("slamMapSelect")?.value || "yahboomcar.yaml",
    })
  )));
  $("slamSetInitialBtn")?.addEventListener("click", () => runSlamAction("设置初始位姿", () => (
    postJson("/api/slam/pose/initial", currentSlamPose())
  )));
  $("slamSendGoalBtn")?.addEventListener("click", () => runSlamAction("发送导航目标", () => (
    postJson("/api/slam/goal", currentSlamPose())
  )));
  $("slamStopBtn")?.addEventListener("click", () => runSlamAction("停止 SLAM/导航", () => (
    postJson("/api/slam/stop", {})
  )));
}

function currentSlamPose() {
  return {
    x: Number($("slamPoseX")?.value || 0),
    y: Number($("slamPoseY")?.value || 0),
    theta: Number($("slamPoseTheta")?.value || 0),
  };
}

function bindEvents() {
  initConnectionInput();
  $("connectBtn")?.addEventListener("click", connect);
  $("disconnectBtn")?.addEventListener("click", disconnect);
  $("estopBtn")?.addEventListener("click", emergencyStop);
  $("reconnectCarBtn")?.addEventListener("click", reconnectCar);
  $("stopTaskBtn")?.addEventListener("click", stopNavigationTask);
  $("detectBtn")?.addEventListener("click", () => send("vision_detect", {}));
  $("lightToggleBtn")?.addEventListener("click", toggleLight);
  $("buzzerBtn")?.addEventListener("click", () => sendAuxControl("buzzer", { duration_ms: 300 }));
  $("followLineBtn")?.addEventListener("click", toggleFollowLine);
  $("cameraAutoBtn")?.addEventListener("click", () => startCameraAuto());
  $("cameraNextBtn")?.addEventListener("click", () => {
    state.camera.attempts = 0;
    startCameraNext();
  });
  $("cameraStopBtn")?.addEventListener("click", stopCamera);
  $("cameraSelect")?.addEventListener("change", () => {
    state.camera.attempts = 0;
    startCameraAt(Number($("cameraSelect").value || 0));
  });
  $("speedRange")?.addEventListener("input", updateSpeedDisplay);
  updateSpeedDisplay();
  document.querySelectorAll(".neon-dpad button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      sendManualPulse(button.dataset.dir);
    });
  });
  if (page === "navigation") bindSlamEvents();
  window.addEventListener("blur", () => sendStopNow());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) sendStopNow();
  });
}

async function initPage() {
  await loadSnapshot();
  if (page === "vision") {
    await loadCameraCandidates();
    startCameraAuto();
  }
  if (page === "navigation") {
    await loadSlamMaps();
    await refreshSlamStatus();
    await refreshSlamLogs();
  }
  connect();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;");
}

bindEvents();
initPage();
