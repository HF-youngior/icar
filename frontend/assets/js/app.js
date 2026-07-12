const page = document.body.dataset.page || "dashboard";
const state = {
  ws: null,
  connected: false,
  manualHoldTimer: null,
  manualDirection: null,
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
  const labels = { online: "宸茶繛鎺?, offline: "绂荤嚎", connecting: "杩炴帴涓?, error: "杩炴帴澶辫触" };
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
    const text = await response.text();
    throw new Error(text || `request failed: ${response.status}`);
  }
  return response.json().catch(() => ({}));
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
  setText("robotTarget", `鐩爣锛?{robot.target || "鏃?}`);
  setText("robotError", robot.last_error || "鏃?);
  setText("batteryText", robot.battery ? `${robot.battery}%` : "--%");
  setText("navMessage", navigation.message || "绛夊緟浠诲姟");
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
      meta: `${item.timestamp} 路 鍛婅 路 ${item.level}`,
      level: item.level,
    })),
    ...state.snapshot.vision.slice(0, 3).map((item) => ({
      title: `瑙嗚妫€娴嬶細${item.label_zh || item.label}`,
      meta: `${item.timestamp} 路 缃俊搴?${Math.round((item.confidence || 0) * 100)}%`,
      level: item.risk === "warning" ? "warning" : "normal",
    })),
    ...state.snapshot.reports.slice(0, 3).map((item) => ({
      title: item.title,
      meta: `${item.timestamp} 路 ${item.summary}`,
      level: "normal",
    })),
  ].slice(0, 8);
  timeline.innerHTML = events.length
    ? events.map(renderTimelineItem).join("")
    : `<div class="timeline-item"><strong>鏆傛棤浜嬩欢</strong><span>杩炴帴鍚庝細鏄剧ず瀹炴椂浜嬩欢</span></div>`;
}

function renderControl() {
  renderCommon();
  renderVoice();
}

function renderNavigation() {
  renderPoints();
  renderRoutes();
  drawMap();
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
  if (events.length) {
    const latest = events[0];
    setText("visionSummary", `${latest.label_zh || latest.label} 路 ${Math.round((latest.confidence || 0) * 100)}%`);
    const image = $("visionImage");
    if (image && latest.image_url) image.src = latest.image_url;
  }
  if (list) {
    list.innerHTML = events.length
      ? events.slice(0, 12).map((event) => renderTimelineItem({
        title: event.label_zh || event.label,
        meta: `${event.timestamp || ""} 路 缃俊搴?${Math.round((event.confidence || 0) * 100)}% 路 ${event.source || ""}`,
        level: event.risk === "warning" ? "warning" : "normal",
      })).join("")
      : `<div class="timeline-item"><strong>鏆傛棤妫€娴?/strong><span>鐐瑰嚮妫€娴嬩竴娆℃垨绛夊緟妯℃嫙妫€娴嬩簨浠?/span></div>`;
  }
}

function renderAlarmsPage() {
  const list = $("alarmList");
  const alarms = state.snapshot.alarms || [];
  const open = alarms.filter((alarm) => alarm.status !== "confirmed");
  setText("alarmSummary", open.length ? `${open.length} 鏉″緟澶勭悊鍛婅` : "鏆傛棤寰呭鐞嗗憡璀?);
  if (!list) return;
  list.innerHTML = alarms.length
    ? alarms.slice(0, 30).map((alarm) => `
      <div class="alarm-item level-${alarm.level || "normal"}">
        <div>
          <strong>${escapeHtml(alarm.message)}</strong>
          <span>${alarm.timestamp || ""} 路 ${alarm.source || ""} 路 ${alarm.status || ""}</span>
        </div>
        <button class="neon-btn ghost" data-alarm="${alarm.alarm_id}" ${alarm.status === "confirmed" ? "disabled" : ""}>纭</button>
      </div>
    `).join("")
    : `<div class="alarm-item"><div><strong>鏆傛棤鍛婅</strong><span>浼犳劅鍣ㄣ€佽瑙夊拰鎬ュ仠浜嬩欢浼氭樉绀哄湪杩欓噷</span></div></div>`;
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
        <span>${report.timestamp || ""} 路 ${escapeHtml(report.summary || "")}</span>
      </div>
    `).join("")
    : `<div class="report-item"><strong>鏆傛棤鎶ュ憡</strong><span>瀵艰埅鍒拌揪鎴栧贰閫诲畬鎴愬悗浼氱敓鎴愭姤鍛?/span></div>`;
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
    state.voice.llmOutput = "褰撳墠娴忚鍣ㄤ笉鏀寔鏈湴闊抽澶勭悊銆?;
    setVoiceStatus("error");
    return;
  }
  try {
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
    state.voice.llmOutput = "楹﹀厠椋庡惎鍔ㄥけ璐ワ紝璇锋鏌ユ祻瑙堝櫒鏉冮檺銆?;
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
    state.voice.llmOutput = data.llm_output || (data.wake_phrase_matched ? "宸插尮閰嶅敜閱掕瘝" : "鏈尮閰嶅敜閱掕瘝");
    state.voice.wakePhrase = data.wake_phrase || state.voice.wakePhrase;
    setVoiceStatus("listening");
  } catch (error) {
    console.warn("voice upload failed", error);
    state.voice.llmOutput = error.message || "璇煶澶勭悊澶辫触";
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

function bindEvents() {
  initConnectionInput();
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
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      button.setPointerCapture?.(event.pointerId);
      startManualHold(button.dataset.dir);
    });
    button.addEventListener("pointerup", () => endManualHold(true));
    button.addEventListener("pointercancel", () => endManualHold(true));
    button.addEventListener("lostpointercapture", () => endManualHold(true));
  });
  window.addEventListener("pointerup", () => endManualHold(true));
  window.addEventListener("blur", () => endManualHold(true));
  $("voiceToggleBtn")?.addEventListener("click", () => {
    toggleVoiceListening();
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
  if (button) button.textContent = "閲嶈繛涓?..";
  try {
    await fetch("/api/car/reconnect", { method: "POST" });
  } catch (error) {
    console.warn("car reconnect failed", error);
  } finally {
    if (button) button.textContent = "閲嶈繛灏忚溅";
    await loadSnapshot();
  }
}

async function sendManualHttp(direction) {
  const speed = Number($("speedRange")?.value || 0.16);
  try {
    await postJson("/api/control/manual", { direction, speed });
  } catch (error) {
    console.warn("manual control failed", error);
  }
}

function clearManualHold() {
  if (state.manualHoldTimer) {
    clearInterval(state.manualHoldTimer);
    state.manualHoldTimer = null;
  }
}

function endManualHold(sendStop = true) {
  const activeDirection = state.manualDirection;
  clearManualHold();
  state.manualDirection = null;
  if (sendStop && activeDirection && activeDirection !== "stop") {
    sendManualHttp("stop");
  }
}

function startManualHold(direction) {
  if (!direction) return;
  if (direction === "stop") {
    endManualHold(false);
    sendManualHttp("stop");
    return;
  }
  if (state.manualDirection === direction && state.manualHoldTimer) {
    return;
  }
  endManualHold(false);
  state.manualDirection = direction;
  sendManualHttp(direction);
  state.manualHoldTimer = window.setInterval(() => {
    sendManualHttp(direction);
  }, 180);
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

