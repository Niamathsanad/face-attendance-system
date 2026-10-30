/* recognition.js - live recognition: send a frame, draw boxes, show events. */
(function () {
  const video = document.getElementById("video");
  const canvas = document.getElementById("overlay");
  const ctx = canvas.getContext("2d");
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  const placeholder = document.getElementById("placeholder");
  const statusEl = document.getElementById("statusLine");
  const logEl = document.getElementById("eventLog");
  const cam = new Camera(video);
  let running = false;
  const logged = new Set();

  const COLORS = { marked: "#2f9e44", already: "#1c7ed6", verifying: "#f08c00", recognized: "#f08c00",
                   no_session: "#f08c00", out_of_scope: "#868e96", unknown: "#e03131", error: "#862e9c" };
  const BADGE = { marked: "success", already: "info", verifying: "warning", recognized: "warning",
                  no_session: "warning", out_of_scope: "secondary", unknown: "danger", error: "danger" };
  const STATUS_TEXT = { marked: "PRESENT - marked", already: "Already marked", verifying: "Verifying...",
                        recognized: "Recognised", no_session: "No open session", out_of_scope: "Not in this session",
                        unknown: "Unknown Person", error: "Error" };

  function setStatus(msg, kind) { statusEl.className = "alert alert-" + kind + " py-2 mb-3"; statusEl.textContent = msg; }

  function draw(faces, frame) {
    canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const sx = canvas.width / frame.width, sy = canvas.height / frame.height;
    faces.forEach(f => {
      const [x1, y1, x2, y2] = f.bbox; const color = COLORS[f.status] || "#e03131";
      ctx.lineWidth = 3; ctx.strokeStyle = color; ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
      const text = f.label + " - " + (STATUS_TEXT[f.status] || f.status) + (f.score != null ? " (" + f.score.toFixed(2) + ")" : "");
      ctx.font = "bold 15px system-ui"; const w = ctx.measureText(text).width + 12;
      const ty = Math.max(22, y1 * sy);
      ctx.fillStyle = color; ctx.fillRect(x1 * sx, ty - 22, w, 22);
      ctx.fillStyle = "#fff"; ctx.fillText(text, x1 * sx + 6, ty - 6);
    });
  }

  function addLog(f) {
    const key = f.status + ":" + (f.student_code || "unknown");
    if (f.status === "marked" || !logged.has(key)) {
      if (f.status !== "marked") logged.add(key);
      const t = new Date().toLocaleTimeString();
      const li = document.createElement("div");
      li.className = "d-flex justify-content-between align-items-center border-bottom py-2";
      li.innerHTML = '<div><strong>' + escapeHtml(f.label) + '</strong> <span class="small-muted">' +
        escapeHtml(f.student_code || "") + '</span><div class="small-muted">' + escapeHtml(f.message) + '</div></div>' +
        '<div class="text-end"><span class="badge badge-soft-' + (BADGE[f.status] || "secondary") + '">' +
        escapeHtml(STATUS_TEXT[f.status] || f.status) + '</span><div class="small-muted">' + t + '</div></div>';
      logEl.prepend(li);
      while (logEl.children.length > 40) logEl.removeChild(logEl.lastChild);
    }
  }

  async function loop() {
    if (!running) return;
    const img = cam.capture(640, 0.7);
    if (img) {
      const r = await apiPost("/api/recognize", { image: img });
      if (!running) return;
      if (!r.ok) {
        setStatus(r.error || "Recognition error.", "danger");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (r.status === 401) { stop(); return; }
      } else {
        draw(r.faces, r.frame);
        r.faces.forEach(addLog);
        if (!r.session) setStatus("No attendance session is open. Faces are recognised but NOTHING is recorded. Start a session first.", "warning");
        else if (r.gallery_people === 0) setStatus("Session '" + r.session.name + "' is open, but nobody has enrolled face data yet.", "warning");
        else setStatus("Session '" + r.session.name + "' is open - " + (r.faces.length ? r.faces.length + " face(s) in view." : "waiting for a face..."), "success");
      }
    }
    setTimeout(loop, 400);
  }

  async function start() {
    startBtn.disabled = true;
    try { await cam.start(); } catch (e) { setStatus(e.message, "danger"); startBtn.disabled = false; return; }
    placeholder.style.display = "none"; running = true; stopBtn.disabled = false;
    setStatus("Camera started. Looking for faces...", "info"); loop();
  }
  function stop() {
    running = false; cam.stop(); ctx.clearRect(0, 0, canvas.width, canvas.height);
    placeholder.style.display = "grid"; startBtn.disabled = false; stopBtn.disabled = true;
    setStatus("Camera stopped. No video is stored.", "secondary");
  }
  startBtn.addEventListener("click", start);
  stopBtn.addEventListener("click", stop);
  window.addEventListener("beforeunload", () => cam.stop());
})();
