(function () {
  // Elements
  const secUpload = document.getElementById("sec-upload");
  const secProgress = document.getElementById("sec-progress");
  const secPreview = document.getElementById("sec-preview");
  const secResults = document.getElementById("sec-results");
  const secError = document.getElementById("sec-error");

  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const fileNameEl = document.getElementById("file-name");
  const urlInput = document.getElementById("url-input");
  const processBtn = document.getElementById("process-btn");

  const progressPct = document.getElementById("progress-pct");
  const progressFill = document.getElementById("progress-fill");
  const steps = {
    silence: document.getElementById("step-silence"),
    transcribe: document.getElementById("step-transcribe"),
    generate: document.getElementById("step-generate"),
  };

  const previewToggle = document.getElementById("preview-toggle");
  const previewLabel = document.getElementById("preview-label");
  const previewPlayer = document.getElementById("preview-player");
  const previewContinueBtn = document.getElementById("preview-continue-btn");

  const variationsGrid = document.getElementById("variations-grid");
  const transcriptToggle = document.getElementById("transcript-toggle");
  const transcriptBody = document.getElementById("transcript-body");
  const newVideoBtn = document.getElementById("new-video-btn");
  const errorMessage = document.getElementById("error-message");
  const errorRetryBtn = document.getElementById("error-retry-btn");

  const stylePickerContainer = document.getElementById("style-picker-container");

  const CAPTION_STYLES = [
    { name: "Georgia", family: "Georgia, serif" },
    { name: "Playfair Display", family: "'Playfair Display', serif" },
    { name: "Bebas Neue", family: "'Bebas Neue', sans-serif", uppercase: true },
    { name: "Poppins", family: "'Poppins', sans-serif" },
    { name: "Dancing Script", family: "'Dancing Script', cursive" },
    { name: "Oswald", family: "'Oswald', sans-serif", uppercase: true },
    { name: "Permanent Marker", family: "'Permanent Marker', cursive" },
    { name: "Abril Fatface", family: "'Abril Fatface', serif" },
    { name: "Quicksand", family: "'Quicksand', sans-serif" },
    { name: "Lobster", family: "'Lobster', cursive" },
    { name: "Lora", family: "'Lora', serif" },
    { name: "Inter", family: "'Inter', sans-serif" },
    { name: "Montserrat", family: "'Montserrat', sans-serif" },
    { name: "DM Sans", family: "'DM Sans', sans-serif" },
    { name: "Nunito", family: "'Nunito', sans-serif" },
    { name: "Raleway", family: "'Raleway', sans-serif" },
    { name: "Outfit", family: "'Outfit', sans-serif" },
  ];

  let selectedFile = null;
  let currentJobId = null;
  let pollTimer = null;
  let previewMode = false;
  let selectedCaptionStyle = "Georgia";

  // --- Preview Mode Toggle ---

  previewToggle.addEventListener("click", () => {
    previewMode = !previewMode;
    previewToggle.classList.toggle("active", previewMode);
    previewLabel.classList.toggle("on", previewMode);
  });

  // --- Upload ---

  function updateProcessBtn() {
    processBtn.disabled = !selectedFile && !urlInput.value.trim();
  }

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      selectFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) selectFile(fileInput.files[0]);
  });

  function selectFile(file) {
    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileNameEl.classList.remove("hidden");
    dropZone.classList.add("has-file");
    urlInput.value = "";
    updateProcessBtn();
  }

  urlInput.addEventListener("input", () => {
    if (urlInput.value.trim()) {
      selectedFile = null;
      fileNameEl.classList.add("hidden");
      dropZone.classList.remove("has-file");
      fileInput.value = "";
    }
    updateProcessBtn();
  });

  // --- Process ---

  processBtn.addEventListener("click", async () => {
    processBtn.disabled = true;
    const formData = new FormData();

    if (selectedFile) {
      formData.append("file", selectedFile);
    } else if (urlInput.value.trim()) {
      formData.append("drive_url", urlInput.value.trim());
    } else {
      return;
    }
    formData.append("preview_mode", previewMode ? "true" : "false");
    formData.append("caption_style", selectedCaptionStyle);

    try {
      const res = await fetch("/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }
      const data = await res.json();
      currentJobId = data.job_id;

      showSection("progress");
      startPolling();
    } catch (e) {
      showError(e.message);
    }
  });

  // --- Polling ---

  function startPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    pollStatus();
  }

  async function pollStatus() {
    if (!currentJobId) return;
    try {
      const res = await fetch("/status/" + currentJobId);
      if (!res.ok) throw new Error("Failed to fetch status");
      const job = await res.json();

      updateProgress(job);

      if (job.status === "preview_paused") {
        pollTimer = null;
        showPreview(job);
        return;
      }

      if (job.status === "rendering_all" || job.status === "rendering") {
        renderResults(job);
        showSection("results");
        pollTimer = setTimeout(pollStatus, 2000);
      } else if (job.status === "complete") {
        pollTimer = null;
        renderResults(job);
        showSection("results");
      } else if (job.status === "error") {
        pollTimer = null;
        showError(job.message);
      } else {
        pollTimer = setTimeout(pollStatus, 2000);
      }
    } catch (e) {
      pollTimer = null;
      showError(e.message);
    }
  }

  // --- Preview ---

  const previewStats = document.getElementById("preview-stats");
  const previewStartOver = document.getElementById("preview-start-over");

  function showPreview(job) {
    previewPlayer.src = "/preview/" + currentJobId;
    previewPlayer.load();

    const stats = job.silence_stats || {};
    if (previewStats) {
      previewStats.innerHTML =
        `<span>Original: <strong>${stats.original_duration || "—"}s</strong></span>` +
        `<span>Clean: <strong>${stats.clean_duration || "—"}s</strong></span>` +
        `<span>Removed: <strong>${stats.seconds_removed || "—"}s</strong></span>` +
        `<span>Regions: <strong>${stats.silence_regions_found || "—"}</strong></span>`;
    }
    showSection("preview");
  }

  previewContinueBtn.addEventListener("click", async () => {
    previewPlayer.pause();
    previewPlayer.src = "";
    previewContinueBtn.disabled = true;
    previewContinueBtn.textContent = "Resuming...";
    try {
      const res = await fetch(`/job/${currentJobId}/continue`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to resume");
    } catch (e) {
      showError(e.message);
      return;
    }
    previewContinueBtn.disabled = false;
    previewContinueBtn.textContent = "Looks good, continue \u2192";
    showSection("progress");
    startPolling();
  });

  previewStartOver.addEventListener("click", () => {
    previewPlayer.pause();
    previewPlayer.src = "";
    resetAll();
  });

  function updateProgress(job) {
    const pct = job.progress || 0;
    progressPct.textContent = pct + "%";
    progressFill.style.width = pct + "%";

    resetSteps();
    const msg = (job.message || "").toLowerCase();

    // Pipeline order: transcribe (10) → silence removal (35) → generate (60)
    if (pct >= 10) steps.transcribe.classList.add(pct > 10 ? "done" : "active");
    if (pct >= 35) steps.silence.classList.add(pct > 35 ? "done" : "active");
    if (pct >= 60) steps.generate.classList.add(pct > 60 ? "done" : "active");

    if (msg.includes("transcrib")) steps.transcribe.classList.add("active");
    else if (msg.includes("silence")) steps.silence.classList.add("active");
    else if (msg.includes("generat")) steps.generate.classList.add("active");
  }

  function resetSteps() {
    Object.values(steps).forEach((s) => s.classList.remove("active", "done"));
  }

  // --- Section badge helper ---

  function sectionBadge(section) {
    if (!section) return "";
    const cls = section.replace(/\s+/g, "_").toLowerCase();
    const label = section.replace(/_/g, " ");
    return `<span class="section-badge ${esc(cls)}">${esc(label)}</span>`;
  }

  // --- Build full script HTML ---

  function buildScriptHtml(script) {
    let html = "";
    (script || []).forEach((seg, i) => {
      const t0 = formatTime(seg.start);
      const t1 = formatTime(seg.end);
      const isHook = i === 0;
      const rowClass = isHook ? "script-item hook-row" : "script-item";
      html += `<li class="${rowClass}">
        <span class="script-order">${i + 1}</span>
        <span class="script-time">${t0} → ${t1}</span>
        <span class="script-content">
          ${sectionBadge(seg.section)}
          <span class="script-text">${esc(seg.text)}</span>
        </span>
      </li>`;
    });
    return html;
  }

  // --- Build preview text (first 2 sentences + ...) ---

  function buildPreview(script) {
    if (!script || script.length === 0) return "";
    const lines = script.slice(0, 2).map((s) => esc(s.text));
    let preview = lines.join(" ");
    if (script.length > 2) {
      preview += ` <span class="ellipsis">... (${script.length - 2} more)</span>`;
    }
    return preview;
  }

  // --- Results ---

  let cardsBuilt = false;

  function renderResults(job) {
    const variations = job.variations || [];
    const renders = job.renders || {};

    // Sort AS_IS last (defensive — backend already sorts)
    const sorted = [...variations].sort((a, b) => {
      const aIs = a.hook_type === "AS_IS" ? 1 : 0;
      const bIs = b.hook_type === "AS_IS" ? 1 : 0;
      return aIs - bIs;
    });

    // Build cards once, then only update status areas on subsequent calls
    if (!cardsBuilt) {
      variationsGrid.innerHTML = "";

      sorted.forEach((v) => {
        const card = document.createElement("div");
        card.className = "var-card";
        card.setAttribute("data-card-id", v.id);
        const varId = v.id;

        const hookLabel = (v.hook_type || "").replace(/_/g, " ");
        const scriptHtml = buildScriptHtml(v.script);
        const previewHtml = buildPreview(v.script);

        let whyHtml = "";
        (v.why_it_works || []).forEach((w) => {
          whyHtml += `<li class="why-item">${esc(w)}</li>`;
        });

        card.innerHTML = `
          <div class="var-card-header">
            <div class="var-num">${varId}</div>
            <div class="var-title">${esc(v.name)}</div>
            <span class="hook-badge">${esc(hookLabel)}</span>
          </div>
          <div class="var-card-body">
            <div class="var-strategy">${esc(v.strategy)}</div>
            <div class="var-preview">${previewHtml}</div>
            <button class="expand-btn" data-var-id="${varId}">+ Show full script</button>
            <div class="script-full" data-script-id="${varId}">
              <ul class="script-list">${scriptHtml}</ul>
              ${whyHtml ? `<ul class="why-list">${whyHtml}</ul>` : ""}
            </div>
            <div class="var-actions" data-var-id="${varId}"></div>
          </div>`;

        variationsGrid.appendChild(card);
      });

      // Bind expand buttons
      variationsGrid.querySelectorAll(".expand-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const vid = btn.getAttribute("data-var-id");
          const full = variationsGrid.querySelector(
            `.script-full[data-script-id="${vid}"]`
          );
          if (full.classList.contains("expanded")) {
            full.classList.remove("expanded");
            btn.textContent = "+ Show full script";
          } else {
            full.classList.add("expanded");
            btn.textContent = "\u2212 Hide full script";
          }
        });
      });

      cardsBuilt = true;
    }

    // Update status areas for each variation
    sorted.forEach((v) => {
      const varId = String(v.id);
      const actionsDiv = variationsGrid.querySelector(
        `.var-actions[data-var-id="${varId}"]`
      );
      if (!actionsDiv) return;

      const renderInfo = renders[varId] || { status: "queued" };
      const status = renderInfo.status || "queued";

      if (status === "done" && renderInfo.filename) {
        actionsDiv.innerHTML =
          `<span class="status-badge status-done">\u2713 Done</span>` +
          `<a class="download-btn" href="/download/${currentJobId}/${renderInfo.filename}" download>&#11015; Download MP4</a>`;
      } else if (status === "rendering") {
        actionsDiv.innerHTML =
          `<span class="status-badge status-rendering">\u25CF Rendering...</span>`;
      } else if (status === "failed") {
        actionsDiv.innerHTML =
          `<span class="status-badge status-failed">\u2717 Failed</span>`;
      } else {
        actionsDiv.innerHTML =
          `<span class="status-badge status-queued">\u25CB Queued</span>`;
      }
    });

    // Transcript
    if (job.transcript && job.transcript.full_text) {
      document.getElementById("transcript-section").classList.remove("hidden");
      transcriptBody.textContent = job.transcript.full_text;
    }
  }

  // --- Caption Style Picker (on upload page) ---

  function buildStylePicker() {
    let chipsHtml = "";
    CAPTION_STYLES.forEach((s) => {
      const sel = s.name === selectedCaptionStyle ? " selected" : "";
      const uc = s.uppercase ? "; text-transform: uppercase" : "";
      chipsHtml += `<div class="style-chip${sel}" data-style="${esc(s.name)}" style="font-family: ${s.family}${uc}">${esc(s.name)}</div>`;
    });

    stylePickerContainer.innerHTML = `
      <div class="style-picker-wrap">
        <div class="style-picker-label">Caption Style (optional)</div>
        <div class="style-picker">${chipsHtml}</div>
      </div>`;

    stylePickerContainer.querySelectorAll(".style-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        stylePickerContainer.querySelectorAll(".style-chip").forEach((c) => c.classList.remove("selected"));
        chip.classList.add("selected");
        selectedCaptionStyle = chip.getAttribute("data-style");
      });
    });
  }

  buildStylePicker();

  // Transcript toggle
  transcriptToggle.addEventListener("click", () => {
    transcriptBody.classList.toggle("hidden");
    transcriptToggle.classList.toggle("open");
  });

  // --- Navigation ---

  function showSection(name) {
    secUpload.classList.remove("active");
    secProgress.classList.remove("active");
    secPreview.classList.remove("active");
    secResults.classList.remove("active");
    secError.classList.remove("active");

    if (name === "upload") secUpload.classList.add("active");
    else if (name === "progress") secProgress.classList.add("active");
    else if (name === "preview") secPreview.classList.add("active");
    else if (name === "results") secResults.classList.add("active");
    else if (name === "error") secError.classList.add("active");
  }

  function showError(msg) {
    errorMessage.textContent = msg;
    showSection("error");
  }

  function resetAll() {
    currentJobId = null;
    selectedFile = null;
    cardsBuilt = false;
    selectedCaptionStyle = "Georgia";
    buildStylePicker();
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    fileInput.value = "";
    urlInput.value = "";
    fileNameEl.classList.add("hidden");
    dropZone.classList.remove("has-file");
    processBtn.disabled = true;
    progressPct.textContent = "0%";
    progressFill.style.width = "0%";
    resetSteps();
    variationsGrid.innerHTML = "";
    transcriptBody.textContent = "";
    transcriptBody.classList.add("hidden");
    transcriptToggle.classList.remove("open");
    previewPlayer.pause();
    previewPlayer.src = "";
    showSection("upload");
  }

  newVideoBtn.addEventListener("click", resetAll);
  errorRetryBtn.addEventListener("click", resetAll);

  // --- Init: ensure upload section is visible on page load ---
  showSection("upload");

  // --- Helpers ---

  function formatTime(sec) {
    if (sec == null) return "0:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 10);
    return `${m}:${s.toString().padStart(2, "0")}.${ms}`;
  }

  function esc(str) {
    if (!str) return "";
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
})();
