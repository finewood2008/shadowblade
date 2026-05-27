/* ============================================================
   影刀短视频工作台 — 流水线编排（6 阶段）
   一次输入 → 6 阶段串行 → 实时状态 + 失败重试
   ============================================================ */

const API = "";
const $ = (id) => document.getElementById(id);

const state = {
  running: false,
  startedAt: 0,
  timer: null,

  // 产物
  script: "",
  script_keywords: [],
  script_subtitle_count: null,
  audio_file: "",
  audio_duration: null,
  subtitle_file: "",
  stock_dir: "",
  stock_files: [],
  stock_seconds: 0,
  video_file: "",
  video_duration: null,
  cover_file: "",

  // 阶段计时
  stageStart: {},
  stageMs: {},
};

// ---------- 健康检查 ----------
async function checkHealth() {
  const pill = $("healthPill");
  const lbl = $("healthLbl");
  try {
    const r = await fetch(API + "/health");
    const j = await r.json();
    if (j.status === "ok" && j.ffmpeg) {
      pill.classList.remove("err");
      pill.classList.add("ok");
      lbl.textContent = "ONLINE · ffmpeg ok";
    } else {
      pill.classList.add("err");
      lbl.textContent = "DEGRADED";
    }
  } catch {
    pill.classList.add("err");
    lbl.textContent = "OFFLINE";
  }
}
checkHealth();
setInterval(checkHealth, 30000);

