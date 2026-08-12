/* FunASR PWA — speech recognition frontend. */
"use strict";

const $ = (id) => document.getElementById(id);

const els = {
  serverBadge: $("serverBadge"),
  installBtn: $("installBtn"),
  dropZone: $("dropZone"),
  fileInput: $("fileInput"),
  recordBtn: $("recordBtn"),
  recordStatus: $("recordStatus"),
  audioMeta: $("audioMeta"),
  modelSelect: $("modelSelect"),
  langSelect: $("langSelect"),
  transcribeBtn: $("transcribeBtn"),
  resultCard: $("resultCard"),
  metrics: $("metrics"),
  transcript: $("transcript"),
  copyBtn: $("copyBtn"),
  apiEndpoint: $("apiEndpoint"),
  toast: $("toast"),
};

const state = {
  audioFile: null,
  recorder: null,
  chunks: [],
  recording: false,
  apiMode: "openai", // "openai" | "legacy"
  apiEndpoint: "/v1/audio/transcriptions",
  serverReady: false,
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function showToast(message, type = "") {
  els.toast.textContent = message;
  els.toast.className = `toast ${type}`;
  els.toast.classList.remove("hidden");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => els.toast.classList.add("hidden"), 4000);
}

function setServerBadge(text, stateName) {
  els.serverBadge.textContent = text;
  els.serverBadge.dataset.state = stateName;
}

function updateButtons() {
  els.transcribeBtn.disabled = !(state.audioFile && state.serverReady);
  els.recordBtn.disabled = !state.serverReady;
}

/* ------------------------------------------------------------------ */
/* Service worker + PWA install prompt                                 */
/* ------------------------------------------------------------------ */

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((err) => {
      console.warn("Service worker registration failed:", err);
    });
  });
}

let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredInstall = e;
  els.installBtn.hidden = false;
  els.installBtn.classList.remove("hidden");
});

els.installBtn.addEventListener("click", async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  els.installBtn.hidden = true;
});

window.addEventListener("appinstalled", () => {
  els.installBtn.hidden = true;
  showToast("应用已安装到设备", "success");
});

/* ------------------------------------------------------------------ */
/* Server probing & API endpoint detection                             */
/* ------------------------------------------------------------------ */

async function probeServer() {
  // 1) Health check
  try {
    const res = await fetch("/health", { method: "GET", cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const models = Array.isArray(data.models_loaded) ? data.models_loaded : [];
    setServerBadge(models.length ? `在线 · ${models.join(" / ")}` : "在线", "ok");
    state.serverReady = true;
  } catch (err) {
    setServerBadge("服务离线", "error");
    showToast("无法连接 FunASR 服务，请稍后重试", "error");
    updateButtons();
    return;
  }

  // 2) Detect API flavour: OpenAI-compatible (/v1/models) vs legacy (/recognize)
  try {
    const res = await fetch("/v1/models", { method: "GET", cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      const ids = (data.data || []).map((m) => m.id);
      if (ids.length) {
        state.apiMode = "openai";
        state.apiEndpoint = "/v1/audio/transcriptions";
        els.apiEndpoint.textContent = state.apiEndpoint;
        populateModels(ids);
      }
    }
  } catch (err) {
    /* fall through to legacy */
  }

  if (state.apiMode !== "openai") {
    state.apiMode = "legacy";
    state.apiEndpoint = "/recognize";
    els.apiEndpoint.textContent = state.apiEndpoint;
  }

  updateButtons();
}

function populateModels(ids) {
  const select = els.modelSelect;
  if (!Array.isArray(ids) || !ids.length) return;
  // Rebuild the dropdown from the model list the server actually exposes.
  select.innerHTML = "";
  for (const id of ids) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = /paraformer/i.test(id)
      ? `${id}（中文标点）`
      : /sensevoice/i.test(id)
        ? `${id}（多语言）`
        : id;
    select.appendChild(opt);
  }
  const pref = [...select.options].find((o) => /paraformer/i.test(o.value));
  if (pref) select.value = pref.value;
}

/* ------------------------------------------------------------------ */
/* Audio file handling                                                 */
/* ------------------------------------------------------------------ */

function setAudioFile(file) {
  state.audioFile = file;
  if (file) {
    const size = (file.size / 1024 / 1024).toFixed(2);
    els.audioMeta.innerHTML =
      `已选择：<strong>${escapeHtml(file.name)}</strong>（${size} MB）` +
      `<button class="remove-file" type="button">移除</button>`;
    els.audioMeta.classList.remove("hidden");
    els.recordStatus.textContent = "已选择音频，点击“转写文字”";
  } else {
    els.audioMeta.classList.add("hidden");
    els.recordStatus.textContent = state.recording ? "正在录音…" : "需要上传音频";
  }
  updateButtons();
}

els.audioMeta.addEventListener("click", (e) => {
  if (e.target.classList.contains("remove-file")) setAudioFile(null);
});

els.dropZone.addEventListener("click", () => els.fileInput.click());
els.dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.fileInput.click(); }
});

