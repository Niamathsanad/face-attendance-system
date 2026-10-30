/* reports.js - draws the present/absent-by-date chart for the previewed report. */
(function () {
  const holder = document.getElementById("chartData"), canvas = document.getElementById("reportChart");
  if (!holder || !canvas) return;
  const d = JSON.parse(holder.textContent);
  new Chart(canvas, { type: "bar", data: { labels: d.labels, datasets: [
    { label: "Present", data: d.present, backgroundColor: "#2f9e44" }, { label: "Absent", data: d.absent, backgroundColor: "#e03131" }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } },
      scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } } });
})();