// ---------- 计时器 ----------
function fmtMs(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
function startTotalTimer() {
  state.startedAt = performance.now();
  state.timer = setInterval(() => {
    $("totalTimer").textContent = fmtMs(performance.now() - state.startedAt);
  }, 200);
}
function stopTotalTimer() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

// ---------- 阶段状态 ----------
function setStage(n, status, opts = {}) {
  const row = document.querySelector(`.pipe-row[data-stage="${n}"]`);
  const st = $(`st-${n}`);
  const meta = $(`meta-${n}`);
  if (!row) return;

  row.classList.remove("pending", "running", "done", "err", "skipped");
  row.classList.add(status);

  // 移除已存在的错误信息和重试按钮
  row.querySelectorAll(".pipe-err-msg, .retry").forEach((el) => el.remove());

  const labels = {
    pending: "待执行",
    running: "运行中",
    done: "已完成",
    err: "失败",
    skipped: "已跳过",
  };
  if (status === "running") {
    st.innerHTML = '<span class="spinner"></span> 运行中…';
    state.stageStart[n] = performance.now();
  } else if (status === "done") {
    const ms = state.stageStart[n]
      ? Math.round(performance.now() - state.stageStart[n])
      : null;
    state.stageMs[n] = ms;
    st.innerHTML = ms != null ? `已完成 · ${fmtMs(ms)}` : "已完成";
  } else if (status === "err") {
    const ms = state.stageStart[n]
      ? Math.round(performance.now() - state.stageStart[n])
      : null;
    st.innerHTML = ms != null ? `失败 · ${fmtMs(ms)}` : "失败";
    if (opts.error) {
      const msg = document.createElement("div");
      msg.className = "pipe-err-msg";
      msg.textContent = opts.error;
      row.appendChild(msg);

      const retry = document.createElement("button");
      retry.className = "retry";
      retry.textContent = "从此步重试";
      retry.onclick = () => retryFrom(n);
      row.querySelector(".status").appendChild(retry);
    }
  } else {
    st.textContent = labels[status] || status;
  }

  if (opts.meta) meta.textContent = opts.meta;
}

function resetPipeline() {
  for (let i = 1; i <= 6; i++) {
    setStage(i, "pending");
    $(`meta-${i}`).textContent = "";
  }
  state.script = "";
  state.script_keywords = [];
  state.script_subtitle_count = null;
  state.audio_file = "";
  state.audio_duration = null;
  state.subtitle_file = "";
  state.stock_dir = "";
  state.stock_files = [];
  state.stock_seconds = 0;
  state.video_file = "";
  state.video_duration = null;
  state.cover_file = "";
  state.stageStart = {};
  state.stageMs = {};
  $("totalTimer").textContent = "00:00";
  renderArtifacts();
  $("btnReset").style.display = "none";
}

// ---------- 产物渲染 ----------
function escapeHtml(s) {
  if (!s) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderArtifacts() {
  const wrap = $("artifacts");
  wrap.innerHTML = "";

  const cards = [];

  // —— 脚本（stage 1 产物） ——
  if (state.script) {
    const kws = (state.script_keywords || [])
      .slice(0, 8)
      .map((k) => `<span class="kw-chip">${escapeHtml(k)}</span>`)
      .join("");
    cards.push(`
      <div class="artifact-card">
        <div class="head-row">
          <span class="name">脚本文案</span>
          <span class="name-en">SCRIPT · TXT</span>
        </div>
        <div class="script-meta">
          <span>${state.script.length} 字</span>
          ${state.script_subtitle_count != null ? `<span>字幕 ${state.script_subtitle_count} 条</span>` : ""}
        </div>
        ${kws ? `<div class="script-meta">${kws}</div>` : ""}
        <div class="script-body">${escapeHtml(state.script)}</div>
      </div>
    `);
  } else {
    cards.push(`
      <div class="artifact-card empty">
        脚本还没生成<br/>
        <span style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;">SCRIPT · WAITING</span>
      </div>
    `);
  }

  if (state.video_file) {
    const url = `/file?path=${encodeURIComponent(state.video_file)}`;
    cards.push(`
      <div class="artifact-card">
        <div class="head-row">
          <span class="name">最终视频</span>
          <span class="name-en">VIDEO · MP4</span>
        </div>
        <video src="${url}" controls preload="metadata"></video>
        <div class="path">${state.video_file}${state.video_duration ? ` · ${state.video_duration.toFixed(1)}s` : ""}</div>
        <div class="actions">
          <a href="${url}" download>下载 · DOWNLOAD</a>
          <a href="${url}" target="_blank">新窗口 · OPEN</a>
        </div>
      </div>
    `);
  } else {
    cards.push(`
      <div class="artifact-card empty">
        视频还没生成<br/>
        <span style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;">VIDEO · WAITING</span>
      </div>
    `);
  }

  if (state.cover_file) {
    const url = `/file?path=${encodeURIComponent(state.cover_file)}`;
    cards.push(`
      <div class="artifact-card">
        <div class="head-row">
          <span class="name">封面图</span>
          <span class="name-en">COVER · JPG</span>
        </div>
        <img src="${url}" alt="cover" />
        <div class="path">${state.cover_file}</div>
        <div class="actions">
          <a href="${url}" download>下载 · DOWNLOAD</a>
          <a href="${url}" target="_blank">新窗口 · OPEN</a>
        </div>
      </div>
    `);
  } else {
    cards.push(`
      <div class="artifact-card empty">
        封面还没生成<br/>
        <span style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;">COVER · WAITING</span>
      </div>
    `);
  }

  wrap.innerHTML = cards.join("");
}

// ---------- 表单收集 ----------
function collectInputs() {
  const dirs = $("f-scenes").value
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  const extraKw = $("f-stock-kw").value
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    topic: $("f-topic").value.trim(),
    length: $("f-length").value || "500",
    language: $("f-lang").value,
    intro: $("f-intro").value.trim(),
    llm: $("f-llm").value || null,
    llmApiKey: $("f-llm-key").value.trim(),
    llmBaseUrl: $("f-llm-base").value.trim(),
    llmModelName: $("f-llm-model").value.trim(),
    tts: $("f-tts").value,
    voice: $("f-voice").value || null,
    rate: $("f-rate").value || "0",
    asr: $("f-asr").value,
    scenes: dirs,
    segMin: parseInt($("f-segmin").value, 10) || 3,
    segMax: parseInt($("f-segmax").value, 10) || 8,
    stockProvider: $("f-stock-prov").value,
    stockOrient: $("f-stock-orient").value,
    stockExtraKw: extraKw,
    stockApiKey: $("f-stock-key").value.trim(),
    enableSubs: $("t-subs").checked,
    enablePad: $("t-pad").checked,
    enableCover: $("t-cover").checked,
    enableTrans: $("t-trans").checked,
  };
}

function validate(inp) {
  if (!inp.topic) return "请填写主题";
  if (inp.scenes.length === 0 && !inp.enablePad) {
    return "请填写至少一个素材目录，或开启「智能补量」从网络补素材";
  }
  return null;
}

// ---------- 调用 ----------
async function postJSON(path, body) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const txt = await r.text();
  let j;
  try { j = JSON.parse(txt); } catch { j = { raw: txt }; }
  if (!r.ok) {
    const err = new Error(typeof j.detail === "string" ? j.detail : `${r.status} ${r.statusText}`);
    err.payload = j;
    throw err;
  }
  return j;
}