els.fileInput.addEventListener("change", (e) => {
  if (e.target.files && e.target.files[0]) setAudioFile(e.target.files[0]);
});

["dragenter", "dragover"].forEach((evt) =>
  els.dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    els.dropZone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((evt) =>
  els.dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    els.dropZone.classList.remove("drag");
  })
);
/* ------------------------------------------------------------------ */
/* Microphone recording                                                */
/* ------------------------------------------------------------------ */

async function toggleRecording() {
  if (state.recording) {
    stopRecording();
    return;
  }

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showToast("当前浏览器不支持录音（需 HTTPS 环境）", "error");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.chunks = [];
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "";
    state.recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    state.recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) state.chunks.push(e.data);
    };
    state.recorder.onstop = () => {
      const blob = new Blob(state.chunks, {
        type: state.recorder.mimeType || "audio/webm",
      });
      stream.getTracks().forEach((t) => t.stop());
      setAudioFile(new File([blob], `recording-${Date.now()}.webm`, { type: blob.type }));
    };

    state.recording = true;
    state.recorder.start();
    els.recordBtn.classList.add("recording");
    els.recordBtn.querySelector(".btn-label").textContent = "停止录音";
    els.recordStatus.textContent = "正在录音… 点击“停止录音”结束";
  } catch (err) {
    showToast("无法访问麦克风：" + err.message, "error");
  }
}

function stopRecording() {
  if (!state.recorder || state.recorder.state === "inactive") return;
  state.recorder.stop();
  state.recording = false;
  els.recordBtn.classList.remove("recording");
  els.recordBtn.querySelector(".btn-label").textContent = "开始录音";
  els.recordStatus.textContent = "录音完成，点击“转写文字”";
}

els.recordBtn.addEventListener("click", toggleRecording);

/* ------------------------------------------------------------------ */
/* Transcription                                                       */
/* ------------------------------------------------------------------ */

function extractText(payload) {
  if (typeof payload === "string") return payload;
  if (Array.isArray(payload)) {
    return payload.map((item) => (item && item.text) || "").join("\n");
  }
  if (payload && typeof payload === "object") {
    if (typeof payload.text === "string") return payload.text;
    if (Array.isArray(payload.results)) {
      return payload.results.map((r) => r.text || "").join("\n");
    }
    if (payload.result && typeof payload.result.text === "string") {
      return payload.result.text;
    }
  }
  return "";
}

async function transcribe() {
  if (!state.audioFile || !state.serverReady) return;

  const btn = els.transcribeBtn;
  btn.classList.add("loading");
  btn.disabled = true;
  btn.textContent = "识别中…";

  const model = els.modelSelect.value;
  const language = els.langSelect.value;

  // Try the detected endpoint first, then fall back to the other API flavour.
  const candidates = [
    state.apiEndpoint,
    state.apiEndpoint === "/v1/audio/transcriptions"
      ? "/recognize"
      : "/v1/audio/transcriptions",
  ];

  const t0 = performance.now();
  let lastError = null;
  try {
    for (const ep of candidates) {
      const form = new FormData();
      form.append("file", state.audioFile, state.audioFile.name);
      form.append("model", model);
      if (ep === "/v1/audio/transcriptions") {
        if (language && language !== "auto") form.append("language", language);
      } else {
        form.append("device", "cpu");
        if (language && language !== "auto") form.append("language", language);
      }

      const res = await fetch(ep, { method: "POST", body: form });

      // 404/405 on this endpoint => try the other one.
      if (res.status === 404 || res.status === 405) {
        lastError = new Error(`接口 ${ep} 不可用（${res.status}）`);
        continue;
      }

      if (!res.ok) {
        let detail = "";
        try {
          const errJson = await res.json();
          detail = errJson.detail || errJson.message || JSON.stringify(errJson);
        } catch (err) {
          detail = await res.text();
        }
        throw new Error(`服务返回错误（${res.status}）：${detail}`);
      }

      const payload = await res.json();
      const text = extractText(payload).trim();
      const elapsed = ((performance.now() - t0) / 1000).toFixed(2);

      // Remember the working endpoint for next time.
      state.apiEndpoint = ep;
      els.apiEndpoint.textContent = ep;

      els.metrics.textContent = `耗时 ${elapsed}s · 模型 ${model} · 设备 CPU`;
      els.transcript.textContent = text || "（未识别到文字，请尝试更清晰的音频）";
      els.resultCard.classList.remove("hidden");
      els.resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }

    showToast(lastError ? lastError.message : "转写失败", "error");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.classList.remove("loading");
    btn.textContent = "转写文字";
    updateButtons();
  }
}

els.transcribeBtn.addEventListener("click", transcribe);

els.copyBtn.addEventListener("click", async () => {
  const text = els.transcript.textContent;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast("已复制到剪贴板", "success");
  } catch (err) {
    showToast("复制失败，请手动选择复制", "error");
  }
});

/* ------------------------------------------------------------------ */
/* Init                                                                */
/* ------------------------------------------------------------------ */

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

probeServer();