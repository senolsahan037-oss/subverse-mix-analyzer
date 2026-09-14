const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const form = $("#analysis-form");
const fileInput = $("#audio-file");
const referenceInput = $("#reference-file");
const referenceStage = $("#reference-stage");
const analyzeButton = $("#analyze-button");
const uploadZone = $("#upload-zone");
const uploadSelected = $("#upload-selected");
const results = $("#results");
const loadingPanel = $("#loading-panel");
const errorBox = $("#form-error");

let loadingTimer = null;
let loadingStartedAt = 0;
let lastResult = null;
let waveformResizeObserver = null;
let publicConfig = null;
let firebaseAuth = null;
let firebaseAuthApi = null;
let signedInUser = null;
let pendingToolRoomToken = null;

const TRUSTED_TOOL_ROOM_ORIGINS = ["https://subverselab.com", "https://www.subverselab.com"];

// When launched inside SubverseLab's Tool Room iframe, the parent hands this
// window a short-lived Firebase custom token for the user already signed in
// on subverselab.com — this tool runs on its own origin (auth_required means
// every action needs a session), so without this it has no way to know that
// and always shows its own sign-in prompt. Only accepted from the site's own
// origin. May arrive before firebaseAuth exists yet (initializeAccess() is
// still awaiting /api/config), so a message that arrives early is queued and
// consumed once firebaseAuth is ready.
function applyToolRoomToken(token) {
  if (firebaseAuth && firebaseAuthApi) {
    firebaseAuthApi.signInWithCustomToken(firebaseAuth, token).catch((error) => {
      console.error("Tool Room sign-in handoff failed", error);
    });
  } else {
    pendingToolRoomToken = token;
  }
}

window.addEventListener("message", (event) => {
  if (!TRUSTED_TOOL_ROOM_ORIGINS.includes(event.origin)) return;
  if (event.data?.type !== "subverselab:auth-token" || !event.data.token) return;
  applyToolRoomToken(event.data.token);
});

const metricNames = {
  loudness_relative_spectrum: "Loudness-relative Spectrum",
  integrated_lufs: "Integrated Loudness",
  sample_peak_dbfs: "Sample Peak",
  crest_factor_db: "Crest Factor",
  channel_balance_db: "L/R RMS Difference",
};