function basename(p) {
  if (!p) return "";
  const parts = p.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1];
}

// ---------- 6 个阶段 ----------
async function stage1Script(inp) {
  setStage(1, "running");
  const body = { topic: inp.topic, language: inp.language, length: inp.length };
  if (inp.llm) body.llm_provider = inp.llm;
  if (inp.llmApiKey) body.llm_api_key = inp.llmApiKey;
  if (inp.llmBaseUrl) body.llm_base_url = inp.llmBaseUrl;
  if (inp.llmModelName) body.llm_model_name = inp.llmModelName;
  const j = await postJSON("/generate-script", body);
  state.script = j.content || "";
  state.script_keywords = Array.isArray(j.keywords)
    ? j.keywords
    : (typeof j.keywords === "string"
        ? j.keywords.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
        : []);
  const kwPreview = state.script_keywords.slice(0, 5).join(", ");
  setStage(1, "done", {
    meta: `${state.script.length} 字${kwPreview ? " · kw=" + kwPreview : ""}`,
  });
  // 脚本一出来就在产物区展示，方便用户即刻校对
  renderArtifacts();
}

async function stage2Audio(inp) {
  setStage(2, "running");
  const remoteSet = new Set(["EdgeTTS", "Azure", "Ali", "Tencent"]);
  const body = {
    text: state.script,
    tts_type: remoteSet.has(inp.tts) ? "remote" : "local",
    provider: inp.tts,
    voice: inp.voice,
    rate: inp.rate,
  };
  const j = await postJSON("/generate-audio", body);
  state.audio_file = j.audio_file;
  state.audio_duration = j.duration_seconds;
  setStage(2, "done", {
    meta: `${j.duration_seconds ? j.duration_seconds.toFixed(1) + "s · " : ""}${basename(j.audio_file)}`,
  });
}

async function stage3Subs(inp) {
  if (!inp.enableSubs) {
    setStage(3, "skipped", { meta: "已跳过（用户关闭）" });
    state.script_subtitle_count = null;
    renderArtifacts();
    return;
  }
  setStage(3, "running");
  const body = {
    audio_file: state.audio_file,
    language: inp.language,
    recognition_type: "local",
    recognition_provider: inp.asr,
  };
  const j = await postJSON("/generate-subtitle", body);
  state.subtitle_file = j.subtitle_file;
  state.script_subtitle_count = (j.line_count != null) ? j.line_count : null;
  const lineSuffix = (j.line_count != null) ? ` · ${j.line_count} 条` : "";
  setStage(3, "done", { meta: `${basename(j.subtitle_file)}${lineSuffix}` });
  // 字幕条数回填到脚本卡片
  renderArtifacts();
}

async function stage4Pad(inp) {
  if (!inp.enablePad) {
    setStage(4, "skipped", { meta: "已跳过（用户关闭）" });
    return;
  }

  // 关键词：用户额外补充 + 脚本生成的关键词 + 主题兜底
  const kws = [
    ...inp.stockExtraKw,
    ...state.script_keywords,
    inp.topic,
  ].filter(Boolean);

  // 目标时长：以配音时长为准；没有就回退 60s
  const target = state.audio_duration && state.audio_duration > 0
    ? state.audio_duration
    : 60;

  const body = {
    keywords: kws,
    target_seconds: target,
    existing_dirs: inp.scenes,
    provider: inp.stockProvider,
    orientation: inp.stockOrient,
  };
  if (inp.stockApiKey) body.api_key = inp.stockApiKey;
  const j = await postJSON("/smart-pad", body);

  // 后端 SmartPadResponse: { needed, existing_seconds, target_seconds,
  //                          stock_dir, downloaded, downloaded_seconds, files, skipped_reasons }
  if (j.needed === false) {
    state.stock_dir = "";
    state.stock_files = [];
    state.stock_seconds = 0;
    const have = j.existing_seconds ? j.existing_seconds.toFixed(0) + "s" : "0s";
    const need = j.target_seconds ? j.target_seconds.toFixed(0) + "s" : "?";
    setStage(4, "skipped", { meta: `本地素材已够 · ${have} ≥ ${need}` });
    return;
  }

  state.stock_dir = j.stock_dir || "";
  state.stock_files = j.files || [];
  state.stock_seconds = j.downloaded_seconds || 0;

  const dl = j.downloaded || 0;
  const dur = j.downloaded_seconds ? j.downloaded_seconds.toFixed(0) + "s" : "0s";

  if (dl === 0) {
    // 后端没拒，但一段都没下下来 — 提示用户
    const reasons = (j.skipped_reasons || []).slice(0, 2).join(" · ");
    throw new Error(`补量返回 0 段视频 · ${reasons || "请检查 API Key / 关键词 / 网络"}`);
  }

  setStage(4, "done", {
    meta: `${inp.stockProvider} · 下载 ${dl} 段 · +${dur}`,
  });
}

