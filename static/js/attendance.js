/* attendance.js - fills the correction modal from the clicked row. */
(function () {
  const modal = document.getElementById("correctModal");
  if (!modal) return;
  modal.addEventListener("show.bs.modal", function (ev) {
    const b = ev.relatedTarget;
    modal.querySelector("[name=session_id]").value = b.dataset.session;
    modal.querySelector("[name=student_id]").value = b.dataset.student;
    modal.querySelector("[name=status]").value = b.dataset.newstatus;
    modal.querySelector("#correctWho").textContent = b.dataset.name + " (" + b.dataset.code + ") - " + b.dataset.sessionname;
    modal.querySelector("[name=reason]").value = "";
  });
})();
