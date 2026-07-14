const page = document.body.dataset.page || "dashboard";

const state = {
  ws: null,
  connected: false,
  manualStopInFlight: false,
  lastManualStopAt: 0,
  manualStopTimer: null,
  manualHoldTimer: null,
  manualHoldInFlight: false,
  manualDirection: null,
  camera: {
    candidates: [],
    index: 0,
    attempts: 0,
    active: false,
    currentUrl: "",
  },
  gesture: {
    enabled: false,
    loading: false,
    model: null,
    timer: null,
    processing: false,
    lastGesture: "none",
    stableGesture: "none",
    stableCount: 0,
    lastSentGesture: "",
    lastCommandAt: 0,
    activeDirection: "",
    status: "idle",
    message: "手势控制未开启",
  },
  visionControl: {
    running: false,
    targets: ["person"],
    options: [],
    streamUrl: "",
  },
  slam: {
    maps: [],
    selectedMap: "",
    mapMeta: null,
    mapImage: null,
    pickMode: "start",
    startPose: null,
    goalPose: null,
    goals: [],
    selectedGoalId: "",
    nextGoalNumber: 1,
    goalColors: ["#ff4fd8", "#ffcf5a", "#26f4ff", "#9f6bff", "#7dff9b"],
    goalMonitorTimer: null,
    goalMonitorBusy: false,
    activeGoalId: "",
    initialPoseSent: false,
  },
  cruise: {
    gridWidth: 48,
    gridHeight: 32,
    pose: { x: 3, y: 28, heading: 0 },
    waypoints: [],
    obstacles: [],
    selectedWaypointId: "",
    selectedMode: "select",
    nextWaypointNumber: 1,
    plan: null,
    savedRoutes: [],
    running: false,
    paused: false,
    stopRequested: false,
    executionPromise: null,
    log: [],
    colors: ["#ff4fd8", "#ffcf5a", "#26f4ff", "#9f6bff", "#7dff9b", "#ff8a5b"],
  },
  voice: {
    listening: false,
    supported: typeof window !== "undefined" && !!(window.AudioContext || window.webkitAudioContext),
    status: "idle",
    transcript: "",
    llmOutput: "",
    wakePhrase: "小比",
    level: 0,
    stream: null,
    audioContext: null,
    source: null,
    processor: null,
    chunks: [],
    recording: false,
    uploading: false,
    silenceMs: 0,
    speechMs: 0,
    voiceFrames: 0,
  },
  snapshot: {
    robot: {},
    navigation: {},
    points: [],
    routes: [],
    sensors: [],
    vision: [],
    vision_control: {},
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
  const labels = {
    online: "已连接",
    offline: "离线",
    connecting: "连接中",
    error: "连接失败",
  };
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
      } else if (data.detail?.message) {
        message = data.detail.message;
      } else if (data.error) {
        message = data.error;
      } else if (text) {
        message = text;
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
  } else if (type === "vision_status") {
    state.snapshot.vision_control = payload;
    state.visionControl.running = !!payload.running;
    state.visionControl.targets = payload.targets || ["person"];
    state.visionControl.streamUrl = payload.stream_url || "";
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
  if (page === "cruise") renderCruisePage();
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
  renderVoice();
}

function renderNavigation() {
  drawSlamMap();
  updateSlamPoseTexts();
}

function renderVoice() {
  if (page !== "control") return;
  const labels = {
    idle: "待机",
    listening: "监听中",
    speech: "检测到说话",
    uploading: "上传识别中",
    error: "异常",
  };
  const button = $("voiceToggleBtn");
  if (button) {
    button.textContent = state.voice.listening ? "停止调试监听" : "启动调试监听";
  }
  setText("voiceLocalState", labels[state.voice.status] || state.voice.status);
  setText("voiceStatusPill", state.voice.listening ? "监听中" : "未启动");
  setText("voiceWakePhrase", state.voice.wakePhrase || "--");
  setText("voiceTranscript", state.voice.transcript || "--");
  setText("voiceLlmOutput", state.voice.llmOutput || "--");
  const bar = $("voiceLevelBar");
  if (bar) {
    bar.style.width = `${Math.max(0, Math.min(100, Math.round(state.voice.level * 100)))}%`;
  }
}

function renderVisionPage() {
  const list = $("visionList");
  const events = state.snapshot.vision || [];
  const visionControl = state.snapshot.vision_control || {};
  state.visionControl.running = !!visionControl.running;
  state.visionControl.targets = visionControl.targets || state.visionControl.targets || ["person"];
  state.visionControl.streamUrl = visionControl.stream_url || state.visionControl.streamUrl || "";
  syncVisionTargetSelect();
  setText("visionModeHint", state.visionControl.running
    ? `检测中：${selectedVisionTargetLabels().join("、")} · 视频继续走原生流`
    : `待机中：可选择人员/宠物等目标后开始检测，视频继续走原生流`);
  if (events.length) {
    const latest = events[0];
    setText("visionSummary", `${latest.label_zh || latest.label} · ${Math.round((latest.confidence || 0) * 100)}%`);
    renderDetectionImage(latest);
  } else {
    renderDetectionImage(null);
  }
  if (list) {
    list.innerHTML = events.length
      ? events.slice(0, 12).map((event) => renderTimelineItem({
        title: event.label_zh || event.label,
        meta: `${event.timestamp || ""} · 置信度 ${Math.round((event.confidence || 0) * 100)}% · ${(event.target_filter || []).join("/") || "all"} · ${event.source || ""}`,
        level: event.risk === "warning" ? "warning" : "normal",
      })).join("")
      : `<div class="timeline-item"><strong>暂无检测</strong><span>选择检测目标后点击“检测一次”或“开始检测”</span></div>`;
  }
  renderGestureStatus();
}

function renderDetectionImage(event) {
  const image = $("detectionImage");
  if (!image) return;
  if (!event?.image_url) {
    image.src = "/assets/sample-detection.svg";
    setText("detectionImageStatus", "等待检测");
    return;
  }
  image.src = event.image_url;
  const label = event.label_zh || event.label || "目标";
  setText("detectionImageStatus", `${label} · ${Math.round((event.confidence || 0) * 100)}%`);
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
    : `<div class="alarm-item"><div><strong>暂无告警</strong><span>传感器、视觉、通信和急停事件会显示在这里</span></div></div>`;
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
    : `<div class="report-item"><strong>暂无报告</strong><span>导航到达、巡逻完成和异常事件会生成报告</span></div>`;
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
    const ok = result.ok !== false;
    let message = `已执行 ${action} · ${result.adapter || "tcp"}`;
    if (action === "buzzer") {
      message = "短蜂鸣已发送";
    } else if (action === "voice") {
      message = result.spoken
        ? `语音已播放：${result.engine || "tts"}`
        : `未确认语音播放，已尝试备用提示：${result.engine || result.message || "unknown"}`;
    } else if (action === "light" && result.runtime) {
      const sshOk = result.runtime?.ok ? "SSH 灯控 OK" : "SSH 灯控未确认";
      const tcpOk = result.tcp?.ok ? "TCP 帧 OK" : "TCP 帧未确认";
      const methods = result.runtime?.result?.methods?.length || 0;
      message = ok
        ? `灯光指令已发送 · ${sshOk} / ${tcpOk}${methods ? ` · ${methods} 种方法` : ""}`
        : `灯光未确认生效 · ${sshOk} / ${tcpOk}`;
    } else if (action === "follow_line") {
      message = payload.enabled ? "已开启循迹模式" : "已关闭循迹模式";
    }
    if (!ok && result.warning) message = `${message}：${result.warning}`;
    setText("auxResult", message);
    await loadSnapshot();
    return ok;
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

async function loadVisionStatus() {
  try {
    const data = await getJson("/api/vision/status");
    state.visionControl.running = !!data.running;
    state.visionControl.options = data.options || [];
    state.visionControl.targets = reconcileVisionTargets(data.targets || state.visionControl.targets);
    state.visionControl.streamUrl = data.stream_url || "";
    state.snapshot.vision_control = {
      running: state.visionControl.running,
      targets: state.visionControl.targets,
      source: data.source || "camera_stream",
      stream_url: state.visionControl.streamUrl,
    };
    populateVisionTargetOptions();
    renderVisionPage();
  } catch (error) {
    console.warn("vision status failed", error);
  }
}

function populateVisionTargetOptions() {
  const select = $("visionTargetSelect");
  if (!select) return;
  const options = state.visionControl.options || [];
  state.visionControl.targets = reconcileVisionTargets(state.visionControl.targets);
  select.innerHTML = options.map((option) => (
    `<option value="${escapeHtml(option.id)}">${escapeHtml(option.label_zh || option.label)}</option>`
  )).join("");
  syncVisionTargetSelect();
}

function reconcileVisionTargets(targets) {
  const options = state.visionControl.options || [];
  const optionIds = new Set(options.map((option) => option.id));
  const selected = (targets || []).filter((target) => optionIds.has(target));
  if (selected.length) return selected;
  if (options.length) return [options[0].id];
  return ["person"];
}

function syncVisionTargetSelect() {
  const select = $("visionTargetSelect");
  if (!select) return;
  const selected = new Set(reconcileVisionTargets(state.visionControl.targets));
  Array.from(select.options).forEach((option) => {
    option.selected = selected.has(option.value);
  });
}

function selectedVisionTargets() {
  const select = $("visionTargetSelect");
  const values = select
    ? Array.from(select.selectedOptions).map((option) => option.value).filter(Boolean)
    : [];
  return values.length ? values : reconcileVisionTargets(state.visionControl.targets);
}

function selectedVisionTargetLabels() {
  const select = $("visionTargetSelect");
  const labels = select
    ? Array.from(select.selectedOptions).map((option) => option.textContent?.trim()).filter(Boolean)
    : [];
  return labels.length ? labels : ["人员"];
}

async function detectVisionOnce() {
  try {
    const result = await postJson("/api/vision/detect", { targets: selectedVisionTargets() });
    state.snapshot.vision.unshift(result);
    state.snapshot.vision = state.snapshot.vision.slice(0, 20);
    renderVisionPage();
  } catch (error) {
    console.warn("vision detect failed", error);
    setText("visionSummary", `检测失败：${error.message}`);
  }
}

async function startVisionDetection() {
  try {
    const result = await postJson("/api/vision/start", { targets: selectedVisionTargets() });
    state.visionControl.running = !!result.running;
    state.visionControl.options = result.options || state.visionControl.options;
    state.visionControl.targets = reconcileVisionTargets(result.targets || state.visionControl.targets);
    state.snapshot.vision_control = result;
    renderVisionPage();
  } catch (error) {
    console.warn("vision start failed", error);
    setText("visionSummary", `启动检测失败：${error.message}`);
  }
}

async function stopVisionDetection() {
  try {
    const result = await postJson("/api/vision/stop", {});
    state.visionControl.running = !!result.running;
    state.visionControl.options = result.options || state.visionControl.options;
    state.visionControl.targets = reconcileVisionTargets(result.targets || state.visionControl.targets);
    state.snapshot.vision_control = result;
    renderVisionPage();
  } catch (error) {
    console.warn("vision stop failed", error);
    setText("visionSummary", `停止检测失败：${error.message}`);
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

function normalizeSlamMapName(value) {
  const name = String(value || "").trim();
  if (!name) return "";
  return name.endsWith(".yaml") ? name : `${name}.yaml`;
}

function stopCamera() {
  const image = $("visionImage");
  state.camera.active = false;
  state.camera.currentUrl = "";
  stopGestureControl();
  if (image) {
    image.onload = null;
    image.onerror = null;
    image.src = "/assets/sample-detection.svg";
  }
  setText("cameraStatus", "摄像头已停止");
}

const HAND_CONNECTIONS_LOCAL = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

const GESTURE_COMMANDS = {
  fist: { direction: "stop", label: "握拳 停止" },
  one: { direction: "backward", label: "1 后退" },
  two: { direction: "left", label: "2 左转" },
  three: { direction: "right", label: "3 右转" },
  five: { direction: "forward", label: "五指张开 前进" },
};

const GESTURE_REPEAT_INTERVAL_MS = 220;
const TURN_PULSE_MS = 450;

function renderGestureStatus() {
  if (page !== "vision") return;
  const button = $("gestureToggleBtn");
  if (button) {
    button.textContent = state.gesture.enabled ? "关闭手势控制" : "开启手势控制";
    button.disabled = state.gesture.loading;
  }
  const status = $("gestureStatus");
  if (status) {
    status.textContent = state.gesture.message || "手势控制未开启";
    status.classList.toggle("ready", state.gesture.status === "ready");
    status.classList.toggle("warning", state.gesture.status === "warning");
    status.classList.toggle("danger", state.gesture.status === "danger");
  }
}

function setGestureStatus(message, status = "idle") {
  state.gesture.message = message;
  state.gesture.status = status;
  renderGestureStatus();
}

function loadScriptOnce(src, globalName) {
  if (globalName && window[globalName]) return Promise.resolve();
  const existing = document.querySelector(`script[src="${src}"]`);
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", reject, { once: true });
      window.setTimeout(resolve, 500);
    });
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function ensureGestureModel() {
  if (state.gesture.model) return state.gesture.model;
  const handsBaseUrl = "/assets/vendor/mediapipe/hands";
  await loadScriptOnce(`${handsBaseUrl}/hands.js`, "Hands");
  if (!window.Hands) {
    throw new Error("MediaPipe Hands 未加载");
  }
  const hands = new window.Hands({
    locateFile: (file) => `${handsBaseUrl}/${file}`,
  });
  hands.setOptions({
    maxNumHands: 1,
    modelComplexity: 0,
    minDetectionConfidence: 0.65,
    minTrackingConfidence: 0.55,
  });
  hands.onResults(handleGestureResults);
  state.gesture.model = hands;
  return hands;
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function preferGestureCameraSource() {
  if (!state.camera.candidates.length) {
    await loadCameraCandidates();
  }
  const current = state.camera.candidates[state.camera.index];
  if (current?.url?.startsWith("/api/camera/stream")) return;
  const preferredIndex = state.camera.candidates.findIndex((candidate) => (
    candidate.url?.startsWith("/api/camera/stream") && candidate.label.includes("6500")
  ));
  const fallbackIndex = state.camera.candidates.findIndex((candidate) => candidate.url?.startsWith("/api/camera/stream"));
  const targetIndex = preferredIndex >= 0 ? preferredIndex : fallbackIndex;
  if (targetIndex >= 0) {
    startCameraAt(targetIndex);
    await delay(900);
  }
}

async function toggleGestureControl() {
  if (state.gesture.enabled || state.gesture.loading) {
    stopGestureControl();
    return;
  }
  await startGestureControl();
}

async function startGestureControl() {
  if (page !== "vision") return;
  state.gesture.loading = true;
  renderGestureStatus();
  setGestureStatus("正在加载 MediaPipe Hands...", "warning");
  try {
    await preferGestureCameraSource();
    await ensureGestureModel();
    state.gesture.enabled = true;
    state.gesture.loading = false;
    state.gesture.lastSentGesture = "";
    state.gesture.activeDirection = "";
    setGestureStatus("等待手掌进入画面", "warning");
    scheduleGestureFrame(80);
  } catch (error) {
    console.warn("gesture start failed", error);
    state.gesture.enabled = false;
    state.gesture.loading = false;
    setGestureStatus(`手势控制启动失败：${error.message || error}`, "danger");
  }
}

function stopGestureControl() {
  if (state.gesture.timer) {
    clearTimeout(state.gesture.timer);
    state.gesture.timer = null;
  }
  state.gesture.enabled = false;
  state.gesture.loading = false;
  state.gesture.processing = false;
  state.gesture.lastGesture = "none";
  state.gesture.stableGesture = "none";
  state.gesture.stableCount = 0;
  state.gesture.lastSentGesture = "";
  if (state.gesture.activeDirection) {
    sendStopNow(true).catch((error) => console.warn("gesture stop failed", error));
  }
  state.gesture.activeDirection = "";
  clearGestureCanvas();
  setGestureStatus("手势控制未开启", "idle");
}

function scheduleGestureFrame(ms = 160) {
  if (!state.gesture.enabled) return;
  if (state.gesture.timer) clearTimeout(state.gesture.timer);
  state.gesture.timer = window.setTimeout(processGestureFrame, ms);
}

async function processGestureFrame() {
  if (!state.gesture.enabled) return;
  const image = $("visionImage");
  if (!image || !image.complete || !image.naturalWidth) {
    setGestureStatus("等待摄像头画面", "warning");
    scheduleGestureFrame(220);
    return;
  }
  if (state.gesture.processing) {
    scheduleGestureFrame(120);
    return;
  }
  state.gesture.processing = true;
  try {
    await state.gesture.model.send({ image });
  } catch (error) {
    console.warn("gesture frame failed", error);
    setGestureStatus(`手势识别失败：${error.message || error}`, "danger");
  } finally {
    state.gesture.processing = false;
    scheduleGestureFrame(170);
  }
}

function clearGestureCanvas() {
  const canvas = $("gestureCanvas");
  if (!canvas) return;
  const context = canvas.getContext("2d");
  if (context) context.clearRect(0, 0, canvas.width, canvas.height);
}

function resizeGestureCanvas() {
  const canvas = $("gestureCanvas");
  const frame = canvas?.parentElement;
  if (!canvas || !frame) return null;
  const rect = frame.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return canvas;
}

function imageContentRect(image, canvas) {
  const imageWidth = image?.naturalWidth || canvas.width;
  const imageHeight = image?.naturalHeight || canvas.height;
  const scale = Math.min(canvas.width / imageWidth, canvas.height / imageHeight);
  const width = imageWidth * scale;
  const height = imageHeight * scale;
  return {
    x: (canvas.width - width) / 2,
    y: (canvas.height - height) / 2,
    width,
    height,
  };
}

function toCanvasPoint(point, rect) {
  return {
    x: rect.x + point.x * rect.width,
    y: rect.y + point.y * rect.height,
  };
}

function drawHandSkeleton(landmarks) {
  const canvas = resizeGestureCanvas();
  const image = $("visionImage");
  if (!canvas || !landmarks?.length) return;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  const rect = imageContentRect(image, canvas);
  context.lineWidth = 3;
  context.lineCap = "round";
  context.strokeStyle = "rgba(38, 244, 255, 0.92)";
  HAND_CONNECTIONS_LOCAL.forEach(([from, to]) => {
    const a = toCanvasPoint(landmarks[from], rect);
    const b = toCanvasPoint(landmarks[to], rect);
    context.beginPath();
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.stroke();
  });
  landmarks.forEach((point, index) => {
    const p = toCanvasPoint(point, rect);
    context.beginPath();
    context.fillStyle = index % 4 === 0 ? "rgba(255, 207, 90, 0.96)" : "rgba(125, 255, 155, 0.96)";
    context.arc(p.x, p.y, index % 4 === 0 ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  });
}

function distance(a, b) {
  return Math.hypot((a.x || 0) - (b.x || 0), (a.y || 0) - (b.y || 0), (a.z || 0) - (b.z || 0));
}

function isFingerExtended(landmarks, tip, pip, mcp) {
  const wrist = landmarks[0];
  const tipPoint = landmarks[tip];
  const pipPoint = landmarks[pip];
  const mcpPoint = landmarks[mcp];
  const verticalOpen = tipPoint.y < pipPoint.y - 0.018;
  const radialOpen = distance(tipPoint, wrist) > distance(pipPoint, wrist) * 1.12
    && distance(tipPoint, mcpPoint) > distance(pipPoint, mcpPoint) * 1.02;
  return verticalOpen || radialOpen;
}

function isThumbExtended(landmarks) {
  const wrist = landmarks[0];
  const thumbTip = landmarks[4];
  const thumbIp = landmarks[3];
  const indexMcp = landmarks[5];
  return distance(thumbTip, indexMcp) > distance(thumbIp, indexMcp) * 1.28
    && distance(thumbTip, wrist) > distance(landmarks[2], wrist) * 1.05;
}

function classifyGesture(landmarks) {
  if (!landmarks?.length) return "none";
  const fingers = {
    index: isFingerExtended(landmarks, 8, 6, 5),
    middle: isFingerExtended(landmarks, 12, 10, 9),
    ring: isFingerExtended(landmarks, 16, 14, 13),
    pinky: isFingerExtended(landmarks, 20, 18, 17),
    thumb: isThumbExtended(landmarks),
  };
  const raised = [fingers.index, fingers.middle, fingers.ring, fingers.pinky].filter(Boolean).length;
  if (raised === 0) return "fist";
  if (fingers.index && !fingers.middle && !fingers.ring && !fingers.pinky) return "one";
  if (fingers.index && fingers.middle && !fingers.ring && !fingers.pinky) return "two";
  if (fingers.index && fingers.middle && fingers.ring && !fingers.pinky) return "three";
  if (raised === 4 && fingers.thumb) return "five";
  return "unknown";
}

function updateStableGesture(gesture) {
  if (gesture === state.gesture.lastGesture) {
    state.gesture.stableCount += 1;
  } else {
    state.gesture.lastGesture = gesture;
    state.gesture.stableCount = 1;
  }
  if (state.gesture.stableCount >= 2) {
    state.gesture.stableGesture = gesture;
  }
}

function gestureSpeed() {
  const raw = Number($("gestureSpeedInput")?.value || 0.1);
  return Math.max(0.08, Math.min(0.16, raw));
}

async function sendGestureCommand(gesture) {
  const command = GESTURE_COMMANDS[gesture];
  if (!command) return;
  const now = Date.now();
  if (now - state.gesture.lastCommandAt < GESTURE_REPEAT_INTERVAL_MS) return;
  state.gesture.lastCommandAt = now;
  state.gesture.lastSentGesture = gesture;
  setGestureStatus(`已识别：${command.label}`, "ready");
  if (command.direction === "stop") {
    state.gesture.activeDirection = "";
    await sendStopNow(true);
    return;
  }
  try {
    state.gesture.activeDirection = command.direction;
    const turnPulse = command.direction === "left" || command.direction === "right";
    await postJson("/api/control/manual", {
      direction: command.direction,
      speed: gestureSpeed(),
      duration_ms: turnPulse ? TURN_PULSE_MS : 0,
      hold: !turnPulse,
    });
  } catch (error) {
    console.warn("gesture command failed", error);
    setGestureStatus(`手势控制发送失败：${error.message || error}`, "danger");
  }
}

function handleGestureResults(results) {
  if (!state.gesture.enabled) return;
  const landmarks = results.multiHandLandmarks?.[0];
  if (!landmarks) {
    clearGestureCanvas();
    state.gesture.lastGesture = "none";
    state.gesture.stableGesture = "none";
    state.gesture.stableCount = 0;
    state.gesture.lastSentGesture = "";
    if (state.gesture.activeDirection) {
      state.gesture.activeDirection = "";
      sendStopNow(true).catch((error) => console.warn("gesture stop failed", error));
    }
    setGestureStatus("未检测到手掌，控制禁止", "warning");
    return;
  }
  drawHandSkeleton(landmarks);
  const gesture = classifyGesture(landmarks);
  updateStableGesture(gesture);
  const command = GESTURE_COMMANDS[state.gesture.stableGesture];
  if (!command) {
    state.gesture.lastSentGesture = "";
    if (state.gesture.activeDirection) {
      state.gesture.activeDirection = "";
      sendStopNow(true).catch((error) => console.warn("gesture stop failed", error));
    }
    setGestureStatus("已检测到手掌，等待明确手势", "warning");
    return;
  }
  sendGestureCommand(state.gesture.stableGesture);
}

async function sendManualHttp(direction, options = {}) {
  const speed = currentSpeed();
  const payload = { direction, speed };
  if (direction !== "stop") {
    if (options.hold) {
      payload.hold = true;
    } else {
      payload.duration_ms = Number(options.durationMs ?? 260);
    }
  }
  try {
    return await postJson("/api/control/manual", payload);
  } catch (error) {
    console.warn("manual control failed", error);
    return null;
  }
}

function clearManualHold() {
  if (state.manualStopTimer) {
    clearTimeout(state.manualStopTimer);
    state.manualStopTimer = null;
  }
  if (state.manualHoldTimer) {
    clearInterval(state.manualHoldTimer);
    state.manualHoldTimer = null;
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

function startManualHold(direction) {
  if (!direction) return;
  if (direction === "stop") {
    sendStopNow(true);
    return;
  }
  if (direction === "left" || direction === "right") {
    sendManualPulse(direction, TURN_PULSE_MS);
    return;
  }
  clearManualHold();
  state.manualDirection = direction;
  sendManualHoldRefresh(direction);
  state.manualHoldTimer = window.setInterval(() => {
    if (state.manualDirection === direction) {
      sendManualHoldRefresh(direction);
    }
  }, 330);
}

async function sendManualHoldRefresh(direction) {
  if (state.manualHoldInFlight) return;
  state.manualHoldInFlight = true;
  try {
    await sendManualHttp(direction, { hold: true });
  } finally {
    state.manualHoldInFlight = false;
  }
}

function stopManualHold(direction) {
  if (!state.manualDirection) return;
  if (!direction || state.manualDirection === direction) {
    sendStopNow(true);
  }
}

function sendManualPulse(direction, durationMs = 260) {
  if (!direction) return;
  if (direction === "stop") {
    sendStopNow();
    return;
  }
  clearManualHold();
  state.manualDirection = direction;
  sendManualHttp(direction, { durationMs });
  state.manualStopTimer = window.setTimeout(() => {
    if (state.manualDirection === direction) {
      sendStopNow();
    }
  }, durationMs);
}

function bindManualButton(button) {
  let activePointerId = null;
  const direction = button.dataset.dir;
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    activePointerId = event.pointerId;
    button.setPointerCapture?.(event.pointerId);
    startManualHold(direction);
  });
  const finish = (event) => {
    if (activePointerId !== null && event.pointerId !== activePointerId) return;
    event.preventDefault();
    button.releasePointerCapture?.(event.pointerId);
    activePointerId = null;
    if (direction !== "stop") stopManualHold(direction);
  };
  button.addEventListener("pointerup", finish);
  button.addEventListener("pointercancel", finish);
  button.addEventListener("pointerleave", finish);
  button.addEventListener("click", (event) => event.preventDefault());
  button.addEventListener("contextmenu", (event) => event.preventDefault());
}

async function loadSlamMaps(preferredMap = "") {
  const select = $("slamMapSelect");
  if (!select) return;
  setText("slamMapHint", "正在读取小车地图列表...");
  try {
    const data = await getJson(withCacheBust("/api/slam/maps"));
    state.slam.maps = data.maps || [];
    select.innerHTML = state.slam.maps.length
      ? state.slam.maps.map((map) => `<option value="${escapeHtml(map.name)}">${escapeHtml(map.name)}</option>`).join("")
      : `<option value="">未找到地图</option>`;
    const names = new Set(state.slam.maps.map((map) => map.name));
    const requested = normalizeSlamMapName(preferredMap);
    const selected = names.has(requested)
      ? requested
      : (names.has(state.slam.selectedMap) ? state.slam.selectedMap : (state.slam.maps[0]?.name || ""));
    state.slam.selectedMap = selected;
    select.value = selected;
    if (!selected) {
      state.slam.mapImage = null;
      state.slam.mapMeta = null;
      drawSlamMap();
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
  const previousMap = state.slam.selectedMap;
  state.slam.selectedMap = name;
  if (previousMap && previousMap !== name) {
    state.slam.startPose = null;
    state.slam.goalPose = null;
    state.slam.goals = [];
    state.slam.selectedGoalId = "";
    state.slam.nextGoalNumber = 1;
    clearSlamGoalMonitor();
    state.slam.initialPoseSent = false;
    updateSlamPoseTexts();
  }
  setText("slamMapHint", `正在加载地图 ${name}...`);
  try {
    const mapInfo = state.slam.maps.find((item) => item.name === name) || {};
    const latestMaps = mapInfo.meta ? state.slam.maps : (await getJson("/api/slam/maps")).maps || [];
    const data = latestMaps.find((item) => item.name === name) || mapInfo;
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

function drawSlamMap() {
  const canvas = $("slamMapCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#06101f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const image = state.slam.mapImage;
  if (!image) {
    ctx.fillStyle = "#8ea4b8";
    ctx.font = "18px Microsoft YaHei, Arial";
    ctx.fillText("加载小车地图后会显示真实 SLAM 栅格图。", 28, 48);
    return;
  }

  const frame = slamMapFrame();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(image, frame.x, frame.y, frame.w, frame.h);
  ctx.strokeStyle = "rgba(38,244,255,0.5)";
  ctx.lineWidth = 2;
  ctx.strokeRect(frame.x, frame.y, frame.w, frame.h);

  drawSlamPoseMarker(ctx, state.slam.startPose, "#7dff9b", "当前位置");
  const goals = state.slam.goals.length ? state.slam.goals : (state.slam.goalPose ? [state.slam.goalPose] : []);
  goals.forEach((goal) => {
    drawSlamPoseMarker(ctx, goal, goal.color || "#ff4fd8", goal.name || "目标点", goal.id === state.slam.selectedGoalId);
  });
}

function drawSlamPoseMarker(ctx, pose, color, label, selected = false) {
  if (!pose || !state.slam.mapImage) return;
  const p = worldToCanvas(Number(pose.x || 0), Number(pose.y || 0));
  const theta = Number(pose.theta || 0);
  ctx.save();
  ctx.beginPath();
  ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.shadowBlur = 18;
  ctx.shadowColor = color;
  ctx.fill();
  ctx.shadowBlur = 0;
  if (selected) {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 13, 0, Math.PI * 2);
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(p.x, p.y);
  ctx.lineTo(p.x + Math.cos(theta) * 24, p.y - Math.sin(theta) * 24);
  ctx.stroke();
  ctx.fillStyle = "#e9f7ff";
  ctx.font = "14px Microsoft YaHei, Arial";
  ctx.fillText(`${label} (${Number(pose.x || 0).toFixed(2)}, ${Number(pose.y || 0).toFixed(2)})`, p.x + 12, p.y - 10);
  ctx.restore();
}

function handleSlamMapClick(event) {
  const world = canvasToWorld(event.clientX, event.clientY);
  if (!world) return;
  const pose = { ...world, theta: Number($("slamPoseTheta")?.value || 0) };
  if (state.slam.pickMode === "start") {
    state.slam.startPose = pose;
    state.slam.initialPoseSent = false;
    setText("slamMapHint", "已点选绿色当前位置。启动导航后点击“确认当前位置”。");
  } else {
    const goal = upsertSelectedSlamGoal(pose);
    setText("slamMapHint", `已设置 ${goal.name}。确认当前位置后可以点击“去目标点”。`);
  }
  setSlamPoseInputs(pose);
  updateSlamPoseTexts();
  drawSlamMap();
}

function setSlamPoseInputs(pose) {
  const xInput = $("slamPoseX");
  const yInput = $("slamPoseY");
  const thetaInput = $("slamPoseTheta");
  if (xInput) xInput.value = Number(pose.x || 0).toFixed(2);
  if (yInput) yInput.value = Number(pose.y || 0).toFixed(2);
  if (thetaInput && pose.theta !== undefined) thetaInput.value = Number(pose.theta || 0).toFixed(2);
}

function formatSlamPose(pose) {
  if (!pose) return "未设置";
  return `${Number(pose.x || 0).toFixed(2)}, ${Number(pose.y || 0).toFixed(2)}, θ ${Number(pose.theta || 0).toFixed(2)}`;
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

function selectedSlamGoal() {
  return state.slam.goals.find((goal) => goal.id === state.slam.selectedGoalId) || null;
}

function goalNameForIndex(index) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `目标 ${alphabet[index % alphabet.length]}${index >= alphabet.length ? Math.floor(index / alphabet.length) + 1 : ""}`;
}

function createSlamGoal(pose = null) {
  const number = state.slam.nextGoalNumber++;
  const goal = {
    id: `goal-${Date.now()}-${number}`,
    name: goalNameForIndex(state.slam.goals.length),
    color: state.slam.goalColors[state.slam.goals.length % state.slam.goalColors.length],
    x: pose ? Number(pose.x || 0) : 0,
    y: pose ? Number(pose.y || 0) : 0,
    theta: pose ? Number(pose.theta || 0) : Number($("slamPoseTheta")?.value || 0),
  };
  state.slam.goals.push(goal);
  state.slam.selectedGoalId = goal.id;
  state.slam.goalPose = goal;
  renderSlamGoalList();
  return goal;
}

function upsertSelectedSlamGoal(pose) {
  let goal = selectedSlamGoal();
  if (!goal) goal = createSlamGoal(pose);
  goal.x = Number(pose.x || 0);
  goal.y = Number(pose.y || 0);
  goal.theta = Number(pose.theta || 0);
  state.slam.selectedGoalId = goal.id;
  state.slam.goalPose = goal;
  renderSlamGoalList();
  return goal;
}

function deleteSelectedSlamGoal() {
  const current = state.slam.selectedGoalId;
  if (!current) return;
  const index = state.slam.goals.findIndex((goal) => goal.id === current);
  if (index < 0) return;
  state.slam.goals.splice(index, 1);
  const next = state.slam.goals[Math.min(index, state.slam.goals.length - 1)] || null;
  state.slam.selectedGoalId = next?.id || "";
  state.slam.goalPose = next;
  if (next) setSlamPoseInputs(next);
  renderSlamGoalList();
  updateSlamPoseTexts();
  drawSlamMap();
}

function renderSlamGoalList() {
  const select = $("slamGoalSelect");
  const list = $("slamGoalList");
  if (select) {
    select.innerHTML = state.slam.goals.length
      ? state.slam.goals.map((goal) => `<option value="${escapeHtml(goal.id)}">${escapeHtml(goal.name)} · ${formatSlamPose(goal)}</option>`).join("")
      : `<option value="">尚未设置目标点</option>`;
    select.value = state.slam.selectedGoalId || "";
  }
  if (list) {
    list.innerHTML = state.slam.goals.length
      ? state.slam.goals.map((goal) => `
        <button class="goal-item ${goal.id === state.slam.selectedGoalId ? "active" : ""}" data-goal-id="${escapeHtml(goal.id)}" type="button">
          <span class="goal-swatch" style="background:${escapeHtml(goal.color || "#ff4fd8")}"></span>
          <strong>${escapeHtml(goal.name)}</strong>
          <small>${escapeHtml(formatSlamPose(goal))}</small>
        </button>
      `).join("")
      : `<div class="goal-empty">点“新增目标点”，再在地图上点击要去的位置。</div>`;
    list.querySelectorAll("[data-goal-id]").forEach((button) => {
      button.addEventListener("click", () => selectSlamGoal(button.dataset.goalId || ""));
    });
  }
}

function selectSlamGoal(goalId) {
  const goal = state.slam.goals.find((item) => item.id === goalId);
  if (!goal) return;
  state.slam.selectedGoalId = goal.id;
  state.slam.goalPose = goal;
  state.slam.pickMode = "goal";
  setSlamPoseInputs(goal);
  renderSlamGoalList();
  updateSlamPoseTexts();
  drawSlamMap();
}

function applySlamPoseInputsToSelection() {
  const pose = currentSlamPose();
  if (state.slam.pickMode === "goal") {
    upsertSelectedSlamGoal(pose);
  } else {
    state.slam.startPose = pose;
    state.slam.initialPoseSent = false;
  }
  updateSlamPoseTexts();
  drawSlamMap();
}

function updateSlamPoseTexts() {
  const goal = selectedSlamGoal() || state.slam.goalPose;
  setText("slamPickModeText", state.slam.pickMode === "start" ? "当前位置/起点" : (goal?.name || "目标点"));
  setText("slamStartCoord", formatSlamPose(state.slam.startPose));
  setText("slamGoalCoord", goal ? `${goal.name || "目标点"}：${formatSlamPose(goal)}` : "未设置");
  $("slamPickStartBtn")?.classList.toggle("active", state.slam.pickMode === "start");
  $("slamPickGoalBtn")?.classList.toggle("active", state.slam.pickMode === "goal");
  renderSlamGoalList();
}

function setSlamPickMode(mode) {
  state.slam.pickMode = mode === "goal" ? "goal" : "start";
  if (state.slam.pickMode === "goal" && !selectedSlamGoal() && !state.slam.goals.length) {
    createSlamGoal(currentSlamPose());
  }
  const selected = state.slam.pickMode === "goal" ? selectedSlamGoal() : state.slam.startPose;
  if (selected) setSlamPoseInputs(selected);
  updateSlamPoseTexts();
  setText("slamMapHint", state.slam.pickMode === "start"
    ? "当前是绿色当前位置/起点模式：在地图上点小车现在的位置。"
    : "当前是目标点模式：可先选目标 A/B/C，再在地图上点要去的位置。");
}

function clearSlamGoalMonitor() {
  if (state.slam.goalMonitorTimer) {
    clearInterval(state.slam.goalMonitorTimer);
    state.slam.goalMonitorTimer = null;
  }
  state.slam.goalMonitorBusy = false;
  state.slam.activeGoalId = "";
}

function startSlamGoalMonitor(goal) {
  clearSlamGoalMonitor();
  if (!goal) return;
  state.slam.activeGoalId = goal.id || "";
  let ticks = 0;
  state.slam.goalMonitorTimer = window.setInterval(async () => {
    if (state.slam.goalMonitorBusy) return;
    state.slam.goalMonitorBusy = true;
    ticks += 1;
    try {
      const result = await getJson("/api/slam/pose/current");
      if (result.ok && result.pose) {
        const dx = Number(result.pose.x || 0) - Number(goal.x || 0);
        const dy = Number(result.pose.y || 0) - Number(goal.y || 0);
        const distance = Math.hypot(dx, dy);
        setText("slamDiagnosis", `正在前往 ${goal.name}，AMCL 估计距离约 ${distance.toFixed(2)} m。到达后请手动同步或点选绿色当前位置，再点“确认当前位置”。`);
      }
      if (ticks > 75) {
        clearSlamGoalMonitor();
        setText("slamDiagnosis", "目标点轮询已超时。如果小车已经到达，请手动同步或点选绿色当前位置，再点“确认当前位置”。");
      }
    } catch (error) {
      console.warn("goal monitor failed", error);
    } finally {
      state.slam.goalMonitorBusy = false;
    }
  }, 2000);
}

async function refreshSlamStatus() {
  const list = $("slamStatusList");
  if (!list) return;
  list.innerHTML = `<div><span>状态</span><strong>读取中...</strong></div>`;
  try {
    const data = await getJson("/api/slam/status");
    const ports = data.ports || {};
    const topics = data.topics || [];
    const nav2 = data.nav2 || {};
    list.innerHTML = [
      statusRow("小车", `${data.host || "--"} · SSH ${ports.ssh_22 ? "open" : "closed"}`),
      statusRow("ROS 容器", data.container?.running ? "icar_web_nav running" : "未运行"),
      statusRow("模式", data.mode || "idle"),
      statusRow("端口", `6000 ${ports.control_6000 ? "open" : "--"} · 6500 ${ports.camera_6500 ? "open" : "--"}`),
      statusRow("Nav2 action", nav2.ready ? "/navigate_to_pose ready" : `/navigate_to_pose not ready (${nav2.action_servers ?? 0})`),
      statusRow("bt_navigator", nav2.bt_navigator_active ? "active" : (nav2.bt_navigator_defunct ? "crashed/defunct" : "not active")),
      statusRow("ROS topics", topics.slice(0, 8).join(", ") || "暂无"),
    ].join("");
    if (nav2.crashed || (data.mode || "").includes("navigation")) {
      setText("slamDiagnosis", nav2.message || (nav2.ready ? "Nav2 导航服务已经就绪，可以确认当前位置并发送目标点。" : "Nav2 导航服务还没就绪。"));
    }
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
    updateSlamDiagnosis(data.logs || "");
    log.textContent = data.logs || "暂无日志";
  } catch (error) {
    log.textContent = `日志读取失败：${error.message || error}`;
  }
}

function updateSlamDiagnosis(logs) {
  const text = logs || "";
  if ((text.includes("process has died") && text.includes("bt_navigator")) || text.includes("exit code -11")) {
    setText("slamDiagnosis", "车端 bt_navigator 已崩溃，/navigate_to_pose action server 会消失。请先点“启动导航”重新拉起 Nav2，再确认当前位置并发送目标点。");
  } else if (text.includes("send_goal failed")) {
    setText("slamDiagnosis", "Nav2 收到目标后执行失败。请先点“启动导航”重启导航服务，并确认目标点在白色可通行区域、不要贴墙或障碍物。");
  } else if (text.includes("Action servers: 0")) {
    setText("slamDiagnosis", "当前没有 /navigate_to_pose action server，导航节点未就绪或已经崩溃。请重新点击“启动导航”。");
  } else if (state.slam.initialPoseSent) {
    setText("slamDiagnosis", "当前位置已经由 AMCL/TF 确认。现在可以发送目标点；到达后再点“同步小车当前位姿”更新绿色起点。");
  } else if (text.includes("Please set the initial pose") || text.includes("Invalid frame ID \"map\"")) {
    setText("slamDiagnosis", "导航已启动，但 AMCL 还不知道小车在地图中的当前位置。先点“点选当前位置/起点”，在地图上点小车当前所在位置，再点“确认当前位置”。");
  } else if (text.includes("Timed out waiting for transform")) {
    setText("slamDiagnosis", "ROS2 正在等待 map 到 base_footprint 的 TF。通常是还没设置当前位置，或者地图、雷达、底盘链路没有完全启动。");
  } else {
    setText("slamDiagnosis", "建图靠激光雷达和里程计生成 2D 栅格地图；导航前需要先让 AMCL 知道小车当前在地图上的位置。");
  }
}

async function runSlamAction(label, action) {
  setText("navMessage", `${label}...`);
  try {
    const result = await action();
    if (result && result.ok === false) {
      throw new Error(result.message || result.error || `${label}未成功`);
    }
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

function currentSlamPose() {
  return {
    x: Number($("slamPoseX")?.value || 0),
    y: Number($("slamPoseY")?.value || 0),
    theta: Number($("slamPoseTheta")?.value || 0),
  };
}

async function syncSlamPose(showError = false) {
  const result = await getJson("/api/slam/pose/current");
  if (!result.ok || !result.pose) {
    const message = result.message || "还没有 AMCL 位姿。请先设置当前位置，再等几秒。";
    if (showError) throw new Error(message);
    setText("slamDiagnosis", message);
    return result;
  }
  state.slam.startPose = result.pose;
  state.slam.initialPoseSent = true;
  setSlamPoseInputs(result.pose);
  updateSlamPoseTexts();
  drawSlamMap();
  setText("slamDiagnosis", "已从 AMCL 同步小车当前位姿，下一次导航会把这里作为起点。");
  return result;
}

async function sendSlamInitialPose(requireLocalized = false) {
  const pose = state.slam.startPose || currentSlamPose();
  state.slam.startPose = pose;
  const result = await postJson("/api/slam/pose/initial", { ...pose, wait_sec: 10 });
  const localized = result.localized || {};
  if (localized.ok && localized.pose) {
    state.slam.startPose = localized.pose;
    state.slam.initialPoseSent = true;
    setSlamPoseInputs(localized.pose);
    setText("slamDiagnosis", "AMCL 已确认当前位置。现在可以点选目标点并发送导航目标。");
  } else {
    state.slam.initialPoseSent = false;
    setSlamPoseInputs(pose);
    const message = localized.message || "当前位置已发布，但 AMCL 还没有回传地图坐标。请确认导航已启动、雷达正常，再点一次“确认当前位置”。";
    setText("slamDiagnosis", message);
    if (requireLocalized) throw new Error(message);
  }
  updateSlamPoseTexts();
  drawSlamMap();
  return result;
}

async function sendSlamGoal() {
  const goal = selectedSlamGoal() || state.slam.goalPose;
  if (!goal) {
    throw new Error("请先新增目标点，并在地图上选择小车要去的位置。");
  }
  const initialPose = state.slam.startPose || currentSlamPose();
  state.slam.startPose = initialPose;
  const result = await postJson("/api/slam/goal", {
    id: goal.id || "slam_goal",
    name: goal.name || "Web 目标点",
    x: Number(goal.x || 0),
    y: Number(goal.y || 0),
    theta: Number(goal.theta || 0),
    initial_pose: initialPose,
    require_localized: true,
  });
  if (result.ok === false) {
    throw new Error(result.message || "导航目标没有被 Nav2 接受。");
  }
  startSlamGoalMonitor(goal);
  setText("slamDiagnosis", `已发送 ${goal.name}：(${Number(goal.x || 0).toFixed(2)}, ${Number(goal.y || 0).toFixed(2)})。到达后请重新确认绿色当前位置，再去下一个目标点。`);
  return result;
}

function ensureSlamGoalControls() {
  if ($("slamGoalSelect")) return;
  const modeRow = document.querySelector(".mode-row");
  if (!modeRow) return;
  const row = document.createElement("div");
  row.className = "goal-row";
  row.innerHTML = `
    <select id="slamGoalSelect" aria-label="导航目标点"></select>
    <button class="neon-btn ghost" id="slamAddGoalBtn" type="button">新增目标点</button>
    <button class="neon-btn ghost" id="slamDeleteGoalBtn" type="button">删除目标点</button>
  `;
  const list = document.createElement("div");
  list.className = "goal-list";
  list.id = "slamGoalList";
  modeRow.insertAdjacentElement("afterend", row);
  row.insertAdjacentElement("afterend", list);
}

function bindSlamEvents() {
  ensureSlamGoalControls();
  $("slamMapCanvas")?.addEventListener("click", handleSlamMapClick);
  $("slamMapSelect")?.addEventListener("change", loadSelectedSlamMap);
  $("slamRefreshMapsBtn")?.addEventListener("click", loadSlamMaps);
  $("slamReloadMapBtn")?.addEventListener("click", loadSelectedSlamMap);
  $("slamPickStartBtn")?.addEventListener("click", () => setSlamPickMode("start"));
  $("slamPickGoalBtn")?.addEventListener("click", () => setSlamPickMode("goal"));
  $("slamAddGoalBtn")?.addEventListener("click", () => {
    const goal = createSlamGoal(currentSlamPose());
    state.slam.pickMode = "goal";
    setSlamPoseInputs(goal);
    updateSlamPoseTexts();
    drawSlamMap();
    setText("slamMapHint", `已新增 ${goal.name}，请在地图上点击它的位置。`);
  });
  $("slamDeleteGoalBtn")?.addEventListener("click", deleteSelectedSlamGoal);
  $("slamGoalSelect")?.addEventListener("change", () => selectSlamGoal($("slamGoalSelect")?.value || ""));
  ["slamPoseX", "slamPoseY", "slamPoseTheta"].forEach((id) => {
    $(id)?.addEventListener("change", applySlamPoseInputsToSelection);
  });
  $("slamSyncPoseBtn")?.addEventListener("click", () => runSlamAction("同步当前位姿", () => syncSlamPose(true)).catch(() => null));
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
    await loadSlamMaps(result.map || name);
    return result;
  }));
  $("slamStartNavBtn")?.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    runSlamAction("启动导航系统", async () => {
      state.slam.initialPoseSent = false;
      clearSlamGoalMonitor();
      return postJson("/api/slam/navigation/start", {
        algorithm: $("slamNavAlgorithm")?.value || "dwa",
        map: $("slamMapSelect")?.value || "yahboomcar.yaml",
      });
    }).catch(() => null);
  });
  $("slamSetInitialBtn")?.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    runSlamAction("确认当前位置", sendSlamInitialPose).catch(() => null);
  });
  $("slamSendGoalBtn")?.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    runSlamAction("发送导航目标", sendSlamGoal).catch(() => null);
  });
  $("slamStopBtn")?.addEventListener("click", () => {
    clearSlamGoalMonitor();
    runSlamAction("停止 SLAM/导航", () => postJson("/api/slam/stop", {})).catch(() => null);
  });
  renderSlamGoalList();
}

function setVoiceStatus(status) {
  state.voice.status = status;
  renderVoice();
}

async function toggleVoiceListening() {
  if (state.voice.listening) {
    stopVoiceListening();
    return;
  }
  await startVoiceListening();
}

async function startVoiceListening() {
  if (!state.voice.supported) {
    state.voice.llmOutput = "当前浏览器不支持本地音频处理。";
    setVoiceStatus("error");
    return;
  }
  try {
    const health = await getJson("/api/voice/health").catch((error) => ({ error: error.message || String(error) }));
    if (health.error) {
      state.voice.llmOutput = `语音健康检查失败：${health.error}`;
      setVoiceStatus("error");
      return;
    }
    if (!health.tencent_sdk_available) {
      state.voice.llmOutput = "后端缺少腾讯云 ASR SDK，请先运行：pip install -r backend\\requirements.txt";
      setVoiceStatus("error");
      return;
    }
    if (!health.tencent_configured) {
      state.voice.llmOutput = "腾讯云 ASR 密钥未配置，请检查 TENCENT_SECRET_ID / TENCENT_SECRET_KEY。";
      setVoiceStatus("error");
      return;
    }
    state.voice.wakePhrase = (health.wake_phrases || []).join(" / ") || state.voice.wakePhrase;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    const audioContext = new AudioCtx();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(audioContext.destination);
    processor.onaudioprocess = handleVoiceAudio;

    state.voice.stream = stream;
    state.voice.audioContext = audioContext;
    state.voice.source = source;
    state.voice.processor = processor;
    state.voice.listening = true;
    state.voice.transcript = "";
    state.voice.llmOutput = "";
    state.voice.level = 0;
    setVoiceStatus("listening");
  } catch (error) {
    console.warn("voice start failed", error);
    state.voice.llmOutput = "麦克风启动失败，请检查浏览器权限。";
    setVoiceStatus("error");
  }
}

function stopVoiceListening() {
  finalizeVoiceUtterance(true);
  state.voice.processor?.disconnect();
  state.voice.source?.disconnect();
  state.voice.audioContext?.close();
  state.voice.stream?.getTracks().forEach((track) => track.stop());
  state.voice.stream = null;
  state.voice.audioContext = null;
  state.voice.source = null;
  state.voice.processor = null;
  state.voice.listening = false;
  state.voice.recording = false;
  state.voice.uploading = false;
  state.voice.level = 0;
  setVoiceStatus("idle");
}

function handleVoiceAudio(event) {
  if (!state.voice.listening || state.voice.uploading) return;
  const input = event.inputBuffer.getChannelData(0);
  const chunk = new Float32Array(input);
  const rms = computeRms(chunk);
  const normalizedLevel = Math.min(1, rms * 10);
  state.voice.level = normalizedLevel;

  const sampleRate = event.inputBuffer.sampleRate || 48000;
  const chunkMs = (chunk.length / sampleRate) * 1000;
  const isSpeech = rms >= 0.035;

  if (isSpeech) {
    state.voice.voiceFrames += 1;
  } else {
    state.voice.voiceFrames = 0;
  }

  if (!state.voice.recording && state.voice.voiceFrames >= 2) {
    state.voice.recording = true;
    state.voice.chunks = [];
    state.voice.silenceMs = 0;
    state.voice.speechMs = 0;
    setVoiceStatus("speech");
  }

  if (!state.voice.recording) {
    renderVoice();
    return;
  }

  state.voice.chunks.push(chunk);
  state.voice.speechMs += chunkMs;
  state.voice.silenceMs = isSpeech ? 0 : state.voice.silenceMs + chunkMs;

  if (state.voice.speechMs >= 1800 && state.voice.silenceMs >= 700) {
    finalizeVoiceUtterance(false, sampleRate);
    return;
  }

  if (state.voice.speechMs >= 5000) {
    finalizeVoiceUtterance(false, sampleRate);
    return;
  }

  renderVoice();
}

function finalizeVoiceUtterance(cancelled = false, inputSampleRate = 48000) {
  const chunks = state.voice.chunks;
  state.voice.chunks = [];
  state.voice.recording = false;
  state.voice.silenceMs = 0;
  state.voice.speechMs = 0;
  state.voice.voiceFrames = 0;

  if (cancelled || !chunks.length || state.voice.uploading) {
    if (state.voice.listening) setVoiceStatus("listening");
    return;
  }

  const wavBlob = buildWavBlob(chunks, inputSampleRate, 16000);
  uploadVoiceBlob(wavBlob);
}

async function uploadVoiceBlob(blob) {
  state.voice.uploading = true;
  setVoiceStatus("uploading");
  try {
    const response = await fetch("/api/voice/process", {
      method: "POST",
      headers: {
        "Content-Type": "audio/wav",
        "X-Audio-Format": "wav",
      },
      body: blob,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "voice request failed");
    }
    state.voice.transcript = data.transcript || "";
    state.voice.llmOutput = data.llm_output || (data.wake_phrase_matched ? "已匹配唤醒词" : "未匹配唤醒词");
    state.voice.wakePhrase = data.wake_phrase || state.voice.wakePhrase;
    setVoiceStatus("listening");
  } catch (error) {
    console.warn("voice upload failed", error);
    state.voice.llmOutput = error.message || "语音处理失败";
    setVoiceStatus("error");
  } finally {
    state.voice.uploading = false;
    if (state.voice.listening && state.voice.status !== "error") {
      setVoiceStatus("listening");
    }
  }
}

function computeRms(chunk) {
  let sum = 0;
  for (let i = 0; i < chunk.length; i += 1) {
    sum += chunk[i] * chunk[i];
  }
  return Math.sqrt(sum / Math.max(1, chunk.length));
}

function buildWavBlob(chunks, inputSampleRate, targetSampleRate) {
  const merged = mergeFloat32Chunks(chunks);
  const resampled = resampleFloat32(merged, inputSampleRate, targetSampleRate);
  const wavBuffer = encodeWav16Bit(resampled, targetSampleRate);
  return new Blob([wavBuffer], { type: "audio/wav" });
}

function mergeFloat32Chunks(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function resampleFloat32(input, inputSampleRate, targetSampleRate) {
  if (inputSampleRate === targetSampleRate) {
    return input;
  }
  const ratio = inputSampleRate / targetSampleRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j];
      count += 1;
    }
    output[i] = count ? sum / count : input[start] || 0;
  }
  return output;
}

function encodeWav16Bit(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

function writeAscii(view, offset, value) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

const CRUISE_HEADINGS = ["north", "east", "south", "west"];
const CRUISE_HEADING_LABELS = ["北", "东", "南", "西"];
const CRUISE_TURN_QUARTER_PER_PULSE = 0.1;
const CRUISE_MOVES = [
  { dx: 0, dy: -1 },
  { dx: 1, dy: 0 },
  { dx: 0, dy: 1 },
  { dx: -1, dy: 0 },
];

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function clampCruiseCell(cell) {
  return {
    x: Math.max(0, Math.min(state.cruise.gridWidth - 1, Math.round(Number(cell.x || 0)))),
    y: Math.max(0, Math.min(state.cruise.gridHeight - 1, Math.round(Number(cell.y || 0)))),
  };
}

function cruiseHeadingIndex(heading) {
  return ((Math.round(Number(heading) || 0) % 4) + 4) % 4;
}

function cruiseHeadingQuarter(heading) {
  return ((Number(heading) % 4) + 4) % 4;
}

function cruiseHeadingName(heading) {
  return CRUISE_HEADINGS[cruiseHeadingIndex(heading)] || "north";
}

function cruiseHeadingLabel(heading) {
  const quarter = cruiseHeadingQuarter(heading);
  const degrees = Math.round(quarter * 90);
  return `${CRUISE_HEADING_LABELS[cruiseHeadingIndex(heading)] || "北"} ${degrees}°`;
}

function cruiseSpeed() {
  return clampNumber($("cruiseSpeedInput")?.value, 0.08, 0.18, 0.1);
}

function cruiseForwardMs() {
  return Math.round(clampNumber($("cruiseForwardMsInput")?.value, 120, 1200, 420));
}

function cruiseTurnMs() {
  return Math.round(clampNumber($("cruiseTurnMsInput")?.value, 120, 1200, 360));
}

function cruiseTurnPulsesPerQuarter() {
  return Math.round(clampNumber($("cruiseTurnPulsesInput")?.value, 1, 20, 10));
}

function cruiseTurnaroundPulses() {
  return Math.round(clampNumber($("cruiseTurnaroundPulsesInput")?.value, 8, 36, 19));
}

function cruiseGridWidthInput() {
  return Math.round(clampNumber($("cruiseGridWidthInput")?.value, 12, 160, 48));
}

function cruiseGridHeightInput() {
  return Math.round(clampNumber($("cruiseGridHeightInput")?.value, 8, 160, 32));
}

function cruiseStepMeters() {
  return clampNumber($("cruiseStepMetersInput")?.value, 0.05, 1, 0.25);
}

function cruiseDwellMs() {
  return Math.round(clampNumber($("cruiseDwellInput")?.value, 1, 60, 5) * 1000);
}

function cruiseTurnPenalty() {
  return clampNumber($("cruiseTurnPenaltyInput")?.value, 0, 3, 0.35);
}

function cruiseLog(message) {
  const time = new Date().toLocaleTimeString();
  state.cruise.log.unshift(`[${time}] ${message}`);
  state.cruise.log = state.cruise.log.slice(0, 80);
  const log = $("cruiseCommandLog");
  if (log) log.textContent = state.cruise.log.join("\n") || "暂无巡航日志";
}

function setCruiseStatus(message) {
  setText("cruiseStatusText", message);
  setText("cruiseMapHint", message);
}

function cruiseFrame() {
  const canvas = $("cruiseCanvas");
  if (!canvas) return null;
  const cell = Math.min(canvas.width / state.cruise.gridWidth, canvas.height / state.cruise.gridHeight);
  const width = cell * state.cruise.gridWidth;
  const height = cell * state.cruise.gridHeight;
  return {
    canvas,
    cell,
    ox: (canvas.width - width) / 2,
    oy: (canvas.height - height) / 2,
    width,
    height,
  };
}

function cruiseCellToCanvas(cell) {
  const frame = cruiseFrame();
  if (!frame) return { x: 0, y: 0 };
  return {
    x: frame.ox + (Number(cell.x) + 0.5) * frame.cell,
    y: frame.oy + (Number(cell.y) + 0.5) * frame.cell,
  };
}

function cruiseCanvasToCell(event) {
  const frame = cruiseFrame();
  if (!frame) return null;
  const rect = frame.canvas.getBoundingClientRect();
  const sx = frame.canvas.width / rect.width;
  const sy = frame.canvas.height / rect.height;
  const x = (event.clientX - rect.left) * sx;
  const y = (event.clientY - rect.top) * sy;
  const gx = Math.floor((x - frame.ox) / frame.cell);
  const gy = Math.floor((y - frame.oy) / frame.cell);
  if (gx < 0 || gy < 0 || gx >= state.cruise.gridWidth || gy >= state.cruise.gridHeight) return null;
  return { x: gx, y: gy };
}

function cruiseCellKey(cell) {
  return `${cell.x},${cell.y}`;
}

function cruiseHasObstacle(cell) {
  const key = cruiseCellKey(cell);
  return state.cruise.obstacles.some((item) => cruiseCellKey(item) === key);
}

function cruiseWaypointAt(cell) {
  const key = cruiseCellKey(cell);
  return state.cruise.waypoints.find((point) => cruiseCellKey(point) === key) || null;
}

function clearCruisePlan() {
  state.cruise.plan = null;
  setText("cruisePlanSummary", "未规划");
}

function updateCruisePoseText() {
  const pose = state.cruise.pose;
  setText("cruisePoseText", `(${pose.x}, ${pose.y}) · 朝${cruiseHeadingLabel(pose.heading)}`);
  setText("cruiseWaypointCount", String(state.cruise.waypoints.length));
  if (state.cruise.plan?.totals) {
    const totals = state.cruise.plan.totals;
    const meters = Number(totals.distance_cells || 0) * cruiseStepMeters();
    setText("cruisePlanSummary", `${totals.distance_cells} 格 ≈ ${meters.toFixed(2)}m · ${totals.turns} 次转弯 · ${totals.move_commands} 条动作`);
  }
}

function renderCruisePage() {
  renderCruiseCanvas();
  renderCruiseWaypoints();
  renderCruiseRoutes();
  updateCruisePoseText();
}

function renderCruiseCanvas() {
  const frame = cruiseFrame();
  if (!frame) return;
  const { canvas, cell, ox, oy, width, height } = frame;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#06101f";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(120, 240, 255, 0.12)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= state.cruise.gridWidth; x += 1) {
    ctx.beginPath();
    ctx.moveTo(ox + x * cell, oy);
    ctx.lineTo(ox + x * cell, oy + height);
    ctx.stroke();
  }
  for (let y = 0; y <= state.cruise.gridHeight; y += 1) {
    ctx.beginPath();
    ctx.moveTo(ox, oy + y * cell);
    ctx.lineTo(ox + width, oy + y * cell);
    ctx.stroke();
  }
  state.cruise.obstacles.forEach((item) => {
    ctx.fillStyle = "rgba(255, 95, 115, 0.45)";
    ctx.fillRect(ox + item.x * cell + 2, oy + item.y * cell + 2, cell - 4, cell - 4);
  });
  drawCruiseRoute(ctx);
  state.cruise.waypoints.forEach((point, index) => drawCruiseWaypoint(ctx, point, index));
  drawCruisePose(ctx);
}

function drawCruiseRoute(ctx) {
  const route = state.cruise.plan?.route || [];
  if (route.length < 2) return;
  ctx.save();
  ctx.lineWidth = 4;
  ctx.strokeStyle = "rgba(38, 244, 255, 0.82)";
  ctx.setLineDash([10, 7]);
  ctx.beginPath();
  route.forEach((cell, index) => {
    const point = cruiseCellToCanvas(cell);
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
  ctx.restore();
}

function drawCruiseWaypoint(ctx, point, index) {
  const canvasPoint = cruiseCellToCanvas(point);
  const selected = point.id === state.cruise.selectedWaypointId;
  ctx.save();
  ctx.fillStyle = point.color || state.cruise.colors[index % state.cruise.colors.length];
  ctx.strokeStyle = selected ? "#ffffff" : "rgba(255, 255, 255, 0.55)";
  ctx.lineWidth = selected ? 4 : 2;
  ctx.beginPath();
  ctx.arc(canvasPoint.x, canvasPoint.y, selected ? 13 : 11, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#04101a";
  ctx.font = "bold 13px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(index + 1), canvasPoint.x, canvasPoint.y);
  ctx.restore();
}

function drawCruisePose(ctx) {
  const pose = state.cruise.pose;
  const point = cruiseCellToCanvas(pose);
  const angle = cruiseHeadingQuarter(pose.heading) * Math.PI / 2;
  const move = { dx: Math.sin(angle), dy: -Math.cos(angle) };
  ctx.save();
  ctx.fillStyle = "#7dff9b";
  ctx.strokeStyle = "rgba(4, 16, 26, 0.9)";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(point.x, point.y, 10, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = "#7dff9b";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(point.x, point.y);
  ctx.lineTo(point.x + move.dx * 20, point.y + move.dy * 20);
  ctx.stroke();
  ctx.restore();
}

function renderCruiseWaypoints() {
  const list = $("cruiseWaypointList");
  if (!list) return;
  if (!state.cruise.waypoints.length) {
    list.innerHTML = `<div class="goal-empty">还没有途经点</div>`;
    return;
  }
  list.innerHTML = state.cruise.waypoints.map((point, index) => `
    <button class="cruise-point-item ${point.id === state.cruise.selectedWaypointId ? "active" : ""}" data-cruise-point="${escapeHtml(point.id)}" type="button">
      <span class="cruise-point-swatch" style="background:${escapeHtml(point.color)}"></span>
      <span><strong>${index + 1}. ${escapeHtml(point.name)}</strong><small>(${point.x}, ${point.y}) · 朝${cruiseHeadingLabel(point.heading)}</small></span>
      <small>${point.id === state.cruise.selectedWaypointId ? "已选中" : "选择"}</small>
    </button>
  `).join("");
  list.querySelectorAll("[data-cruise-point]").forEach((button) => {
    button.addEventListener("click", () => {
      selectCruiseWaypoint(button.dataset.cruisePoint || "");
    });
  });
}

function renderCruiseRoutes() {
  const select = $("cruiseRouteSelect");
  if (!select) return;
  const current = select.value;
  if (!state.cruise.savedRoutes.length) {
    select.innerHTML = `<option value="">暂无保存路线</option>`;
    return;
  }
  select.innerHTML = state.cruise.savedRoutes.map((route) => (
    `<option value="${escapeHtml(route.id)}">${escapeHtml(route.name || route.id)}</option>`
  )).join("");
  if (state.cruise.savedRoutes.some((route) => route.id === current)) {
    select.value = current;
  }
}

function selectCruiseWaypoint(id) {
  state.cruise.selectedWaypointId = id;
  const point = state.cruise.waypoints.find((item) => item.id === id);
  if (point) {
    const input = $("cruiseWaypointNameInput");
    if (input) input.value = point.name || "";
    setCruiseStatus(`已选择 ${point.name}，点击网格可调整它的位置。`);
  }
  renderCruisePage();
}

function selectedCruiseWaypointIndex() {
  return state.cruise.waypoints.findIndex((point) => point.id === state.cruise.selectedWaypointId);
}

function saveCruiseWaypoint() {
  const pose = state.cruise.pose;
  if (cruiseHasObstacle(pose)) {
    setCruiseStatus("当前位置是障碍格，不能保存途经点。");
    return;
  }
  const existing = cruiseWaypointAt(pose);
  if (existing) {
    state.cruise.selectedWaypointId = existing.id;
    setCruiseStatus(`${existing.name} 已在当前位置。`);
    renderCruisePage();
    return;
  }
  const index = state.cruise.nextWaypointNumber++;
  const point = {
    id: `wp-${Date.now()}-${index}`,
    name: `途经点 ${index}`,
    x: pose.x,
    y: pose.y,
    heading: pose.heading,
    color: state.cruise.colors[state.cruise.waypoints.length % state.cruise.colors.length],
  };
  state.cruise.waypoints.push(point);
  state.cruise.selectedWaypointId = point.id;
  clearCruisePlan();
  setCruiseStatus(`已保存 ${point.name}。`);
  renderCruisePage();
}

function moveCruiseWaypoint(delta) {
  const index = selectedCruiseWaypointIndex();
  if (index < 0) return;
  const next = index + delta;
  if (next < 0 || next >= state.cruise.waypoints.length) return;
  const [point] = state.cruise.waypoints.splice(index, 1);
  state.cruise.waypoints.splice(next, 0, point);
  clearCruisePlan();
  setCruiseStatus(`已调整 ${point.name} 的巡航顺序。`);
  renderCruisePage();
}

function deleteCruiseWaypoint() {
  const index = selectedCruiseWaypointIndex();
  if (index < 0) return;
  const [point] = state.cruise.waypoints.splice(index, 1);
  const next = state.cruise.waypoints[Math.min(index, state.cruise.waypoints.length - 1)];
  state.cruise.selectedWaypointId = next?.id || "";
  clearCruisePlan();
  setCruiseStatus(`已删除 ${point.name}。`);
  renderCruisePage();
}

function clearCruiseWaypoints() {
  state.cruise.waypoints = [];
  state.cruise.selectedWaypointId = "";
  state.cruise.nextWaypointNumber = 1;
  clearCruisePlan();
  setCruiseStatus("途经点已清空。");
  renderCruisePage();
}

function renameSelectedCruiseWaypoint() {
  const index = selectedCruiseWaypointIndex();
  if (index < 0) {
    setCruiseStatus("请先选择一个途经点。");
    return;
  }
  const input = $("cruiseWaypointNameInput");
  const name = (input?.value || "").trim();
  if (!name) {
    setCruiseStatus("请输入途经点名称。");
    return;
  }
  state.cruise.waypoints[index].name = name.slice(0, 24);
  clearCruisePlan();
  setCruiseStatus(`已修改为 ${state.cruise.waypoints[index].name}。`);
  renderCruisePage();
}

function applyCruiseGridSize() {
  state.cruise.gridWidth = cruiseGridWidthInput();
  state.cruise.gridHeight = cruiseGridHeightInput();
  state.cruise.pose = clampCruiseCell(state.cruise.pose);
  state.cruise.waypoints = state.cruise.waypoints.map((point) => ({
    ...point,
    ...clampCruiseCell(point),
  }));
  const seen = new Set();
  state.cruise.obstacles = state.cruise.obstacles
    .map(clampCruiseCell)
    .filter((item) => {
      const key = cruiseCellKey(item);
      if (seen.has(key) || cruiseWaypointAt(item)) return false;
      seen.add(key);
      return true;
    });
  clearCruisePlan();
  setCruiseStatus(`巡航网格已调整为 ${state.cruise.gridWidth} × ${state.cruise.gridHeight}。`);
  renderCruisePage();
}

function handleCruiseCanvasClick(event) {
  const cell = cruiseCanvasToCell(event);
  if (!cell) return;
  const key = cruiseCellKey(cell);
  if (state.cruise.selectedMode === "obstacle") {
    const index = state.cruise.obstacles.findIndex((item) => cruiseCellKey(item) === key);
    if (index >= 0) state.cruise.obstacles.splice(index, 1);
    else if (!cruiseWaypointAt(cell)) state.cruise.obstacles.push(cell);
    clearCruisePlan();
    renderCruisePage();
    return;
  }
  const selected = state.cruise.waypoints.find((point) => point.id === state.cruise.selectedWaypointId);
  if (selected && !cruiseHasObstacle(cell)) {
    const occupied = cruiseWaypointAt(cell);
    if (occupied && occupied.id !== selected.id) {
      setCruiseStatus("该格已有途经点。");
      return;
    }
    selected.x = cell.x;
    selected.y = cell.y;
    clearCruisePlan();
    setCruiseStatus(`已移动 ${selected.name}。`);
  } else if (!cruiseHasObstacle(cell)) {
    state.cruise.pose = { ...state.cruise.pose, ...cell };
    setCruiseStatus("已移动当前位置估计。");
  }
  renderCruisePage();
}

function setCruiseEditMode(mode) {
  state.cruise.selectedMode = mode === "obstacle" ? "obstacle" : "select";
  $("cruiseSelectBtn")?.classList.toggle("active", state.cruise.selectedMode === "select");
  $("cruiseObstacleBtn")?.classList.toggle("active", state.cruise.selectedMode === "obstacle");
  setCruiseStatus(state.cruise.selectedMode === "obstacle" ? "点击网格可添加或取消障碍。" : "点击途经点后，可在网格上移动它。");
}

function resetCruisePose() {
  state.cruise.pose = { x: 3, y: state.cruise.gridHeight - 4, heading: 0 };
  setCruiseStatus("当前位置估计已归零。");
  renderCruisePage();
}

function updateCruisePoseByDirection(direction) {
  const pose = state.cruise.pose;
  if (direction === "left") {
    pose.heading = cruiseHeadingQuarter(pose.heading - CRUISE_TURN_QUARTER_PER_PULSE);
  } else if (direction === "right") {
    pose.heading = cruiseHeadingQuarter(pose.heading + CRUISE_TURN_QUARTER_PER_PULSE);
  } else if (direction === "forward" || direction === "backward") {
    const move = CRUISE_MOVES[cruiseHeadingIndex(pose.heading)] || CRUISE_MOVES[0];
    const sign = direction === "forward" ? 1 : -1;
    const next = clampCruiseCell({ x: pose.x + move.dx * sign, y: pose.y + move.dy * sign });
    if (!cruiseHasObstacle(next)) {
      pose.x = next.x;
      pose.y = next.y;
    }
  }
}

async function sendCruiseManual(direction) {
  if (!direction) return;
  if (direction === "stop") {
    await sendStopNow(true);
    cruiseLog("已发送停止");
    return;
  }
  const duration = direction === "forward" || direction === "backward" ? cruiseForwardMs() : cruiseTurnMs();
  await postJson("/api/control/manual", {
    direction,
    speed: cruiseSpeed(),
    duration_ms: duration,
    precision: true,
    source: "cruise",
  });
  updateCruisePoseByDirection(direction);
  cruiseLog(`遥控 ${direction} · ${duration}ms`);
  if (!state.cruise.running) clearCruisePlan();
  renderCruisePage();
}

async function sendCruiseContinuousTurn(direction, totalMs) {
  const startedAt = Date.now();
  cruiseLog(`连续${direction === "left" ? "左" : "右"}掉头 · ${Math.round(totalMs)}ms`);
  while (Date.now() - startedAt < totalMs) {
    await waitCruiseReady();
    await postJson("/api/control/manual", {
      direction,
      speed: cruiseSpeed(),
      duration_ms: 0,
      hold: true,
      precision: true,
      source: "cruise",
    });
    await waitCruise(220);
  }
  await sendStopNow(true);
}

function cruisePlanPayload() {
  return {
    grid: {
      width: state.cruise.gridWidth,
      height: state.cruise.gridHeight,
    },
    waypoints: state.cruise.waypoints.map((point, index) => ({
      id: point.id,
      name: point.name || `途经点 ${index + 1}`,
      x: point.x,
      y: point.y,
      heading: cruiseHeadingName(point.heading),
      color: point.color,
    })),
    obstacles: state.cruise.obstacles,
    start_heading: cruiseHeadingName(state.cruise.waypoints[0]?.heading ?? state.cruise.pose.heading),
    route_mode: "out_and_back",
    turn_penalty: cruiseTurnPenalty(),
  };
}

function cruiseRoutePayload() {
  return {
    grid: { width: state.cruise.gridWidth, height: state.cruise.gridHeight },
    pose: state.cruise.pose,
    waypoints: state.cruise.waypoints,
    obstacles: state.cruise.obstacles,
    settings: {
      speed: cruiseSpeed(),
      forward_ms: cruiseForwardMs(),
      turn_ms: cruiseTurnMs(),
      turn_pulses_per_90: cruiseTurnPulsesPerQuarter(),
      turnaround_pulses: cruiseTurnaroundPulses(),
      step_meters: cruiseStepMeters(),
      dwell_seconds: Math.round(cruiseDwellMs() / 1000),
      turn_penalty: cruiseTurnPenalty(),
      mode: $("cruiseModeSelect")?.value || "once",
      repeat_count: Math.round(clampNumber($("cruiseRepeatInput")?.value, 1, 20, 1)),
    },
    plan: state.cruise.plan,
  };
}

async function loadCruiseRoutes() {
  try {
    const data = await getJson("/api/cruise/routes");
    state.cruise.savedRoutes = data.routes || [];
    renderCruiseRoutes();
  } catch (error) {
    console.warn("load cruise routes failed", error);
  }
}

async function saveCruiseRoute() {
  if (state.cruise.waypoints.length < 3) {
    setCruiseStatus("请先保存至少 3 个途经点，再保存路线。");
    return;
  }
  const name = ($("cruiseRouteNameInput")?.value || "").trim() || "路线1";
  const plan = state.cruise.plan || await planCruiseRoute();
  if (!plan?.ok) return;
  const existingId = $("cruiseRouteSelect")?.value || "";
  const result = await postJson("/api/cruise/routes", {
    id: existingId || undefined,
    name,
    route: { ...cruiseRoutePayload(), plan },
  });
  const saved = result.route;
  const index = state.cruise.savedRoutes.findIndex((route) => route.id === saved.id);
  if (index >= 0) state.cruise.savedRoutes.splice(index, 1, saved);
  else state.cruise.savedRoutes.unshift(saved);
  renderCruiseRoutes();
  const select = $("cruiseRouteSelect");
  if (select) select.value = saved.id;
  setCruiseStatus(`已保存路线：${saved.name}。`);
  cruiseLog(`路线已保存：${saved.name}`);
}

function applyCruiseRoute(route) {
  const data = route?.route || {};
  const grid = data.grid || {};
  state.cruise.gridWidth = Math.round(clampNumber(grid.width, 12, 160, 48));
  state.cruise.gridHeight = Math.round(clampNumber(grid.height, 8, 160, 32));
  const widthInput = $("cruiseGridWidthInput");
  const heightInput = $("cruiseGridHeightInput");
  if (widthInput) widthInput.value = String(state.cruise.gridWidth);
  if (heightInput) heightInput.value = String(state.cruise.gridHeight);
  state.cruise.pose = clampCruiseCell(data.pose || { x: 3, y: state.cruise.gridHeight - 4, heading: 0 });
  state.cruise.waypoints = Array.isArray(data.waypoints) ? data.waypoints.map((point, index) => ({
    ...point,
    ...clampCruiseCell(point),
    id: point.id || `wp-${Date.now()}-${index}`,
    name: point.name || `途经点 ${index + 1}`,
    color: point.color || state.cruise.colors[index % state.cruise.colors.length],
    heading: Number(point.heading || 0),
  })) : [];
  state.cruise.obstacles = Array.isArray(data.obstacles) ? data.obstacles.map(clampCruiseCell) : [];
  state.cruise.selectedWaypointId = state.cruise.waypoints[0]?.id || "";
  state.cruise.nextWaypointNumber = state.cruise.waypoints.length + 1;
  const settings = data.settings || {};
  const setValue = (id, value) => {
    const node = $(id);
    if (node && value !== undefined && value !== null) node.value = String(value);
  };
  setValue("cruiseSpeedInput", settings.speed);
  setValue("cruiseForwardMsInput", settings.forward_ms);
  setValue("cruiseTurnMsInput", settings.turn_ms);
  setValue("cruiseTurnPulsesInput", settings.turn_pulses_per_90);
  setValue("cruiseTurnaroundPulsesInput", settings.turnaround_pulses);
  setValue("cruiseStepMetersInput", settings.step_meters);
  setValue("cruiseDwellInput", settings.dwell_seconds);
  setValue("cruiseTurnPenaltyInput", settings.turn_penalty);
  setValue("cruiseRepeatInput", settings.repeat_count);
  setValue("cruiseModeSelect", settings.mode);
  setValue("cruiseRouteNameInput", route.name || "");
  state.cruise.plan = data.plan || null;
  setCruiseStatus(`已加载路线：${route.name || route.id}。`);
  renderCruisePage();
}

function loadSelectedCruiseRoute() {
  const id = $("cruiseRouteSelect")?.value || "";
  const route = state.cruise.savedRoutes.find((item) => item.id === id);
  if (!route) {
    setCruiseStatus("请选择一条已保存路线。");
    return;
  }
  applyCruiseRoute(route);
}

async function planCruiseRoute() {
  if (state.cruise.waypoints.length < 3) {
    setCruiseStatus("请先保存至少 3 个途经点。");
    return null;
  }
  setCruiseStatus("正在规划 A* 巡航路线...");
  const plan = await postJson("/api/cruise/plan", cruisePlanPayload());
  state.cruise.plan = plan;
  const first = state.cruise.waypoints[0];
  state.cruise.pose = { x: first.x, y: first.y, heading: first.heading ?? state.cruise.pose.heading };
  const totals = plan.totals || {};
  const meters = Number(totals.distance_cells || 0) * cruiseStepMeters();
  cruiseLog(`规划完成：${totals.distance_cells || 0} 格，约 ${meters.toFixed(2)}m，${totals.turns || 0} 次转弯，${totals.move_commands || 0} 条动作`);
  setCruiseStatus("路线已规划。开始前请确认小车已经回到第一个途经点。");
  renderCruisePage();
  return plan;
}

function cruiseRepeatTarget() {
  const mode = $("cruiseModeSelect")?.value || "once";
  if (mode === "loop") return Infinity;
  if (mode === "repeat") return Math.round(clampNumber($("cruiseRepeatInput")?.value, 1, 20, 1));
  return 1;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitCruise(ms) {
  let remaining = ms;
  let last = Date.now();
  while (remaining > 0) {
    if (state.cruise.stopRequested) throw new Error("cruise stopped");
    if (!state.cruise.paused) {
      const now = Date.now();
      remaining -= now - last;
      last = now;
      await sleep(120);
    } else {
      last = Date.now();
      await sleep(180);
    }
  }
}

async function waitCruiseReady() {
  while (state.cruise.paused) {
    if (state.cruise.stopRequested) throw new Error("cruise stopped");
    await sleep(180);
  }
  if (state.cruise.stopRequested) throw new Error("cruise stopped");
}

async function executeCruiseCommand(command) {
  await waitCruiseReady();
  if (command.type === "move") {
    const repeats = command.direction === "left" || command.direction === "right"
      ? cruiseTurnPulsesPerQuarter()
      : 1;
    for (let index = 0; index < repeats; index += 1) {
      await waitCruiseReady();
      await sendCruiseManual(command.direction);
      if (repeats > 1) await waitCruise(80);
    }
    return;
  }
  if (command.type === "turnaround") {
    const direction = command.direction || "left";
    await sendCruiseContinuousTurn(direction, cruiseTurnMs() * cruiseTurnaroundPulses());
    state.cruise.pose.heading = cruiseHeadingQuarter(state.cruise.pose.heading + 2);
    cruiseLog("掉头完成");
    renderCruisePage();
    return;
  }
  if (command.type === "arrive") {
    cruiseLog(`到达 ${command.waypoint_name || command.waypoint_id}`);
    await sendAuxControl("buzzer", { duration_ms: 180 });
    await waitCruise(cruiseDwellMs());
  }
}

async function startCruiseExecution() {
  if (state.cruise.running) {
    setCruiseStatus("巡航正在执行中。");
    return;
  }
  const plan = state.cruise.plan || await planCruiseRoute();
  if (!plan?.commands?.length) return;
  const first = state.cruise.waypoints[0];
  state.cruise.pose = { x: first.x, y: first.y, heading: first.heading ?? state.cruise.pose.heading };
  state.cruise.running = true;
  state.cruise.paused = false;
  state.cruise.stopRequested = false;
  const targetRepeats = cruiseRepeatTarget();
  cruiseLog("巡航开始");
  setCruiseStatus("巡航执行中。");
  state.cruise.executionPromise = (async () => {
    let round = 0;
    try {
      while (!state.cruise.stopRequested && round < targetRepeats) {
        round += 1;
        cruiseLog(`第 ${round} 轮巡航`);
        for (const command of plan.commands) {
          await executeCruiseCommand(command);
        }
      }
      if (!state.cruise.stopRequested) {
        setCruiseStatus("巡航完成。");
        cruiseLog("巡航完成");
      }
    } catch (error) {
      if (!state.cruise.stopRequested) {
        console.warn("cruise execution failed", error);
        setCruiseStatus(`巡航中断：${error.message || error}`);
        cruiseLog(`巡航中断：${error.message || error}`);
      }
    } finally {
      state.cruise.running = false;
      state.cruise.paused = false;
      state.cruise.stopRequested = false;
      await sendStopNow(true);
      renderCruisePage();
    }
  })();
}

function toggleCruisePause() {
  if (!state.cruise.running) return;
  state.cruise.paused = !state.cruise.paused;
  setCruiseStatus(state.cruise.paused ? "巡航已暂停。" : "巡航继续执行。");
  cruiseLog(state.cruise.paused ? "巡航暂停" : "巡航继续");
  if (state.cruise.paused) sendStopNow(true);
}

async function stopCruiseExecution() {
  state.cruise.stopRequested = true;
  state.cruise.paused = false;
  await sendStopNow(true);
  state.cruise.running = false;
  setCruiseStatus("巡航已停止。");
  cruiseLog("巡航停止");
  renderCruisePage();
}

function bindCruiseEvents() {
  $("cruiseCanvas")?.addEventListener("click", handleCruiseCanvasClick);
  $("cruiseSelectBtn")?.addEventListener("click", () => setCruiseEditMode("select"));
  $("cruiseObstacleBtn")?.addEventListener("click", () => setCruiseEditMode("obstacle"));
  $("cruiseClearObstaclesBtn")?.addEventListener("click", () => {
    state.cruise.obstacles = [];
    clearCruisePlan();
    setCruiseStatus("障碍已清空。");
    renderCruisePage();
  });
  $("cruiseResetPoseBtn")?.addEventListener("click", resetCruisePose);
  $("cruiseSaveWaypointBtn")?.addEventListener("click", saveCruiseWaypoint);
  $("cruiseRenameWaypointBtn")?.addEventListener("click", renameSelectedCruiseWaypoint);
  $("cruiseMovePointUpBtn")?.addEventListener("click", () => moveCruiseWaypoint(-1));
  $("cruiseMovePointDownBtn")?.addEventListener("click", () => moveCruiseWaypoint(1));
  $("cruiseDeletePointBtn")?.addEventListener("click", deleteCruiseWaypoint);
  $("cruiseClearPointsBtn")?.addEventListener("click", clearCruiseWaypoints);
  $("cruiseSaveRouteBtn")?.addEventListener("click", () => {
    saveCruiseRoute().catch((error) => {
      console.warn("save cruise route failed", error);
      setCruiseStatus(`保存路线失败：${error.message || error}`);
    });
  });
  $("cruiseLoadRouteBtn")?.addEventListener("click", loadSelectedCruiseRoute);
  $("cruisePlanBtn")?.addEventListener("click", () => {
    planCruiseRoute().catch((error) => {
      console.warn("cruise plan failed", error);
      setCruiseStatus(`规划失败：${error.message || error}`);
    });
  });
  $("cruiseStartBtn")?.addEventListener("click", () => {
    startCruiseExecution().catch((error) => {
      console.warn("cruise start failed", error);
      setCruiseStatus(`巡航启动失败：${error.message || error}`);
    });
  });
  $("cruisePauseBtn")?.addEventListener("click", toggleCruisePause);
  $("cruiseStopBtn")?.addEventListener("click", () => {
    stopCruiseExecution().catch((error) => console.warn("cruise stop failed", error));
  });
  document.querySelectorAll(".cruise-dpad button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      sendCruiseManual(button.dataset.dir).catch((error) => {
        console.warn("cruise manual failed", error);
        setCruiseStatus(`遥控失败：${error.message || error}`);
      });
    });
  });
  ["cruiseTurnPenaltyInput", "cruiseStepMetersInput", "cruiseTurnPulsesInput", "cruiseTurnaroundPulsesInput"].forEach((id) => {
    $(id)?.addEventListener("change", () => {
      clearCruisePlan();
      renderCruisePage();
    });
  });
  ["cruiseGridWidthInput", "cruiseGridHeightInput"].forEach((id) => {
    $(id)?.addEventListener("change", applyCruiseGridSize);
  });
  setCruiseEditMode("select");
  loadCruiseRoutes().catch((error) => console.warn("load cruise routes failed", error));
  renderCruisePage();
}

function speakLocalCue(text) {
  try {
    if (!("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  } catch (error) {
    console.warn("local speech failed", error);
  }
}

async function playBuzzerCue() {
  await sendAuxControl("buzzer", { duration_ms: 260 });
}

async function playVoiceCue() {
  await sendAuxControl("voice", { text: "主人，我在", volume_percent: 85 });
}

function bindEvents() {
  initConnectionInput();
  $("connectBtn")?.addEventListener("click", connect);
  $("disconnectBtn")?.addEventListener("click", disconnect);
  $("estopBtn")?.addEventListener("click", emergencyStop);
  $("reconnectCarBtn")?.addEventListener("click", reconnectCar);
  $("stopTaskBtn")?.addEventListener("click", stopNavigationTask);
  $("detectBtn")?.addEventListener("click", detectVisionOnce);
  $("visionStartBtn")?.addEventListener("click", startVisionDetection);
  $("visionStopBtn")?.addEventListener("click", stopVisionDetection);
  $("visionTargetSelect")?.addEventListener("change", () => {
    state.visionControl.targets = selectedVisionTargets();
    renderVisionPage();
  });
  $("lightToggleBtn")?.addEventListener("click", toggleLight);
  $("buzzerBtn")?.addEventListener("click", playBuzzerCue);
  $("voicePlayBtn")?.addEventListener("click", playVoiceCue);
  $("followLineBtn")?.addEventListener("click", toggleFollowLine);
  $("cameraAutoBtn")?.addEventListener("click", () => startCameraAuto());
  $("cameraNextBtn")?.addEventListener("click", () => {
    state.camera.attempts = 0;
    startCameraNext();
  });
  $("cameraStopBtn")?.addEventListener("click", stopCamera);
  $("cameraSelect")?.addEventListener("change", () => {
    state.camera.attempts = 0;
    startCameraAt(Number($("cameraSelect")?.value || 0));
  });
  $("gestureToggleBtn")?.addEventListener("click", () => {
    toggleGestureControl();
  });
  $("speedRange")?.addEventListener("input", updateSpeedDisplay);
  $("voiceToggleBtn")?.addEventListener("click", () => {
    toggleVoiceListening();
  });
  updateSpeedDisplay();
  document.querySelectorAll(".neon-dpad button").forEach((button) => {
    bindManualButton(button);
  });
  if (page === "navigation") bindSlamEvents();
  if (page === "cruise") bindCruiseEvents();
  window.addEventListener("blur", () => sendStopNow());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) sendStopNow();
  });
  if (page === "vision") {
    loadVisionStatus();
  }
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
  if (page === "cruise") {
    renderCruisePage();
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