async function stage5Mix(inp) {
  setStage(5, "running");

  // 用户场景目录 + 智能补量目录
  const allScenes = inp.scenes.map((d) => ({ media_dir: d, text: "" }));
  if (state.stock_dir) {
    allScenes.push({ media_dir: state.stock_dir, text: "" });
  }
  if (allScenes.length === 0) {
    throw new Error("没有任何素材目录可用 · 请检查素材路径或开启智能补量");
  }

  const body = {
    scenes: allScenes,
    audio_file: state.audio_file,
    subtitle_file: state.subtitle_file || null,
    video_config: {
      fps: 30,
      width: 0,
      height: 0,
      segment_min_length: inp.segMin,
      segment_max_length: inp.segMax,
      enable_background_music: false,
      background_music: "",
      background_music_volume: 0.3,
      enable_video_transition_effect: inp.enableTrans,
      video_transition_effect_type: "xfade",
      video_transition_effect_value: "fade",
      video_transition_effect_duration: 1.0,
      intro_text: inp.intro,
    },
    subtitle_config: {
      enable: !!state.subtitle_file,
      font_name: "Microsoft YaHei",
      font_size: 16,
      color: "#FFFFFF",
      border_color: "#000000",
      border_width: 1,
      position: 2,
    },
  };
  const j = await postJSON("/mix-video", body);
  state.video_file = j.video_file;
  state.video_duration = j.duration_seconds;
  setStage(5, "done", {
    meta: `${j.duration_seconds ? j.duration_seconds.toFixed(1) + "s · " : ""}${basename(j.video_file)}`,
  });
  renderArtifacts();
}

async function stage6Cover(inp) {
  if (!inp.enableCover) {
    setStage(6, "skipped", { meta: "已跳过（用户关闭）" });
    return;
  }
  setStage(6, "running");
  const body = {
    video_file: state.video_file,
    timestamp: "00:00:03",
    width: 1080,
    height: 1920,
  };
  const j = await postJSON("/generate-cover", body);
  state.cover_file = j.cover_file;
  setStage(6, "done", { meta: basename(j.cover_file) });
  renderArtifacts();
}

// ---------- 编排 ----------
const stages = [stage1Script, stage2Audio, stage3Subs, stage4Pad, stage5Mix, stage6Cover];

async function runFrom(startIdx) {
  if (state.running) return;
  const inp = collectInputs();
  const err = validate(inp);
  if (err) {
    alert(err);
    return;
  }

  state.running = true;
  $("btnRun").disabled = true;
  $("btnRun").innerHTML = '<span class="spinner"></span> 流水线运行中…';
  $("btnReset").style.display = "none";

  if (startIdx === 0) startTotalTimer();

  let allOk = true;
  for (let i = startIdx; i < stages.length; i++) {
    try {
      await stages[i](inp);
    } catch (e) {
      setStage(i + 1, "err", { error: e.message || String(e) });
      allOk = false;
      break;
    }
  }

  state.running = false;
  stopTotalTimer();
  $("btnRun").disabled = false;
  $("btnRun").innerHTML = allOk ? "再跑一次 →" : "继续运行 →";
  $("btnReset").style.display = "inline-flex";
}

function retryFrom(stageNum) {
  // stageNum 是 1-based
  runFrom(stageNum - 1);
}

// ---------- 绑定 ----------
$("btnRun").addEventListener("click", () => {
  // 如果有失败的阶段，从失败处继续；否则重置后从头跑
  const errRow = document.querySelector(".pipe-row.err");
  if (errRow) {
    const n = parseInt(errRow.dataset.stage, 10);
    runFrom(n - 1);
  } else {
    resetPipeline();
    runFrom(0);
  }
});

$("btnReset").addEventListener("click", resetPipeline);