const policyNames = {
  descriptive_mix: "Mix · Descriptive",
  descriptive_master: "Master · Descriptive",
  mix_to_mix: "Mix → Mix Reference",
  mix_to_master: "Mix → Master Reference",
  master_to_mix: "Master → Mix Reference",
  master_to_master: "Master → Master Reference",
  mix_to_genre: "Mix → Genre Profile",
  master_to_genre: "Master → Genre Profile",
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatNumber(value, digits = 1) {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : Number(value).toFixed(digits);
}

function formatTime(seconds, includeMilliseconds = false) {
  if (!Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining
    .toFixed(includeMilliseconds ? 3 : 0)
    .padStart(includeMilliseconds ? 6 : 2, "0")}`;
}

function setError(message = "") {
  if (message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
    try { errorBox.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
  } else {
    errorBox.textContent = "";
    errorBox.hidden = true;
  }
}

async function authorizedFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  try {
    if (signedInUser && typeof signedInUser.getIdToken === "function") {
      const token = await signedInUser.getIdToken();
      if (token && typeof token === "string") {
        headers.set("Authorization", `Bearer ${token}`);
      }
    }
  } catch (e) {
    console.warn("Auth token skip:", e);
  }
  return fetch(url, { ...options, headers });
}

function setAuthError(message = "") {
  const node = $("#auth-error");
  if (!node) return;
  node.textContent = message;
  node.hidden = !message;
}

function renderAccessState() {
  const workspace = $("#analysis-workspace");
  const wall = $("#members-wall");
  const signOutBtn = $("#sign-out-button");

  // Mix Check hands over a file, so the gate is at the door (Rules/00, "Where
  // the gate sits"). This function used to reveal the workspace unconditionally
  // — auth_required was read from /api/config and then never acted on, so the
  // console opened for anyone and the membership check existed only on the
  // server. Showing a console that cannot analyse is the ten-minutes-then-a-
  // locked-button problem in a different shape.
  const needsSession = Boolean(publicConfig?.auth_required) && !signedInUser;
  if (workspace) workspace.hidden = needsSession;
  if (wall) wall.hidden = !needsSession;
  if (signOutBtn) signOutBtn.hidden = true;
}

// The wall's only button. The tool has no login: it asks the website to open
// one, and subverselab.com decides. Framed by the Tool Room this never shows.
function requestWebsiteSignIn() {
  const parent = TRUSTED_TOOL_ROOM_ORIGINS.find((origin) => {
    try { return new URL(document.referrer).origin === origin; } catch { return false; }
  });
  const embedded = (() => { try { return window.self !== window.top; } catch { return true; } })();
  if (embedded && parent) {
    try {
      window.parent.postMessage({ type: "subverselab:request-sign-in", tool: "subverse-mix-check" }, parent);
      return;
    } catch { /* fall through to navigation */ }
  }
  window.open("https://subverselab.com/tools/subverse-mix-check", "_top");
}

async function initializeAccess() {
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error("The service configuration is unavailable.");
  publicConfig = await response.json();
  if (!publicConfig.auth_required) {
    renderAccessState();
    return;
  }
  const [{ initializeApp }, authApi] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/11.4.0/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/11.4.0/firebase-auth.js"),
  ]);
  firebaseAuthApi = authApi;
  firebaseAuth = authApi.getAuth(initializeApp(publicConfig.firebase));
  authApi.useDeviceLanguage(firebaseAuth);
  authApi.onAuthStateChanged(firebaseAuth, (user) => {
    signedInUser = user;
    renderAccessState();
  });
  if (pendingToolRoomToken) {
    const token = pendingToolRoomToken;
    pendingToolRoomToken = null;
    applyToolRoomToken(token);
  }
}

// signInWithGoogle was removed. It was already dead — nothing in the page
// called it and no button existed for it — but a tool that still carries a way
// to sign in is a tool that grows a button for it again on the next edit.
// subverselab.com is the only place anyone signs in; identity reaches this
// origin through the Tool Room handoff above and by no other route.
// See Rules/03_VALIDATION.md, "Session handoff to a member remote tool".

function safeUploadFilename(filename) {
  if (!filename) return "track.wav";
  const ext = filename.split(".").pop()?.toLowerCase() || "wav";
  const safeExt = ["wav", "mp3"].includes(ext) ? ext : "wav";
  const base = filename.substring(0, filename.lastIndexOf(".")).replace(/[^a-zA-Z0-9_-]/g, "_");
  return `${base || "track"}.${safeExt}`;
}

async function createCloudUpload(file) {
  const safeName = safeUploadFilename(file.name);
  const sessionResponse = await authorizedFetch("/api/uploads/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: safeName,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
    }),
  });
  let session = null;
  try {
    session = await sessionResponse.json();
  } catch (e) {
    throw new Error("Temporary upload session response error.");
  }
  if (!sessionResponse.ok || !session?.upload_url) {
    throw new Error(session?.detail || "The temporary upload could not be started.");
  }
  const uploadResponse = await fetch(session.upload_url, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!uploadResponse.ok) throw new Error("The audio upload could not be completed.");
  return session.object_name;
}

function validateAudioFile(file, clearError = true) {
  if (!file) return true;
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!["wav", "mp3"].includes(extension)) {
    setError("Supported audio formats: WAV and MP3 only.");
    return false;
  }
  if (file.size > 100 * 1024 * 1024) {
    setError("The selected file exceeds the 100 MB upload limit.");
    return false;
  }
  if (clearError) setError();
  return true;
}

function renderSelectedFile(file) {
  if (!file) {
    uploadZone.hidden = false;
    uploadSelected.hidden = true;
    analyzeButton.disabled = true;
    return;
  }
  if (!validateAudioFile(file)) {
    fileInput.value = "";
    return;
  }
  $("#file-name").textContent = file.name;
  $("#file-name").title = file.name;
  $("#file-size").textContent = `${formatBytes(file.size)} · Ready for analysis`;
  $("#file-type").textContent = file.name.split(".").pop().toUpperCase();
  uploadZone.hidden = true;
  uploadSelected.hidden = false;
  analyzeButton.disabled = false;
}

function renderReference(file) {
  if (!file) {
    $("#reference-name").textContent = "Choose a Reference Track";
    $("#reference-help").textContent = "WAV or MP3";
    referenceStage.disabled = true;
    return;
  }
  if (!validateAudioFile(file, false)) {
    referenceInput.value = "";
    return;
  }
  $("#reference-name").textContent = file.name;
  $("#reference-name").title = file.name;
  $("#reference-help").textContent = `${formatBytes(file.size)} · Select its stage`;
  referenceStage.disabled = false;
}

function updateModePromise() {
  const stage = $('input[name="analysis_stage"]:checked').value;
  const genre = $("#genre-select").value;
  const hasReference = Boolean(referenceInput.files[0]);
  const closestProfile = $("#use-closest-profile");
  const closestProfileApplies = !genre && !hasReference;
  closestProfile.disabled = !closestProfileApplies;
  $(".closest-profile-option").classList.toggle(
    "is-disabled",
    !closestProfileApplies,
  );
  $("#mode-promise-title").textContent =
    closestProfileApplies && closestProfile.checked
      ? `Closest-profile ${stage === "mix" ? "Mix" : "Master"} guidance`
      : `Direct ${stage === "mix" ? "Mix" : "Master"} measurement`;

  let copy =
    stage === "mix"
      ? "Waveform, spectrum, Crest Factor, L/R RMS Difference, and Mono Fold-down."
      : "Waveform, Integrated Loudness, Sample Peak, dynamics, spectrum, and Mono Fold-down.";
  if (genre) {
    copy +=
      stage === "mix"
        ? " Genre Profile comparison remains spectral only."
        : " Measurements are compared with the released-master distribution.";
  }
  if (closestProfileApplies && closestProfile.checked) {
    copy +=
      " The technically nearest stored profile will be shown and used as optional guidance.";
  }
  if (hasReference) {
    copy = "The uploaded Reference Track is the primary comparison basis.";
  }
  $("#mode-promise").textContent = copy;
}

async function loadGenres() {
  const select = $("#genre-select");
  try {
    const response = await fetch("/mix/genres");
    if (!response.ok) throw new Error();
    const payload = await response.json();
    payload.genres.forEach((genre) => {
      const option = document.createElement("option");
      option.value = genre.id;
      option.textContent = genre.name;
      select.append(option);
    });
  } catch {
    const option = document.createElement("option");
    option.disabled = true;
    option.textContent = "Genre Profiles are currently unavailable";
    select.append(option);
  }
}

function metricContext(result, metric) {
  const numeric = result.comparison?.numeric_metrics?.find(
    (item) => item.metric === metric,
  );
  if (!numeric) return "Direct measurement";
  if (numeric.target_p25 !== null && numeric.target_p25 !== undefined) {
    return `Profile IQR ${formatNumber(numeric.target_p25)} to ${formatNumber(
      numeric.target_p75,
    )}`;
  }
  const sign = numeric.delta > 0 ? "+" : "";
  return `Reference delta ${sign}${formatNumber(numeric.delta)}`;
}

function addMeasurementRow(label, value, unit, context) {
  const row = document.createElement("tr");
  const labelCell = document.createElement("th");
  const valueCell = document.createElement("td");
  const contextCell = document.createElement("td");
  labelCell.scope = "row";
  labelCell.textContent = label;
  valueCell.className = "measurement-value";
  valueCell.textContent = value;
  if (unit) {
    const unitNode = document.createElement("span");
    unitNode.textContent = unit;
    valueCell.append(unitNode);
  }
  contextCell.textContent = context;
  row.append(labelCell, valueCell, contextCell);
  $("#measurement-rows").append(row);
}

function renderMeasurements(result) {
  const analysis = result.mix.analysis;
  $("#measurement-rows").replaceChildren();
  $("#measurement-status").textContent =
    analysis.analysis_status === "ok"
      ? "Decoded signal · Direct values"
      : analysis.analysis_status.replace("_", " ");

  addMeasurementRow(
    "Integrated Loudness",
    formatNumber(analysis.integrated_lufs),
    "LUFS",
    metricContext(result, "integrated_lufs"),
  );
  addMeasurementRow(
    "Sample Peak",
    formatNumber(analysis.sample_peak_dbfs),
    "dBFS",
    metricContext(result, "sample_peak_dbfs"),
  );
  addMeasurementRow(
    "RMS",
    formatNumber(analysis.rms_dbfs),
    "dBFS",
    "Full-file RMS",
  );
  addMeasurementRow(
    "Crest Factor",
    formatNumber(analysis.crest_factor_db),
    "dB",
    metricContext(result, "crest_factor_db"),
  );
  addMeasurementRow(
    "L/R RMS Difference",
    formatNumber(result.mix.channel_balance_db),
    "dB",
    "Long-term channel energy difference",
  );
}

function drawWaveform(canvas, channel, durationSeconds) {
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);

  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const width = bounds.width;
  const height = bounds.height;
  const middle = height / 2;
  const minimums = channel.minimums;
  const maximums = channel.maximums;

  context.clearRect(0, 0, width, height);
  context.strokeStyle = "rgba(255,255,255,.08)";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(0, Math.round(middle) + 0.5);
  context.lineTo(width, Math.round(middle) + 0.5);
  context.stroke();

  // Brand-aligned waveform colors; channel distinction stays legible without cyan/purple drift.
  context.strokeStyle = channel.index === 0 ? "#D9B978" : "#6BD6C9";
  context.lineWidth = Math.max(1, width / Math.max(minimums.length, 1));
  context.beginPath();
  for (let index = 0; index < minimums.length; index += 1) {
    const x = (index / Math.max(minimums.length - 1, 1)) * width;
    const top = middle - maximums[index] * middle;
    const bottom = middle - minimums[index] * middle;
    context.moveTo(x, top);
    context.lineTo(x, bottom);
  }
  context.stroke();

  canvas._waveform = { channel, durationSeconds };
}

function updateWaveformReadout(canvas, clientX, explicitIndex = null) {
  const data = canvas._waveform;
  if (!data) return;
  const bounds = canvas.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
  const index =
    explicitIndex === null
      ? Math.round(ratio * (data.channel.minimums.length - 1))
      : Math.max(0, Math.min(data.channel.minimums.length - 1, explicitIndex));
  canvas.dataset.cursorIndex = String(index);
  const time =
    (index / Math.max(data.channel.minimums.length - 1, 1)) *
    data.durationSeconds;
  $("#waveform-readout").textContent = `${data.channel.label} · ${formatTime(
    time,
    true,
  )} · min ${formatNumber(data.channel.minimums[index], 4)} · max ${formatNumber(
    data.channel.maximums[index],
    4,
  )}`;
}

function renderWaveform(result) {
  const waveform = result.mix.waveform;
  const duration = result.mix.analysis.duration_seconds;
  const container = $("#waveform-channels");
  container.replaceChildren();
  waveformResizeObserver?.disconnect();
  waveformResizeObserver = new ResizeObserver(() => {
    $$(".waveform-canvas").forEach((canvas) =>
      drawWaveform(canvas, canvas._channel, duration),
    );
  });

  waveform.channels.forEach((channel) => {
    const row = document.createElement("div");
    row.className = "waveform-channel";
    const label = document.createElement("span");
    label.className = "waveform-label";
    label.textContent = channel.label;
    const canvas = document.createElement("canvas");
    canvas.className = "waveform-canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      `${channel.label} raw waveform envelope. Use Left and Right Arrow keys to inspect.`,
    );
    canvas._channel = channel;
    canvas.addEventListener("pointermove", (event) =>
      updateWaveformReadout(canvas, event.clientX),
    );
    canvas.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const current = Number(canvas.dataset.cursorIndex || 0);
      updateWaveformReadout(canvas, 0, current + direction);
    });
    row.append(label, canvas);
    container.append(row);
    waveformResizeObserver.observe(canvas);
    requestAnimationFrame(() => drawWaveform(canvas, channel, duration));
  });

  $("#waveform-axis").replaceChildren(
    ...[0, duration / 2, duration].map((value) => {
      const tick = document.createElement("span");
      tick.textContent = formatTime(value);
      return tick;
    }),
  );
}

function renderSpectrum(result) {
  const chart = $("#spectrum-chart");
  const empty = $("#empty-chart");
  const deltas = (result.comparison?.spectral_deltas || []).filter(
    (band) => band.comparison_status !== "inactive",
  );
  const rawBands = (result.mix.spectral_bands || []).filter(
    (band) => band.level_dbfs !== null,
  );
  const isComparison = deltas.length > 0;
  const bands = isComparison ? deltas : rawBands;
  chart.replaceChildren();
  chart.classList.toggle("is-comparison", isComparison);
  chart.hidden = bands.length === 0;
  $(".chart-axis").hidden = bands.length === 0;
  empty.hidden = bands.length !== 0;
  $("#spectrum-title").textContent = isComparison
    ? "Loudness-relative Spectrum Delta"
    : "One-third-octave Spectrum";
  $("#chart-legend").lastChild.textContent = isComparison
    ? " Target delta · dB"
    : " Band level · dBFS";

  bands.forEach((band) => {
    const wrapper = document.createElement("button");
    const bar = document.createElement("i");
    wrapper.type = "button";
    if (isComparison) {
      const value = Math.max(-12, Math.min(12, band.delta_db));
      wrapper.className = `spectrum-bar ${
        value >= 0 ? "is-positive" : "is-negative"
      }`;
      wrapper.dataset.label = `${band.center_hz} Hz · ${
        value > 0 ? "+" : ""
      }${formatNumber(band.delta_db)} dB`;
      bar.style.height = `${Math.max(3, (Math.abs(value) / 12) * 46)}%`;
    } else {
      const value = Math.max(-80, Math.min(0, band.level_dbfs));
      wrapper.className = "spectrum-bar is-raw";
      wrapper.dataset.label = `${band.center_hz} Hz · ${formatNumber(
        band.level_dbfs,
      )} dBFS`;
      bar.style.height = `${Math.max(3, ((value + 80) / 80) * 92)}%`;
    }
    wrapper.setAttribute("aria-label", wrapper.dataset.label);
    wrapper.append(bar);
    chart.append(wrapper);
  });
}

function renderMonoCompatibility(result) {
  const measurement = result.mix.mono_compatibility;
  const statusNames = {
    clear: "No material loss detected",
    loss_detected: "Loss detected",
    unavailable: "Unavailable",
  };
  $("#mono-state").className = `mono-state is-${measurement.status}`;
  $("#mono-state").textContent = measurement.status.replace("_", " ");
  $("#mono-status-value").textContent =
    statusNames[measurement.status] || measurement.status;
  $("#mono-threshold").textContent = `${formatNumber(
    measurement.detection_threshold_db,
  )} dB`;
  $("#mono-floor").textContent = `${formatNumber(
    measurement.activity_floor_db,
  )} dB`;
  $("#mono-summary").textContent = measurement.summary;
  const regions = $("#mono-regions");
  regions.replaceChildren();
  if (!measurement.loss_regions.length) {
    regions.textContent = "None";
  } else {
    measurement.loss_regions.forEach((region) => {
      const item = document.createElement("span");
      item.textContent = `${Math.round(region.low_hz)}–${Math.round(
        region.high_hz,
      )} Hz · ${formatNumber(region.median_loss_db)} dB`;
      regions.append(item);
    });
  }
}

function renderTonalMap(result) {
  const map = result.mix.tonal_map;
  const bars = $("#tonal-bars");
  bars.replaceChildren();
  if (!map || map.status === "unavailable") { $("#tonal-summary").textContent = "Tonal map is unavailable for this signal."; return; }
  $("#tonal-summary").textContent = `Dominant pitch-class energy: ${map.dominant_pitch_class || "—"}. Tonal lead only, not automatic key detection.`;
  $("#tonal-confidence").textContent = `Confidence ${Math.round((map.confidence || 0) * 100)}%`;
  map.pitch_classes.forEach((item) => { const row = document.createElement("div"); row.className = "tonal-bar"; row.innerHTML = `<span>${item.name}</span><i><b style="width:${Math.min(100, item.share * 1000)}%"></b></i><em>${(item.share * 100).toFixed(1)}%</em>`; bars.append(row); });
}

function renderSignalIntelligence(result) {
  const map = result.mix.tonal_map || {};
  const key = map.key_candidate;
  const chord = map.chord_candidate;
  $("#key-candidate").textContent = key ? `${key.root} ${key.mode}` : "—";
  $("#key-confidence").textContent = key ? `score ${formatNumber(key.score, 2)}` : "Unavailable";
  $("#chord-candidate").textContent = chord ? `${chord.root} ${chord.quality}` : "—";
  $("#chord-confidence").textContent = chord ? `energy ${formatNumber(chord.score, 2)}` : "Unavailable";
  $("#noise-floor").textContent = result.mix.noise_floor_dbfs == null ? "—" : `${formatNumber(result.mix.noise_floor_dbfs)} dBFS`;
  const strip = $("#section-strip"); strip.replaceChildren();
  (result.mix.section_summaries || []).forEach((section) => {
    const item = document.createElement("div"); item.className = "section-chip";
    const tonal = section.tonal_map?.dominant_pitch_class || "—";
    item.textContent = `S${section.index} · ${tonal} · ${formatNumber(section.rms_dbfs)} dBFS`;
    strip.append(item);
  });
}

function renderFindings(result) {
  const section = $("#findings-section");
  const container = $("#findings-list");
  container.replaceChildren();
  section.hidden = result.findings.length === 0;
  $("#finding-count").textContent = `${result.findings.length} ${
    result.findings.length === 1 ? "finding" : "findings"
  }`;

  result.findings.forEach((finding, index) => {
    const card = document.createElement("article");
    card.className = "finding";
    const number = document.createElement("span");
    number.className = "finding-index";
    number.textContent = String(index + 1).padStart(2, "0");
    const body = document.createElement("div");
    const title = document.createElement("h4");
    title.textContent = finding.observation;
    const meaning = document.createElement("p");
    meaning.textContent = finding.possible_meaning;
    const details = document.createElement("dl");
    details.className = "finding-details";
    [
      ["Verify", finding.verification],
      ["Reversible experiment", finding.experiment],
    ].forEach(([label, text]) => {
      const group = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = text;
      group.append(term, description);
      details.append(group);
    });
    body.append(title, meaning, details);
    card.append(number, body);
    container.append(card);
  });
}

function buildGuideQuestions(result) {
  const questions = [];
  const primaryFinding = result.findings[0];
  const mono = result.mix.mono_compatibility;

  if (primaryFinding) {
    questions.push(
      {
        source: "Finding · measured evidence",
        question: "What should I check first?",
        answer: `${primaryFinding.observation} ${primaryFinding.possible_meaning}`,
      },
      {
        source: "Finding · listening verification",
        question: "How do I verify it by listening?",
        answer: primaryFinding.verification,
      },
      {
        source: "Finding · reversible experiment",
        question: "What small experiment can I try?",
        answer: primaryFinding.experiment,
      },
    );
  } else {
    questions.push(
      {
        source: "Analysis summary",
        question: "What does this analysis show?",
        answer: result.summary,
      },
      {
        source: "Finding policy",
        question: "Why was no correction suggested?",
        answer: result.comparison
          ? "The available comparison did not produce a measured difference beyond the documented finding thresholds. The measurements remain visible as context."
          : "No Reference Track or selected Genre Profile was used as a correction basis. The result therefore remains descriptive unless a direct Mono Fold-down loss is measured.",
      },
    );
  }

  if (result.mode === "pooled" && result.comparison) {
    questions.push({
      source: "Pooled released masters · interpretation boundary",
      question: "Why was my track not compared with a genre?",
      answer: `No single genre profile was clearly nearest, so the comparison target is ${result.comparison.target_name}: the pooled measurements of well-known released masters across every stored genre. Its range is wide, so a reported difference is large even for released masters in general. Select a Genre Profile for a narrower comparison.`,
    });
  }

  if (result.mode === "affinity" && result.comparison) {
    questions.push({
      source: "Closest technical profile · interpretation boundary",
      question: "Does this mean my mix is correct?",
      answer: `No single profile can determine whether a mix is correct. ${result.comparison.target_name} is only the nearest stored technical context for this track. Use any reported difference as a listening check, not as a mandatory correction.`,
    });
  }

  if (mono.status === "loss_detected") {
    const monoFinding = result.findings.find(
      (finding) => finding.code === "mono_fold_down_loss",
    );
    questions.push({
      source: "Direct measurement · Mono Fold-down",
      question: "How do I verify the Mono loss?",
      answer: monoFinding?.verification || mono.summary,
    });
  } else {
    questions.push({
      source: "Direct measurement · Mono Fold-down",
      question: "What does the Mono result mean?",
      answer: `${mono.summary} This result covers the measured fold-down energy only; it is not a universal mix-quality score.`,
    });
  }

  if (result.excluded_metrics.length) {
    const exclusions = result.excluded_metrics
      .slice(0, 2)
      .map(
        (item) => `${metricNames[item.metric] || item.metric}: ${item.reason}`,
      )
      .join(" ");
    questions.push({
      source: "Comparison policy",
      question: "Why were some metrics excluded?",
      answer: exclusions,
    });
  }

  const boundaryQuestion = {
    source: "Interpretation boundary",
    question: "What can this analysis not tell me?",
    answer: result.limitations.slice(0, 2).join(" "),
  };

  return [...questions.slice(0, 5), boundaryQuestion];
}

function renderGuideAnswer(question, button) {
  $$(".guide-question").forEach((item) => {
    const isSelected = item === button;
    item.classList.toggle("is-selected", isSelected);
    item.setAttribute("aria-pressed", String(isSelected));
  });
  $("#guide-answer-source").textContent = question.source;
  $("#guide-answer-title").textContent = question.question;
  $("#guide-answer-copy").textContent = question.answer;
}

function renderAnalysisGuide(result) {
  const container = $("#guide-questions");
  const questions = buildGuideQuestions(result);
  container.replaceChildren();

  questions.forEach((question, index) => {
    const button = document.createElement("button");
    const number = document.createElement("span");
    const copy = document.createElement("span");
    button.type = "button";
    button.className = "guide-question";
    button.setAttribute("aria-pressed", "false");
    number.textContent = String(index + 1).padStart(2, "0");
    copy.textContent = question.question;
    button.append(number, copy);
    button.addEventListener("click", () => renderGuideAnswer(question, button));
    container.append(button);
    if (index === 0) renderGuideAnswer(question, button);
  });
}

function renderAffinity(result) {
  const list = $("#affinity-list");
  list.replaceChildren();
  $("#affinity-notice").textContent = result.genre_affinity_notice;
  const statusLabel = {
    clear: "nearest profile is clearly separated",
    ambiguous: "no genre is clearly nearest",
    unavailable: "unavailable",
    not_requested: "ranking only",
  }[result.closest_profile_status] || "ranking only";
  $("#affinity-summary").textContent = result.genre_affinity.length
    ? `${result.genre_affinity.length} measured profiles · ${statusLabel}`
    : "Unavailable";

  if (!result.genre_affinity.length) {
    const empty = document.createElement("p");
    empty.textContent = "No comparable Genre Profile is available.";
    list.append(empty);
    return;
  }

  result.genre_affinity.forEach((affinity) => {
    const row = document.createElement("div");
    row.className = "affinity-item";
    const rank = document.createElement("span");
    rank.className = "affinity-rank";
    rank.textContent = String(affinity.rank).padStart(2, "0");
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = affinity.profile_name;
    const basis = document.createElement("small");
    basis.textContent =
      result.analysis_stage === "mix"
        ? "Spectral proximity"
        : "Spectral and master-measurement proximity";
    copy.append(name, basis);
    const distance = document.createElement("code");
    const share =
      typeof affinity.bands_within_range_share === "number"
        ? ` · ${Math.round(affinity.bands_within_range_share * 100)}% of bands inside its p25–p75`
        : "";
    const lead =
      typeof affinity.separation_db === "number"
        ? ` · leads by ${affinity.separation_db.toFixed(2)} dB`
        : "";
    distance.textContent = `${affinity.distance.toFixed(2)} dB${lead}${share}`;
    row.append(rank, copy, distance);
    list.append(row);
  });
}

function renderPolicy(result) {
  $("#policy-title").textContent =
    policyNames[result.comparison_policy] || result.comparison_policy;
  const compared = $("#compared-metrics");
  compared.replaceChildren();
  const included = result.compared_metrics.length
    ? result.compared_metrics
    : ["Direct measurements only"];
  included.forEach((metric) => {
    const tag = document.createElement("span");
    tag.className = "metric-tag";
    tag.textContent = metricNames[metric] || metric;
    compared.append(tag);
  });

  const excludedSection = $("#excluded-section");
  const excluded = $("#excluded-metrics");
  excluded.replaceChildren();
  excludedSection.hidden = result.excluded_metrics.length === 0;
  result.excluded_metrics.forEach((item) => {
    const row = document.createElement("div");
    row.className = "excluded-item";
    const title = document.createElement("strong");
    title.textContent = metricNames[item.metric] || item.metric;
    const reason = document.createElement("p");
    reason.textContent = item.reason;
    row.append(title, reason);
    excluded.append(row);
  });

  const limitations = $("#limitations");
  limitations.replaceChildren();
  $("#limitation-count").textContent = `${result.limitations.length} notes`;
  result.limitations.forEach((limitation) => {
    const item = document.createElement("li");
    item.textContent = limitation;
    limitations.append(item);
  });
}

function renderTrackMetadata(result) {
  const analysis = result.mix.analysis;
  const metadata = [
    `${formatTime(analysis.duration_seconds, true)}`,
    `${(analysis.sample_rate / 1000).toFixed(
      analysis.sample_rate % 1000 === 0 ? 0 : 1,
    )} kHz`,
    `${analysis.channels} ${analysis.channels === 1 ? "channel" : "channels"}`,
    analysis.analysis_status,
  ];
  $("#track-metadata").replaceChildren(
    ...metadata.map((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      return item;
    }),
  );
}

function renderResultContext(result) {
  const context = $("#result-context");
  if (result.mode === "pooled" && result.comparison) {
    const nearest = result.genre_affinity[0];
    context.hidden = false;
    $("#result-context-title").textContent =
      `No single genre is clearly nearest · compared with ${result.comparison.target_name}`;
    $("#result-context-copy").textContent =
      `${nearest ? `${nearest.profile_name} leads the genre ranking by only ${Number(nearest.separation_db).toFixed(2)} dB. ` : ""}The track was compared with the pooled distribution of well-known released masters across all stored genres. Select a Genre Profile above for a narrower comparison.`;
    return;
  }
  if (result.closest_profile_status === "ambiguous" && result.genre_affinity.length) {
    const nearest = result.genre_affinity[0];
    context.hidden = false;
    $("#result-context-title").textContent =
      "No stored profile is clearly nearest";
    $("#result-context-copy").textContent =
      `${nearest.profile_name} leads by only ${Number(nearest.separation_db).toFixed(2)} dB. The ranking is shown below, but no profile was used as a correction target, so no comparative guidance is given.`;
    return;
  }
  if (result.mode !== "affinity" || !result.comparison) {
    context.hidden = true;
    return;
  }
  context.hidden = false;
  $("#result-context-title").textContent =
    `Closest technical profile · ${result.comparison.target_name}`;
  $("#result-context-copy").textContent =
    "Automatically selected from stored measurement profiles. This is guidance, not genre classification or a quality verdict.";
}

function renderResults(result) {
  lastResult = result;
  const stage = result.analysis_stage === "mix" ? "Mix" : "Master";
  $("#result-title").textContent = `${stage} / ${
    result.mix.analysis.filename || "Track"
  }`;
  renderTrackMetadata(result);
  renderResultContext(result);
  renderWaveform(result);
  renderMeasurements(result);
  renderSpectrum(result);
  renderMonoCompatibility(result);
  renderTonalMap(result);
  renderSignalIntelligence(result);
  renderFindings(result);
  renderAnalysisGuide(result);
  renderAffinity(result);
  renderPolicy(result);
  $("#raw-data").textContent = JSON.stringify(result, null, 2);
}

function stopLoadingState() {
  if (loadingTimer) window.clearInterval(loadingTimer);
  loadingTimer = null;
}

function startLoadingState() {
  stopLoadingState();
  loadingStartedAt = Date.now();
  const labels = [
    ["Uploading audio", 0],
    ["Decoding signal", 2],
    ["Computing measurements", 4],
    ["Preparing report", 8],
  ];
  const update = () => {
    const elapsed = Math.floor((Date.now() - loadingStartedAt) / 1000);
    $("#loading-elapsed").textContent = formatTime(elapsed);
    const activeIndex = labels.reduce(
      (selected, [, threshold], index) =>
        elapsed >= threshold ? index : selected,
      0,
    );
    $("#loading-stage").textContent = labels[activeIndex][0];
    $$(".loading-steps li").forEach((item, index) => {
      item.classList.toggle("is-active", index === activeIndex);
      item.classList.toggle("is-complete", index < activeIndex);
    });
  };
  update();
  loadingTimer = window.setInterval(update, 1000);
}

function setView(view) {
  form.hidden = view !== "form";
  loadingPanel.hidden = view !== "loading";
  results.hidden = view !== "results";
  document.body.dataset.view = view;
  if (view === "loading") startLoadingState();
  else stopLoadingState();
}

let selectedMixFile = null;
let selectedReferenceFile = null;

fileInput.addEventListener("change", () => {
  selectedMixFile = fileInput.files?.[0] || null;
  renderSelectedFile(selectedMixFile);
});
referenceInput.addEventListener("change", () => {
  selectedReferenceFile = referenceInput.files?.[0] || null;
  renderReference(selectedReferenceFile);
  updateModePromise();
});

$("#remove-file").addEventListener("click", () => {
  fileInput.value = "";
  selectedMixFile = null;
  renderSelectedFile(null);
  setError();
});

["dragenter", "dragover"].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.remove("is-dragging");
  });
});
uploadZone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  selectedMixFile = file;
  renderSelectedFile(file);
});

$$('input[name="analysis_stage"]').forEach((input) =>
  input.addEventListener("change", updateModePromise),
);
$("#genre-select").addEventListener("change", updateModePromise);
$("#use-closest-profile").addEventListener("change", updateModePromise);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = selectedMixFile || fileInput.files?.[0];
  const refFile = selectedReferenceFile || referenceInput.files?.[0];
  if (!file || !validateAudioFile(file)) return;
  if (refFile && !validateAudioFile(refFile)) {
    return;
  }

  setError();
  setView("loading");
  try { loadingPanel.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
  try {
    let response;
    if (publicConfig?.cloud_uploads) {
      const mixObject = await createCloudUpload(file);
      let referenceObject = null;
      try {
        if (refFile) referenceObject = await createCloudUpload(refFile);
        response = await authorizedFetch("/api/analyze/cloud", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mix_object: mixObject,
            reference_object: referenceObject,
            genre: $("#genre-select").value || null,
            use_closest_profile: $("#use-closest-profile").checked,
            analysis_stage: $('input[name="analysis_stage"]:checked').value,
            reference_stage: refFile ? referenceStage.value : null,
          }),
        });
      } catch (error) {
        throw error;
      }
    } else {
      if (!file) {
        setError("Please select an audio file first.");
        return;
      }
function safeUploadFilename(filename) {
  if (!filename) return "track.wav";
  const ext = filename.split(".").pop()?.toLowerCase() || "wav";
  const safeExt = ["wav", "mp3"].includes(ext) ? ext : "wav";
  return `track.${safeExt}`;
}

      const payload = new FormData();
      payload.append("file", file, safeUploadFilename(file.name));
      payload.append("analysis_stage", $('input[name="analysis_stage"]:checked')?.value || "mix");
      if ($("#genre-select")?.value) {
        payload.append("genre", $("#genre-select").value);
      }
      if ($("#use-closest-profile")?.checked) {
        payload.append("use_closest_profile", "true");
      }
      if (refFile) {
        payload.append("reference", refFile, safeUploadFilename(refFile.name));
        if (referenceStage?.value) {
          payload.append("reference_stage", referenceStage.value);
        }
      }
      response = await authorizedFetch("/analyze/track", {
        method: "POST",
        body: payload,
      });
    }
    let body = null;
    try {
      body = await response.json();
    } catch (e) {
      const rawText = await response.text().catch(() => "");
      throw new Error(rawText || `Server error (${response.status} ${response.statusText})`);
    }
    if (!response.ok) {
      const detail = Array.isArray(body?.detail)
        ? body.detail.map((item) => item.msg).join(" ")
        : body?.detail;
      throw new Error(detail || "Analysis could not be completed.");
    }
    renderResults(body);
    setView("results");
    try { results.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (e) {}
  } catch (error) {
    setView("form");
    setError(error.message || "An unexpected error occurred during analysis.");
  }
});

$("#members-wall-action")?.addEventListener("click", requestWebsiteSignIn);

$("#sign-out-button").addEventListener("click", async () => {
  if (firebaseAuth && firebaseAuthApi) await firebaseAuthApi.signOut(firebaseAuth);
});

$("#download-result").addEventListener("click", () => {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `subverse-mix-analysis-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

$("#new-analysis").addEventListener("click", () => {
  form.reset();
  fileInput.value = "";
  referenceInput.value = "";
  $("#advanced-reference").open = false;
  renderSelectedFile(null);
  renderReference(null);
  updateModePromise();
  setError();
  setView("form");
  window.scrollTo({ top: 0, behavior: "smooth" });
});

$("#copy-raw-data").addEventListener("click", async () => {
  if (!lastResult) return;
  const button = $("#copy-raw-data");
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2));
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy unavailable";
  }
  window.setTimeout(() => {
    button.textContent = "Copy JSON";
  }, 1600);
});

Promise.all([initializeAccess(), loadGenres()])
  .then(() => {
    updateModePromise();
    setView("form");
    renderAccessState();
  })
  .catch((error) => {
    setAuthError(error.message || "The service could not be initialized.");
    $("#analysis-workspace").hidden = false;
  });
