/* common.js - CSRF-aware fetch helpers + delegated confirm dialogs (CSP forbids inline handlers). */
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  window.CSRF = meta ? meta.content : "";

  window.apiPost = async function (url, body) {
    const isForm = body instanceof FormData;
    const opts = { method: "POST", headers: { "X-CSRF-Token": window.CSRF }, body: isForm ? body : JSON.stringify(body) };
    if (!isForm) opts.headers["Content-Type"] = "application/json";
    let res;
    try { res = await fetch(url, opts); }
    catch (e) { return { ok: false, status: 0, error: "Cannot reach the server. Is the application still running?" }; }
    let data;
    try { data = await res.json(); }
    catch (e) { data = { ok: false, error: "The server returned an unreadable response (status " + res.status + ")." }; }
    data.status = res.status;
    if (res.status === 401) data.error = "Your session expired. Please log in again.";
    return data;
  };

  window.escapeHtml = function (s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  document.addEventListener("submit", function (ev) {
    const msg = ev.target.getAttribute && ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });
})();
