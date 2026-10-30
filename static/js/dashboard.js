/* dashboard.js - loads real statistics from /api/dashboard and draws Chart.js charts. */
(function () {
  const charts = {};
  const css = getComputedStyle(document.documentElement);
  const GREEN = "#2f9e44", RED = "#e03131", BLUE = "#3b5bdb";

  function upsert(id, config) {
    if (charts[id]) { charts[id].data = config.data; charts[id].update(); return; }
    charts[id] = new Chart(document.getElementById(id), config);
  }
  const opts = (extra) => Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }, extra || {});
  const pctAxis = { y: { min: 0, max: 100, title: { display: true, text: "Attendance %" } } };

  function set(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

  function render(d) {
    const s = d.stats;
    set("statTotal", s.total_registered); set("statPresent", s.present_today); set("statAbsent", s.absent_today);
    set("statPct", s.percentage_today === null ? "-" : s.percentage_today + "%");
    set("statNote", s.sessions_today ? s.sessions_today + " session(s) today" : "No session held today");

    const tb = document.getElementById("recentBody"); tb.innerHTML = "";
    if (!d.recent.length) { tb.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No attendance recorded yet.</td></tr>'; }
    d.recent.forEach(r => {
      const tr = document.createElement("tr");
      const typeBadge = r.type === "Manual correction" ? "warning" : "info";
      tr.innerHTML = "<td>" + escapeHtml(r.name) + '<div class="small-muted">' + escapeHtml(r.student_code) + "</div></td>" +
        '<td><span class="badge badge-soft-' + (r.status === "Present" ? "success" : "danger") + '">' + escapeHtml(r.status) + "</span></td>" +
        '<td><span class="badge badge-soft-' + typeBadge + '">' + escapeHtml(r.type) + "</span></td>" +
        "<td>" + escapeHtml(r.session) + "</td><td>" + escapeHtml(r.time) + "</td>";
      tb.appendChild(tr);
    });

    upsert("dailyChart", { type: "bar", data: { labels: d.daily.labels, datasets: [
      { label: "Present", data: d.daily.present, backgroundColor: GREEN, stack: "a" },
      { label: "Absent", data: d.daily.absent, backgroundColor: RED, stack: "a" }] },
      options: opts({ scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } }) });
    upsert("weeklyChart", { type: "line", data: { labels: d.weekly.labels, datasets: [
      { label: "Attendance %", data: d.weekly.percentage, borderColor: BLUE, backgroundColor: BLUE + "33", fill: true, tension: .3, spanGaps: true }] },
      options: opts({ scales: pctAxis }) });
    upsert("monthlyChart", { type: "bar", data: { labels: d.monthly.labels, datasets: [
      { label: "Attendance %", data: d.monthly.percentage, backgroundColor: BLUE }] },
      options: opts({ scales: pctAxis }) });

    const mt = document.getElementById("monthlyBody"); mt.innerHTML = "";
    d.monthly.labels.forEach((lab, i) => {
      const p = d.monthly.percentage[i];
      mt.insertAdjacentHTML("beforeend", "<tr><td>" + escapeHtml(lab) + "</td><td>" + d.monthly.expected[i] + "</td><td>" +
        d.monthly.present[i] + "</td><td>" + d.monthly.absent[i] + "</td><td>" + (p === null ? "-" : p + "%") + "</td></tr>");
    });
  }

  async function load() {
    try { const r = await fetch("/api/dashboard", { headers: { Accept: "application/json" } });
      if (r.status === 401) { window.location = "/login"; return; }
      render(await r.json()); } catch (e) { console.error("Dashboard load failed", e); }
  }
  load(); setInterval(load, 20000);
})();