// ---------- API Key：按 provider 分别保存到 localStorage ----------
const KEY_LS_PREFIX = "shadowblade.stockKey.";
const KEY_HINTS = {
  pexels:  "Pexels Key 格式约 56 位字符 · 在 https://www.pexels.com/api/ 注册免费拿",
  pixabay: "Pixabay Key 格式约 36 位字符 · 在 https://pixabay.com/api/docs/ 注册免费拿",
};

function loadKeyFor(provider) {
  try { return localStorage.getItem(KEY_LS_PREFIX + provider) || ""; }
  catch { return ""; }
}
function saveKeyFor(provider, key) {
  try {
    if (key) localStorage.setItem(KEY_LS_PREFIX + provider, key);
    else     localStorage.removeItem(KEY_LS_PREFIX + provider);
  } catch {}
}
function refreshKeyHint(provider) {
  const hint = $("key-hint");
  const tip = KEY_HINTS[provider];
  if (!hint || !tip) return;
  hint.innerHTML = `${tip}<br/>仅保存在你本地浏览器（localStorage），不会上传任何服务器；留空则回退到 <code class="mono" style="color:var(--accent);font-size:11px;">config.yml → resource.${provider}.api_key</code>`;
}

// 启动时加载当前选中 provider 的已存 key
(function initStockKey() {
  const provSel = $("f-stock-prov");
  const keyInp = $("f-stock-key");
  if (!provSel || !keyInp) return;

  keyInp.value = loadKeyFor(provSel.value);
  refreshKeyHint(provSel.value);

  // 切换来源 → 自动切到对应 key
  provSel.addEventListener("change", () => {
    keyInp.value = loadKeyFor(provSel.value);
    refreshKeyHint(provSel.value);
    // 切换后默认隐藏
    keyInp.type = "password";
    $("btnKeyToggle").textContent = "显示";
  });

  // 失焦自动保存（限定当前所选 provider）
  keyInp.addEventListener("change", () => {
    saveKeyFor(provSel.value, keyInp.value.trim());
  });
  keyInp.addEventListener("blur", () => {
    saveKeyFor(provSel.value, keyInp.value.trim());
  });

  // 显示 / 隐藏
  const toggle = $("btnKeyToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const showing = keyInp.type === "text";
      keyInp.type = showing ? "password" : "text";
      toggle.textContent = showing ? "显示" : "隐藏";
    });
  }
})();

