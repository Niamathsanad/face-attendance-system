/* enroll.js - capture several face photos (webcam) or choose files, then send to the server. */
(function () {
  const root = document.getElementById("enrollRoot");
  const studentId = root.dataset.studentId;
  const minImages = parseInt(root.dataset.min, 10), maxImages = parseInt(root.dataset.max, 10);
  const video = document.getElementById("video"), placeholder = document.getElementById("placeholder");
  const camBtn = document.getElementById("camBtn"), snapBtn = document.getElementById("snapBtn"), autoBtn = document.getElementById("autoBtn");
  const thumbs = document.getElementById("thumbs"), countEl = document.getElementById("count");
  const saveBtn = document.getElementById("saveBtn"), msg = document.getElementById("msg"), fileInput = document.getElementById("fileInput");
  const cam = new Camera(video);
  let shots = [];            // data URLs, held in memory only

  function show(text, kind) { msg.className = "alert alert-" + kind; msg.innerHTML = text; msg.classList.remove("d-none"); }

  function render() {
    thumbs.innerHTML = "";
    shots.forEach((s, i) => {
      const w = document.createElement("span"); w.className = "thumb-wrap me-2 mb-2";
      const img = document.createElement("img"); img.src = s; img.className = "thumb";
      const b = document.createElement("button"); b.type = "button"; b.className = "btn btn-danger"; b.textContent = "x";
      b.title = "Remove"; b.addEventListener("click", () => { shots.splice(i, 1); render(); });
      w.append(img, b); thumbs.append(w);
    });
    countEl.textContent = shots.length + " / " + maxImages + " (minimum " + minImages + ")";
    saveBtn.disabled = shots.length < 1;
  }

  function add(dataUrl) { if (shots.length >= maxImages) { show("Maximum of " + maxImages + " images reached.", "warning"); return false; } shots.push(dataUrl); render(); return true; }

  camBtn.addEventListener("click", async () => {
    if (cam.running) { cam.stop(); placeholder.style.display = "grid"; camBtn.textContent = "Start camera"; snapBtn.disabled = autoBtn.disabled = true; return; }
    try { await cam.start(); placeholder.style.display = "none"; camBtn.textContent = "Stop camera"; snapBtn.disabled = autoBtn.disabled = false; msg.classList.add("d-none"); }
    catch (e) { show(escapeHtml(e.message), "danger"); }
  });
  snapBtn.addEventListener("click", () => { const d = cam.capture(640, 0.9); if (d) add(d); });
  autoBtn.addEventListener("click", async () => {
    autoBtn.disabled = snapBtn.disabled = true;
    for (let i = 0; i < 5; i++) {
      show("Auto-capture " + (i + 1) + "/5 - look at the camera and slowly turn your head a little.", "info");
      await new Promise(r => setTimeout(r, 900));
      const d = cam.capture(640, 0.9); if (!d || !add(d)) break;
    }
    msg.classList.add("d-none"); autoBtn.disabled = snapBtn.disabled = !cam.running;
  });

  fileInput.addEventListener("change", () => {
    Array.from(fileInput.files).forEach(f => {
      if (!f.type.startsWith("image/")) return;
      const r = new FileReader(); r.onload = () => add(r.result); r.readAsDataURL(f);
    });
    fileInput.value = "";
  });

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true; show("Checking images and creating face templates...", "info");
    const r = await apiPost("/api/students/" + studentId + "/enroll", { images: shots });
    if (r.ok) {
      cam.stop(); shots = []; render();
      show("Enrollment complete: " + r.accepted + " image(s) accepted, " + r.rejected + " rejected. Photos were NOT stored - only face templates. Redirecting...", "success");
      setTimeout(() => { window.location = r.redirect; }, 1800);
    } else {
      show(escapeHtml(r.error || "Enrollment failed."), "danger"); saveBtn.disabled = shots.length < 1;
    }
  });
  window.addEventListener("beforeunload", () => cam.stop());
  render();
})();