// ---------- LLM 设置：按 provider 分别保存到 localStorage ----------
const LLM_LS_PREFIX = "shadowblade.llm.";
// 每家 provider 的默认 base_url / model_name 占位
const LLM_DEFAULTS = {
  DeepSeek:  { base: "https://api.deepseek.com",          model: "deepseek-chat" },
  Moonshot:  { base: "https://api.moonshot.cn/v1",        model: "moonshot-v1-8k" },
  OpenAI:    { base: "https://api.openai.com/v1",         model: "gpt-4o-mini" },
  Tongyi:    { base: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  Ollama:    { base: "http://127.0.0.1:11434/v1",         model: "qwen2.5:7b" },
};

function llmKey(provider, field) { return `${LLM_LS_PREFIX}${provider}.${field}`; }
function llmLoad(provider, field) {
  try { return localStorage.getItem(llmKey(provider, field)) || ""; }
  catch { return ""; }
}
function llmSave(provider, field, val) {
  try {
    if (val) localStorage.setItem(llmKey(provider, field), val);
    else     localStorage.removeItem(llmKey(provider, field));
  } catch {}
}

(function initLlmSettings() {
  const sel = $("f-llm");
  const keyInp = $("f-llm-key");
  const baseInp = $("f-llm-base");
  const modelInp = $("f-llm-model");
  const toggle = $("btnLlmKeyToggle");
  if (!sel || !keyInp || !baseInp || !modelInp) return;

  function applyProvider(provider) {
    if (!provider) {
      // "默认（config.yml）"——清空显示，让用户感知会走 config
      keyInp.value = "";
      baseInp.value = "";
      modelInp.value = "";
      baseInp.placeholder = "走 config.yml 配置";
      modelInp.placeholder = "走 config.yml 配置";
      return;
    }
    keyInp.value = llmLoad(provider, "api_key");
    baseInp.value = llmLoad(provider, "base_url");
    modelInp.value = llmLoad(provider, "model_name");
    const def = LLM_DEFAULTS[provider] || {};
    baseInp.placeholder = def.base ? `留空则用 ${def.base}` : "可选";
    modelInp.placeholder = def.model ? `留空则用 ${def.model}` : "可选";
    // 切换后默认隐藏
    keyInp.type = "password";
    if (toggle) toggle.textContent = "显示";
  }

  applyProvider(sel.value);

  sel.addEventListener("change", () => applyProvider(sel.value));

  function bindBlurSave(inp, field) {
    const save = () => {
      const provider = sel.value;
      if (!provider) return; // 没选 provider 不存
      llmSave(provider, field, inp.value.trim());
    };
    inp.addEventListener("change", save);
    inp.addEventListener("blur", save);
  }
  bindBlurSave(keyInp,   "api_key");
  bindBlurSave(baseInp,  "base_url");
  bindBlurSave(modelInp, "model_name");

  if (toggle) {
    toggle.addEventListener("click", () => {
      const showing = keyInp.type === "text";
      keyInp.type = showing ? "password" : "text";
      toggle.textContent = showing ? "显示" : "隐藏";
    });
  }
})();

// ============================================================
//   AI 智能向导：6 轮以内对话收集字段并自动填表
// ============================================================
(function initWizard() {
  const card = $("wizardCard");
  const body = $("wizardBody");
  const toggleBtn = $("btnWizardToggle");
  const stream = $("chatStream");
  const input = $("chatInput");
  const sendBtn = $("btnChatSend");
  const startBtn = $("btnWizardStart");
  const resetBtn = $("btnWizardReset");
  const progressEl = $("wizardProgress");
  const appliedEl = $("wizardApplied");
  if (!card || !body || !stream) return;

  // 对话状态
  const wstate = {
    open: false,
    messages: [], // [{role, content}]
    busy: false,
    done: false,
  };

  // ---------- UI helpers ----------
  function renderStream() {
    stream.innerHTML = "";
    for (const m of wstate.messages) {
      // 隐藏伪开场消息
      if (m.role === "user" && m.content === "__start__") continue;
      const div = document.createElement("div");
      div.className = `chat-msg ${m.role}`;
      div.textContent = m.content;
      stream.appendChild(div);
    }
    if (wstate.busy) {
      const loading = document.createElement("div");
      loading.className = "chat-msg assistant loading";
      loading.textContent = "AI 正在思考";
      stream.appendChild(loading);
    }
    stream.scrollTop = stream.scrollHeight;
  }

  function updateProgress() {
    const rounds = wstate.messages.filter(
      (m) => m.role === "user" && m.content !== "__start__"
    ).length;
    progressEl.textContent = `${Math.min(rounds, 6)} / 6`;
  }

  function setBusy(b) {
    wstate.busy = b;
    input.disabled = b || wstate.done;
    sendBtn.disabled = b || wstate.done;
    startBtn.disabled = b || wstate.done || wstate.messages.length > 0;
    renderStream();
  }

  function setDone() {
    wstate.done = true;
    input.disabled = true;
    sendBtn.disabled = true;
    appliedEl.style.display = "inline";
  }

  // ---------- 折叠 ----------
  function openCard() {
    wstate.open = true;
    body.style.display = "block";
    toggleBtn.textContent = "收起 ▴";
  }
  function closeCard() {
    wstate.open = false;
    body.style.display = "none";
    toggleBtn.textContent = "展开 ▾";
  }
  toggleBtn.addEventListener("click", () => {
    if (wstate.open) closeCard();
    else openCard();
  });

  // ---------- 调 /wizard/chat ----------
  async function callWizard() {
    // 复用现有 LLM 设置（从主表单读取，前端覆盖后端 config）
    const llm = $("f-llm").value || null;
    const llmApiKey = $("f-llm-key").value.trim();
    const llmBaseUrl = $("f-llm-base").value.trim();
    const llmModelName = $("f-llm-model").value.trim();

    const reqBody = {
      messages: wstate.messages,
      language: $("f-lang").value || "zh-CN",
    };
    if (llm) reqBody.llm_provider = llm;
    if (llmApiKey) reqBody.llm_api_key = llmApiKey;
    if (llmBaseUrl) reqBody.llm_base_url = llmBaseUrl;
    if (llmModelName) reqBody.llm_model_name = llmModelName;

    setBusy(true);
    try {
      const j = await postJSON("/wizard/chat", reqBody);
      wstate.messages.push({ role: "assistant", content: j.reply || "" });
      updateProgress();
      if (j.done && j.fields) {
        applyFields(j.fields);
        setBusy(false);
        setDone();
      } else {
        setBusy(false);
      }
    } catch (e) {
      wstate.messages.push({
        role: "assistant",
        content: `（出错了：${e.message || e}）你可以「重置对话」从头再来，或者直接在下面手动填表单。`,
      });
      setBusy(false);
    }
  }

  // ---------- 把 LLM 返回的字段写进主表单 ----------
  function applyFields(fields) {
    if (!fields) return;
    if (fields.topic) $("f-topic").value = fields.topic;
    if (fields.intro) $("f-intro").value = fields.intro;
    if (fields.length) $("f-length").value = String(fields.length);
    if (fields.language) $("f-lang").value = fields.language;
    // style_hint 暂时不映射到独立字段（V0 简化）
    // 不覆盖用户已填的素材目录 / 引擎选型，那是用户自己的事
  }

  // ---------- 开始 ----------
  startBtn.addEventListener("click", () => {
    wstate.messages = [{ role: "user", content: "__start__" }];
    wstate.done = false;
    appliedEl.style.display = "none";
    resetBtn.style.display = "inline-flex";
    startBtn.textContent = "已开始";
    startBtn.disabled = true;
    updateProgress();
    callWizard();
  });

  // ---------- 重置 ----------
  resetBtn.addEventListener("click", () => {
    wstate.messages = [];
    wstate.done = false;
    wstate.busy = false;
    appliedEl.style.display = "none";
    startBtn.textContent = "开始向导 →";
    startBtn.disabled = false;
    input.disabled = true;
    sendBtn.disabled = true;
    input.value = "";
    resetBtn.style.display = "none";
    updateProgress();
    renderStream();
  });

  // ---------- 发送 ----------
  function send() {
    const text = input.value.trim();
    if (!text || wstate.busy || wstate.done) return;
    wstate.messages.push({ role: "user", content: text });
    input.value = "";
    updateProgress();
    callWizard();
  }
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  updateProgress();
})();

// ============================================================
//   场景目录：添加 / 最近用过下拉 / 清空
// ============================================================
(function initSceneTools() {
  const ta = $("f-scenes");
  const addBtn = $("btnSceneAdd");
  const clearBtn = $("btnSceneClear");
  const recentSel = $("f-scene-recent");
  if (!ta || !addBtn) return;

  const LS_KEY = "shadowblade.recentScenes";
  const MAX_RECENT = 8;

  function loadRecent() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.filter((s) => typeof s === "string") : [];
    } catch {
      return [];
    }
  }

  function saveRecent(list) {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
    } catch {}
  }

  function pushRecent(path) {
    if (!path) return;
    const list = loadRecent();
    const idx = list.indexOf(path);
    if (idx >= 0) list.splice(idx, 1);
    list.unshift(path);
    saveRecent(list);
    refreshDropdown();
  }

  function refreshDropdown() {
    if (!recentSel) return;
    const list = loadRecent();
    recentSel.innerHTML = '<option value="">最近用过…</option>';
    for (const p of list) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p.length > 50 ? "…" + p.slice(-49) : p;
      recentSel.appendChild(opt);
    }
  }

  function appendPath(path) {
    if (!path) return;
    const trimmed = path.trim();
    if (!trimmed) return;
    const lines = ta.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (lines.includes(trimmed)) return; // 已经在里面就不重复加
    lines.push(trimmed);
    ta.value = lines.join("\n");
    pushRecent(trimmed);
  }

  addBtn.addEventListener("click", () => {
    const p = window.prompt(
      "粘贴一个绝对路径（每次一个）：\n例：D:\\GITHUB\\shadowblade\\assets\\beauty\\scene-1"
    );
    if (p) appendPath(p);
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (!ta.value.trim()) return;
      if (window.confirm("确认清空 textarea 里所有目录？最近用过的记录不会删。")) {
        ta.value = "";
      }
    });
  }

  if (recentSel) {
    recentSel.addEventListener("change", () => {
      const v = recentSel.value;
      if (v) {
        appendPath(v);
        recentSel.value = "";
      }
    });
  }

  // textarea 失焦时把里面的所有路径也记一遍（手动粘贴的也能进最近）
  ta.addEventListener("blur", () => {
    const lines = ta.value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    // 反向 push，让 textarea 里第一行排在最近用过的最前
    for (let i = lines.length - 1; i >= 0; i--) {
      pushRecent(lines[i]);
    }
  });

  refreshDropdown();
})();
